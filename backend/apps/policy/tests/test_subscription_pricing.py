"""Audit batch 5: the one Subscription fee estimator
(apps.policy.subscription_pricing).

    depreciation = price x (1 - residual) / tenure
    funding      = price x (1 + residual) / 2 x funding% / 100 / 12
    bundled      = (road tax + insurance + maintenance) / 12
    fee          = (depreciation + funding + bundled) x (1 + margin% / 100)

Unrounded Decimal intermediates, rounded once at the end. The golden fees were
recomputed independently of the code (a standalone script) and agree to the sen.
"""

import importlib
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, transaction

from apps.policy.models import (
    ContractPenaltyRule,
    MileageBand,
    ResidualBaseline,
    SubscriptionPlan,
    SubscriptionPolicy,
)
from apps.policy.operating_costs import estimate_operating_costs
from apps.policy.subscription_pricing import (
    SubscriptionConfigError,
    included_km_per_year,
    offered_tenures,
    resolve_subscription_fee,
    tenure_message,
)
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal
residual_seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")
policy_seed = importlib.import_module("apps.policy.migrations.0020_seed_subscription_policy")


def make_vehicle(brand_name, name, trim, msrp, kw, powertrain, cc):
    brand, _ = Brand.objects.get_or_create(name=brand_name, defaults={"tier_code": "2"})
    residual_seed.seed_brand_adjustments(django_apps)
    vehicle = VehicleModel.objects.create(
        brand=brand, name=name, trim=trim, body_segment=BodySegment.SEDAN, msrp=msrp,
        engine_capacity_kw=kw, powertrain=powertrain, engine_capacity_cc=cc,
    )
    vehicle.refresh_from_db()
    return vehicle


@pytest.fixture
def bmw():
    return make_vehicle("BMW", "3 Series", "320i Sport", "265800.00", "135.00", "petrol", 1998)


@pytest.fixture
def macan_ev():
    return make_vehicle("Porsche", "Macan Electric", "Macan RWD", "575000.00", "261.10", "bev", None)


@pytest.fixture
def alphard():
    return make_vehicle("Toyota", "Alphard", "2.4 Executive Lounge", "548000.00", "201.53", "petrol", 2393)


def fee(vehicle, tenure, band=MileageBand.STANDARD):
    return resolve_subscription_fee(vehicle, tenure, band)


# --- the seeded policy ---------------------------------------------------------


def test_the_seeded_policy_is_one_row_of_planning_assumptions():
    policy = SubscriptionPolicy.objects.get(is_active=True)

    assert (policy.min_tenure_months, policy.max_tenure_months) == (12, 36)
    assert (policy.funding_rate_percent, policy.margin_percent) == (D("4.5000"), D("12.0000"))
    assert (policy.deposit_months, policy.very_high_km_cap) == (D("2.00"), 35000)  # Run 3 fix batch 6: was 40,000
    assert policy.source_note == "Planning estimate - edit in admin. Real subscription terms vary by provider."


def test_re_running_the_seed_never_overwrites_an_admin_edit_or_adds_a_second_policy():
    policy = SubscriptionPolicy.objects.get(is_active=True)
    policy.margin_percent = D("20.0000")
    policy.source_note = "Edited by an admin"
    policy.save()

    policy_seed.forwards(django_apps, None)
    policy_seed.forwards(django_apps, None)

    assert SubscriptionPolicy.objects.filter(is_active=True).count() == 1
    policy.refresh_from_db()
    assert (policy.margin_percent, policy.source_note) == (D("20.0000"), "Edited by an admin")


def test_the_database_allows_only_one_active_policy_and_a_sane_tenure_range():
    with pytest.raises(IntegrityError), transaction.atomic():
        SubscriptionPolicy.objects.create(effective_from="2026-10-07")
    SubscriptionPolicy.objects.update(is_active=False)
    with pytest.raises(IntegrityError), transaction.atomic():
        SubscriptionPolicy.objects.create(min_tenure_months=40, max_tenure_months=12, effective_from="2026-10-07")


# --- golden fees (standard band) -------------------------------------------------
# Run 3 fix batch 6: the standard residuals moved with the recalibrated band (policy 0028);
# recomputed by a standalone script that first reproduced every old golden from the old grid.
# old -> new: BMW 7,423.82 / 6,466.23 / 5,701.93 -> 7,164.34 / 6,339.48 / 5,563.90;
# Macan Electric 17,706.85 / 14,830.32 / 12,908.60 -> 17,145.54 / 14,556.12 / 12,610.01;
# Alphard (saloon fixture) 12,305.15 / 11,865.29 / 10,801.01 -> 11,770.19 / 11,603.97 / 10,516.44.


