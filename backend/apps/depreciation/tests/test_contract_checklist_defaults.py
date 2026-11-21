"""The contract checklist (audit batch 4, reworked in run 1 / B7): the brand's
own ContractPenaltyRule if it has one, else the single default rule - and two
early exits that are never mixed up:

  - settling a HIRE PURCHASE loan early: the reducing-balance amount to settle
    (settlement_balance), with no penalty under the Hire-Purchase (Amendment)
    Act 2026;
  - returning a SUBSCRIPTION car early: early_termination_months now means N
    months of the subscription fee (KINTO ONE's rule), so the fee is N x the
    Subscription fee of the request, null when Subscription isn't available.

No ringgit figure is ever stored; early_termination_amount (N months of the HP
instalment) is no longer computed.
"""

from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient

from apps.comparisons.formulas import exact_hp_monthly
from apps.depreciation.services import build_contract_checklist, build_early_settlement
from apps.policy.models import ContractPenaltyRule, InterestRate
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal
SETTLEMENT = {"method": "reducing_balance", "after_12_months": D("1.00"), "at_half_term": D("1.00"),
              "half_term_month": 1, "penalty": "none"}


@pytest.fixture
def brand():
    return Brand.objects.create(name="ChecklistBrand", tier_code="2")


def checklist_for(brand, subscription_fee):
    return build_contract_checklist(brand=brand, early_settlement=SETTLEMENT, subscription_fee=subscription_fee)


# --- HP early settlement: reducing balance, no penalty ---------------------------------------

BMW_PRINCIPAL = D("265800.00") - D("26580.00")


@pytest.mark.parametrize(
    "tenure, after_12, half_month, at_half",
    [(60, "196280.44", 30, "127476.28"), (48, "184074.51", 24, "125932.69")],
)
def test_early_settlement_golden_values(tenure, after_12, half_month, at_half):
    exact = exact_hp_monthly(D("265800.00"), D("26580.00"), tenure, D("0.028"))

    settlement = build_early_settlement(principal=BMW_PRINCIPAL, exact_hp_monthly=exact, tenure_months=tenure)

    assert settlement == {
        "method": "reducing_balance",
        "after_12_months": D(after_12),
        "at_half_term": D(at_half),
        "half_term_month": half_month,
        "penalty": "none",
    }


def test_a_12_month_loan_has_no_after_12_months_figure():
    exact = exact_hp_monthly(D("265800.00"), D("26580.00"), 12, D("0.028"))

    settlement = build_early_settlement(principal=BMW_PRINCIPAL, exact_hp_monthly=exact, tenure_months=12)

    assert settlement["after_12_months"] is None
    assert settlement["half_term_month"] == 6 and settlement["at_half_term"] > 0


def test_the_checklist_carries_the_early_settlement_it_is_given(brand):
    assert checklist_for(brand, D("1000.00"))["early_settlement"] is SETTLEMENT


# --- Subscription early return: N months of the subscription fee ----------------------------


def test_the_default_applies_when_the_brand_has_no_rule(brand):
    checklist = checklist_for(brand, D("5701.93"))

    assert checklist["rule_source"] == "default"
    assert checklist["excess_mileage_charge_per_km"] == D("0.50")
    assert checklist["subscription_early_return_months"] == D("3.00")
    # 3 months x the BMW 320i's 36-month subscription fee RM 5,701.93 = 17,105.79
    assert checklist["subscription_early_return_fee"] == D("17105.79")
    assert checklist["early_termination_months"] == D("3.00")  # kept for older clients
    assert checklist["early_termination_months_source"] == "default"
    assert "early_termination_amount" not in checklist
    assert "wear and tear" in checklist["wear_tear_tolerance_description"].lower()


def test_no_subscription_for_this_tenure_means_no_fee_but_the_months_still_show(brand):
    checklist = checklist_for(brand, None)

    assert checklist["subscription_early_return_fee"] is None
    assert checklist["subscription_early_return_months"] == D("3.00")


def test_a_brand_rule_beats_the_default(brand):
    ContractPenaltyRule.objects.create(
        brand=brand, excess_mileage_charge_per_km="0.80", early_termination_months="6",
        wear_tear_tolerance_description="Brand terms.",
    )

    checklist = checklist_for(brand, D("5701.93"))

    assert checklist["rule_source"] == "brand"
    assert checklist["excess_mileage_charge_per_km"] == D("0.80")
    assert checklist["subscription_early_return_months"] == D("6.00")
    assert checklist["early_termination_months_source"] == "brand"
    assert checklist["subscription_early_return_fee"] == D("34211.58")  # 6 x 5,701.93
    assert checklist["wear_tear_tolerance_description"] == "Brand terms."


def test_a_brand_rule_with_empty_months_inherits_the_defaults_months(brand):
    ContractPenaltyRule.objects.create(
        brand=brand, excess_mileage_charge_per_km="0.80", early_termination_months=None,
        wear_tear_tolerance_description="Brand terms.",
    )

    checklist = checklist_for(brand, D("1000.00"))

    assert checklist["rule_source"] == "brand"  # the per-km and wear text are the brand's own
    assert checklist["excess_mileage_charge_per_km"] == D("0.80")
    assert checklist["subscription_early_return_months"] == D("3.00")
    assert checklist["early_termination_months_source"] == "default"
    assert checklist["subscription_early_return_fee"] == D("3000.00")