@pytest.mark.parametrize(
    "fixture, tenure, residual, expected",
    [
        ("bmw", 12, "0.7807", "7164.34"),
        ("bmw", 24, "0.6207", "6339.48"),
        ("bmw", 36, "0.5179", "5563.90"),
        ("macan_ev", 12, "0.7507", "17145.54"),
        ("macan_ev", 24, "0.5907", "14556.12"),
        ("macan_ev", 36, "0.4879", "12610.01"),
        ("alphard", 12, "0.8407", "11770.19"),
        ("alphard", 24, "0.6807", "11603.97"),
        ("alphard", 36, "0.5779", "10516.44"),
    ],
)
def test_golden_fees(request, fixture, tenure, residual, expected):
    quote = fee(request.getfixturevalue(fixture), tenure)

    assert quote.source == "estimate"
    assert quote.components["residual_ratio"] == D(residual)
    assert quote.fee_monthly == D(expected)


def test_the_bmw_36_month_components_and_basis_by_hand(bmw):
    """Residual 0.5179 (Run 3 fix batch 6; was 0.50): depreciation = 265800 x 0.4821 / 36
    = 3,559.51; funding = 265800 x 1.5179 / 2 x 4.5% / 12 = 756.48; bundled = (379.00 +
    4,784.40 + 2,658.00) / 12 = 651.78; (3559.5050 + 756.4832 + 651.7833) x 1.12 = 5,563.90."""
    costs = estimate_operating_costs(bmw)
    assert (costs.road_tax_annual, costs.insurance_annual, costs.maintenance_annual) == (
        D("379.00"), D("4784.40"), D("2658.00"))

    quote = fee(bmw, 36)

    assert quote.components["depreciation_monthly"] == D("3559.51")
    assert quote.components["funding_monthly"] == D("756.48")
    assert quote.components["bundled_monthly"] == D("651.78")
    assert quote.basis == (
        "Estimate: depreciation RM 3,559.51 + funding RM 756.48 + road tax, insurance and maintenance "
        "RM 651.78, plus 12% margin"
    )


# --- how the fee moves -----------------------------------------------------------


def test_a_longer_tenure_is_cheaper_per_month_for_the_same_car_and_band(bmw):
    fees = [fee(bmw, tenure).fee_monthly for tenure in (12, 24, 36)]

    assert fees == sorted(fees, reverse=True) and len(set(fees)) == 3


def test_a_higher_mileage_band_is_dearer_because_its_residual_is_lower(bmw):
    fees = [fee(bmw, 36, band).fee_monthly for band in ("low", "standard", "high", "very_high")]

    assert fees == sorted(fees) and len(set(fees)) == 4
    # by hand at 36 months, residuals 0.5500 / 0.5179 / 0.4750 / 0.4250 (Run 3 fix batch 6;
    # were 0.55 / 0.50 / 0.45 / 0.40), bundled 651.7833 each:
    #   low       (3322.50 + 772.4813 + 651.7833) x 1.12 = 5,316.38 (unchanged)
    #   very_high (4245.4167 + 707.6925 + 651.7833) x 1.12 = 6,280.27 (was 6,473.05)
    assert (fees[0], fees[3]) == (D("5316.38"), D("6280.27"))
    assert fees[2] == D("5894.71")  # was 6,087.49


def test_an_electric_car_costs_more_than_the_same_price_petrol_car_to_subscribe_to(bmw, macan_ev):
    # the BEV's -8 point residual and 2.3% insurance both push the fee up
    assert fee(macan_ev, 36).components["residual_ratio"] == D("0.4879")
    assert fee(macan_ev, 36).fee_monthly / macan_ev.msrp > fee(bmw, 36).fee_monthly / bmw.msrp


# --- provider quote override ---------------------------------------------------------


def test_an_active_quote_overrides_the_estimate_and_ignores_tenure_and_band(bmw):
    SubscriptionPlan.objects.create(vehicle=bmw, fee_monthly="6000.00")

    quotes = [fee(bmw, tenure, band) for tenure in (12, 24, 36) for band in ("low", "very_high")]

    assert {q.fee_monthly for q in quotes} == {D("6000.00")}
    assert {q.source for q in quotes} == {"quote"}
    assert {q.basis for q in quotes} == {"Provider quote - fixed fee"}
    assert all(q.components is None for q in quotes)


def test_an_archived_quote_is_ignored(bmw):
    SubscriptionPlan.objects.create(vehicle=bmw, fee_monthly="6000.00", is_active=False)

    assert fee(bmw, 36).fee_monthly == D("5563.90")


def test_a_quote_never_raises_for_a_car_that_cannot_be_costed(bmw):
    VehicleModel.objects.filter(pk=bmw.pk).update(powertrain="", engine_capacity_cc=None)
    bmw.refresh_from_db()
    SubscriptionPlan.objects.create(vehicle=bmw, fee_monthly="6000.00")

    assert fee(bmw, 36).fee_monthly == D("6000.00")  # the fee needs no running costs; only the net offset does


def test_a_quote_does_not_bypass_the_tenure_gate(bmw):
    SubscriptionPlan.objects.create(vehicle=bmw, fee_monthly="6000.00")

    with pytest.raises(SubscriptionConfigError):
        fee(bmw, 48)


# --- the tenure gate -----------------------------------------------------------------


def test_the_offered_tenures_are_the_policy_range_intersected_with_the_baseline():
    assert offered_tenures(SubscriptionPolicy.objects.get(is_active=True)) == [12, 24, 36]


@pytest.mark.parametrize("tenure", [18, 30, 48, 60, 72, 108])
def test_a_tenure_outside_the_policy_or_without_a_baseline_raises_the_friendly_error(bmw, tenure):
    # 18 and 30 are inside 12-36 but have no baseline row (12-month steps);
    # 48 and 60 have a baseline (GFV runs to 60) but are beyond the policy's 36.
    with pytest.raises(SubscriptionConfigError) as excinfo:
        fee(bmw, tenure)

    assert str(excinfo.value) == "Subscription plans run for 12, 24 or 36 months."


def test_the_message_is_built_from_the_real_data_never_hard_coded(bmw):
    SubscriptionPolicy.objects.update(max_tenure_months=24)
    with pytest.raises(SubscriptionConfigError) as excinfo:
        fee(bmw, 36)
    assert str(excinfo.value) == "Subscription plans run for 12 or 24 months."

    ResidualBaseline.objects.filter(tenure_months=24).update(is_active=False)  # baseline gone for 24
    with pytest.raises(SubscriptionConfigError) as excinfo:
        fee(bmw, 24)
    assert str(excinfo.value) == "Subscription plans run for 12 months."

    ResidualBaseline.objects.update(is_active=False)
    with pytest.raises(SubscriptionConfigError) as excinfo:
        fee(bmw, 12)
    assert str(excinfo.value) == "Subscription plans aren't offered for any tenure right now."


def test_tenure_message_wording():
    assert tenure_message([12, 24, 36]) == "Subscription plans run for 12, 24 or 36 months."
    assert tenure_message([12, 24]) == "Subscription plans run for 12 or 24 months."
    assert tenure_message([12]) == "Subscription plans run for 12 months."


def test_an_edited_policy_changes_the_fee_with_no_deploy(bmw):
    SubscriptionPolicy.objects.update(margin_percent=D("0"), funding_rate_percent=D("0"))

    # margin 0, funding 0: (3559.5050 + 651.7833) = 4,211.29 (was 4,343.45 on the old 0.50 residual)
    assert fee(bmw, 36).fee_monthly == D("4211.29")


def test_no_active_policy_means_subscription_is_unavailable_not_guessed(bmw):
    SubscriptionPolicy.objects.update(is_active=False)

    with pytest.raises(SubscriptionConfigError) as excinfo:
        fee(bmw, 36)

    assert str(excinfo.value) == "Subscription pricing isn't configured."


# --- a car that cannot be costed / priced ----------------------------------------------


def test_a_car_with_incomplete_specs_raises_with_its_reason_never_a_guess(bmw):
    VehicleModel.objects.filter(pk=bmw.pk).update(powertrain="", engine_capacity_cc=None)
    bmw.refresh_from_db()

    with pytest.raises(SubscriptionConfigError) as excinfo:
        fee(bmw, 36)

    assert "missing its specs" in str(excinfo.value)


def test_a_car_whose_residual_cannot_be_resolved_raises(bmw):
    ResidualBaseline.objects.filter(tenure_months=36, mileage_band="high").update(is_active=False)

    with pytest.raises(SubscriptionConfigError):
        fee(bmw, 36, MileageBand.HIGH)
    assert fee(bmw, 36).fee_monthly == D("5563.90")  # other bands unaffected


# --- included kilometres -----------------------------------------------------------------


@pytest.mark.parametrize(
    "band, km", [("low", 10000), ("standard", 15000), ("high", 25000), ("very_high", 35000)]
)
def test_included_km_is_the_bands_limit_from_the_policy(band, km):
    # Run 3 fix batch 6: was 10,000 / 20,000 / 30,000 / 40,000; the seeded policy limits.
    assert included_km_per_year(SubscriptionPolicy.objects.get(is_active=True), band) == km


def test_every_allowance_follows_the_policy_value():
    SubscriptionPolicy.objects.update(low_km_cap=9000, standard_km_cap=16000, high_km_cap=27000, very_high_km_cap=45000)
    policy = SubscriptionPolicy.objects.get(is_active=True)

    assert [included_km_per_year(policy, band) for band in MileageBand.values] == [9000, 16000, 27000, 45000]


def test_the_mileage_note_names_the_brand_rule_or_the_default(bmw):
    from apps.comparisons.services import _mileage_note

    assert _mileage_note(bmw.brand, 20000) == (
        "Includes up to 20,000 km a year. Kilometres above that are billed per km "
        "(RM 0.50/km under the default contract rule)."
    )
    ContractPenaltyRule.objects.create(
        brand=bmw.brand, excess_mileage_charge_per_km="0.80", early_termination_months="6",
        wear_tear_tolerance_description="x",
    )
    assert _mileage_note(bmw.brand, 30000) == (
        "Includes up to 30,000 km a year. Kilometres above that are billed per km "
        "(RM 0.80/km under this brand's contract rule)."
    )
    ContractPenaltyRule.objects.update(is_active=False)
    assert _mileage_note(bmw.brand, 10000) == "Includes up to 10,000 km a year."