def test_a_legacy_brand_rule_carrying_only_the_deprecated_fee_never_uses_it(brand):
    ContractPenaltyRule.objects.create(
        brand=brand, excess_mileage_charge_per_km="0.50", early_termination_fee="99999.00",
        wear_tear_tolerance_description="Legacy row.",
    )

    checklist = checklist_for(brand, D("1000.00"))

    assert "early_termination_fee" not in checklist
    assert checklist["subscription_early_return_fee"] == D("3000.00")  # default 3 months x 1,000, not 99,999


def test_the_fee_scales_with_the_subscription_fee_so_two_cars_of_one_brand_differ(brand):
    cheap = checklist_for(brand, D("2000.00"))
    dear = checklist_for(brand, D("12000.00"))

    assert (cheap["subscription_early_return_fee"], dear["subscription_early_return_fee"]) == (
        D("6000.00"), D("36000.00"))


def test_months_with_a_fraction_round_to_the_sen(brand):
    ContractPenaltyRule.objects.create(
        brand=brand, excess_mileage_charge_per_km="0.50", early_termination_months="2.5",
        wear_tear_tolerance_description="x",
    )

    assert checklist_for(brand, D("1058.33"))["subscription_early_return_fee"] == D("2645.83")  # 2645.825 half-up


def test_no_checklist_when_neither_a_brand_rule_nor_a_default_exists(brand):
    ContractPenaltyRule.objects.update(is_active=False)

    assert checklist_for(brand, D("1000.00")) is None


def test_a_default_with_no_months_gives_null_months_and_fee_rather_than_a_guess(brand):
    ContractPenaltyRule.objects.filter(brand__isnull=True).update(early_termination_months=None)

    checklist = checklist_for(brand, D("1000.00"))

    assert checklist["subscription_early_return_months"] is None
    assert checklist["subscription_early_return_fee"] is None
    assert checklist["early_termination_months_source"] is None


def test_archiving_a_brand_never_touches_the_default_rule(brand):
    from apps.vehicles import archiving

    default = ContractPenaltyRule.objects.get(brand__isnull=True, is_active=True)
    ContractPenaltyRule.objects.create(
        brand=brand, excess_mileage_charge_per_km="0.50", early_termination_months="6",
        wear_tear_tolerance_description="Brand terms.",
    )

    plan = archiving.plan_brand_archive(brand)
    rules = [row for row in plan.rows if isinstance(row, ContractPenaltyRule)]
    assert [rule.brand_id for rule in rules] == [brand.pk]  # the brand's own rule only

    archiving.archive_brand(brand, actor=None, request=None)

    default.refresh_from_db()
    assert default.is_active is True
    assert ContractPenaltyRule.objects.get(brand=brand).is_active is False

    archiving.restore_brand(brand, actor=None, request=None)
    assert ContractPenaltyRule.objects.get(brand=brand).is_active is True
    default.refresh_from_db()
    assert default.is_active is True


# --- through the TCO endpoint, BMW 320i (the run-1 goldens) --------------------------------------


@pytest.fixture
def bmw_client(regular_user):
    import importlib

    brand = Brand.objects.create(name="BMW", tier_code="2")
    importlib.import_module(
        "apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule"
    ).seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=brand, rate_percent="2.8000")
    vehicle = VehicleModel.objects.create(
        brand=brand, name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN, msrp="265800.00",
        engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client, vehicle


def tco(client, vehicle, tenure):
    response = client.get(
        "/api/depreciation/tco/",
        {"vehicle": vehicle.id, "tenure_months": tenure, "mileage_band": "standard", "downpayment": "26580.00"},
    )
    assert response.status_code == 200
    return response.data["contract_checklist"]


def test_bmw_36_months_subscription_early_return_fee_is_16691_70(bmw_client):
    # 3 x the 36-month fee 5,563.90 (Run 3 fix batch 6; was 3 x 5,701.93 = 17,105.79)
    checklist = tco(*bmw_client, 36)

    assert checklist["subscription_early_return_months"] == "3.00"
    assert checklist["subscription_early_return_fee"] == "16691.70"
    assert "early_termination_amount" not in checklist


@pytest.mark.parametrize("tenure", [48, 60])
def test_bmw_beyond_36_months_has_no_subscription_so_no_fee(bmw_client, tenure):
    checklist = tco(*bmw_client, tenure)

    assert checklist["subscription_early_return_fee"] is None
    assert checklist["subscription_early_return_months"] == "3.00"


@pytest.mark.parametrize(
    "tenure, after_12, half_month, at_half",
    [(60, "196280.44", 30, "127476.28"), (48, "184074.51", 24, "125932.69")],
)
def test_bmw_early_settlement_through_the_endpoint(bmw_client, tenure, after_12, half_month, at_half):
    settlement = tco(*bmw_client, tenure)["early_settlement"]

    assert settlement == {
        "method": "reducing_balance",
        "after_12_months": after_12,
        "at_half_term": at_half,
        "half_term_month": half_month,
        "penalty": "none",
    }
