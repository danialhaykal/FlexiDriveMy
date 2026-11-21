"""Batch 6C / UC006 steps 6-9: the risk radar, cumulative cash flow
chart, contract return checklist, and risk alerts build_tco_report now
adds on top of its existing negative-equity forecast/60-month TCO
summary."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.comparisons import formulas as comparison_formulas
from apps.depreciation import formulas
from apps.policy.mileage import mileage_band_label
from apps.policy.models import (
    ContractPenaltyRule,
    InterestRate,
    MileageBand,
    ResidualValueMatrix,
    SubscriptionPlan,
)
from apps.profiles.models import AnnualMileageBand, FinancialProfile, OwnershipPreference
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def brand():
    return Brand.objects.create(name="RadarBrand", tier_code="2")


@pytest.fixture
def vehicle(brand):
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SUV,
        msrp="100000.00", engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1498,
    )


@pytest.fixture
def interest_rate(brand):
    return InterestRate.objects.create(brand=brand, rate_percent="3.0000")


def request_tco(client, vehicle, tenure_months=36, mileage_band=MileageBand.STANDARD, downpayment="10000.00"):
    return client.get(
        "/api/depreciation/tco/",
        {
            "vehicle": vehicle.id,
            "tenure_months": tenure_months,
            "mileage_band": mileage_band,
            "downpayment": downpayment,
        },
    )


# --- 2a: risk radar ----------------------------------------------------


def test_radar_includes_hp_and_marks_gfv_subscription_unavailable_without_their_config(
    user_client, vehicle, interest_rate
):
    # Audit batch 5: Subscription is estimated for any car, but only runs for
    # 12-36 months - at 48 months it is the unavailable pathway.
    response = request_tco(user_client, vehicle, tenure_months=48)

    assert response.status_code == 200
    radar = response.data["risk_radar"]
    # Audit batch 4: GFV no longer needs a residual row keyed for the brand -
    # the estimator supplies one - so only Subscription is missing.
    assert set(radar.keys()) == {"hire_purchase", "gfv_leasing"}
    assert radar["hire_purchase"]["maintenance_protection"] == "0.0000"
    assert radar["hire_purchase"]["ownership_equity"] == "1.0000"
    # score_upfront_cash_preservation: 1 - (downpayment / price) = 1 - (10000/100000) = 0.9000
    assert radar["hire_purchase"]["upfront_cash_preservation"] == "0.9000"

    assert set(response.data["radar_unavailable"].keys()) == {"subscription"}


def test_radar_includes_every_pathway_once_all_three_are_configured(user_client, brand, vehicle, interest_rate):
    ResidualValueMatrix.objects.create(
        brand=brand, tenure_months=36, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.5000"
    )
    SubscriptionPlan.objects.create(
        vehicle=vehicle, fee_monthly="2000.00", insurance_annual="1800.00",
        road_tax_annual="90.00", maintenance_annual="600.00",
    )

    response = request_tco(user_client, vehicle)

    assert response.status_code == 200
    radar = response.data["risk_radar"]
    assert set(radar.keys()) == {"hire_purchase", "gfv_leasing", "subscription"}
    assert radar["subscription"]["maintenance_protection"] == "1.0000"
    assert radar["subscription"]["ownership_equity"] == "0.0000"
    # Audit batch 5: Subscription's upfront cash is the refundable deposit,
    # 2 months x the 2000.00 quote = 4000.00, so 1 - 4000/100000 = 0.9600
    # (it used to be a perfect 1.0000 with RM 0 upfront).
    assert radar["subscription"]["upfront_cash_preservation"] == "0.9600"
    assert radar["gfv_leasing"]["ownership_equity"] == "0.5000"
    assert response.data["radar_unavailable"] == {}


# --- 2b: cumulative cash flow invariant ---------------------------------


def test_cumulative_cash_flow_final_entry_matches_tco_gross_for_tenure_at_or_under_60(
    user_client, vehicle, interest_rate
):
    response = request_tco(user_client, vehicle, tenure_months=36, downpayment="10000.00")

    assert response.status_code == 200
    cash_flow = response.data["cumulative_cash_flow"]
    assert len(cash_flow) == formulas.HORIZON_MONTHS + 1
    assert cash_flow[-1]["month"] == formulas.HORIZON_MONTHS
    assert Decimal(cash_flow[-1]["cumulative_cash_outflow"]) == Decimal(response.data["tco_gross"])


def test_cumulative_cash_flow_final_entry_matches_tco_gross_for_tenure_over_60(
    user_client, vehicle, interest_rate
):
    response = request_tco(user_client, vehicle, tenure_months=108, downpayment="10000.00")

    assert response.status_code == 200
    cash_flow = response.data["cumulative_cash_flow"]
    assert Decimal(cash_flow[-1]["cumulative_cash_outflow"]) == Decimal(response.data["tco_gross"])


def test_cumulative_cash_flow_matches_the_formula_directly(user_client, vehicle, interest_rate):
    response = request_tco(user_client, vehicle, tenure_months=36, downpayment="10000.00")
    # The unrounded instalment from the fixtures (msrp 100000, rate 3%).
    exact_hp_monthly = comparison_formulas.exact_hp_monthly(
        Decimal("100000.00"), Decimal("10000.00"), 36, Decimal("0.03")
    )

    expected = formulas.build_cumulative_cash_flow(
        downpayment=Decimal("10000.00"),
        exact_hp_monthly=exact_hp_monthly,
        tenure_months=36,
        road_tax_annual=Decimal(response.data["road_tax_annual"]),
        insurance_annual=Decimal(response.data["insurance_annual"]),
        maintenance_annual=Decimal(response.data["maintenance_annual"]),
    )

    actual = response.data["cumulative_cash_flow"]
    assert len(actual) == len(expected)
    assert Decimal(actual[12]["cumulative_cash_outflow"]) == expected[12]["cumulative_cash_outflow"]
    assert Decimal(actual[-1]["cumulative_cash_outflow"]) == expected[-1]["cumulative_cash_outflow"]


# --- 2c: contract return checklist --------------------------------------


def test_contract_checklist_present_when_a_rule_is_configured_for_the_brand(
    user_client, brand, vehicle, interest_rate
):
    ContractPenaltyRule.objects.create(
        brand=brand,
        excess_mileage_charge_per_km="0.50",
        early_termination_months="6",
        wear_tear_tolerance_description="Normal wear and tear accepted.",
    )

    response = request_tco(user_client, vehicle)

    checklist = response.data["contract_checklist"]
    assert checklist is not None
    assert checklist["excess_mileage_charge_per_km"] == "0.50"
    assert checklist["early_termination_months"] == "6.00"
    # Run 1: the months are months of the SUBSCRIPTION fee for returning a
    # subscription car early. This car's 36-month estimated fee, by hand:
    # depreciation 100000 x 0.4821 / 36 = 1,339.1667; funding 100000 x 1.5179 / 2
    # x 4.5% / 12 = 284.6063; running costs (120 + 1,800 + 1,200) / 12 = 260.00
    # (a 1,498 cc SUV is on the non-saloon table since run 1 fix batch 3: a flat
    # RM 120, was RM 90 saloon); x 1.12 = 2,109.8257 -> 2,109.83.
    # 6 x 2,109.83 = 12,658.98 - never a stored amount. (Run 3 fix batch 6: the
    # 36-month standard residual is 0.5179, was 0.50 -> 2,161.76 / 12,970.56.)
    assert checklist["subscription_early_return_months"] == "6.00"
    assert checklist["subscription_early_return_fee"] == "12658.98"
    assert "early_termination_amount" not in checklist
    # HP early settlement is the reducing-balance amount to settle, no penalty.
    assert checklist["early_settlement"]["penalty"] == "none"
    assert checklist["early_settlement"]["half_term_month"] == 18
    assert checklist["wear_tear_tolerance_description"] == "Normal wear and tear accepted."
    assert checklist["rule_source"] == "brand"


def test_contract_checklist_is_null_only_when_there_is_no_brand_rule_and_no_default(
    user_client, vehicle, interest_rate
):
    # The seeded default rule (migration 0018) makes this checklist present
    # for every brand; it is only absent if the default is archived too.
    ContractPenaltyRule.objects.filter(brand__isnull=True).update(is_active=False)

    response = request_tco(user_client, vehicle)
    assert response.data["contract_checklist"] is None


def test_contract_checklist_ignores_an_archived_brand_rule_and_uses_the_default(
    user_client, brand, vehicle, interest_rate
):
    ContractPenaltyRule.objects.create(
        brand=brand,
        excess_mileage_charge_per_km="9.99",
        early_termination_months="12",
        wear_tear_tolerance_description="Archived rule.",
        is_active=False,
    )

    response = request_tco(user_client, vehicle)

    checklist = response.data["contract_checklist"]
    assert checklist["rule_source"] == "default"
    assert checklist["excess_mileage_charge_per_km"] == "0.50"


# --- 2d: risk alerts -----------------------------------------------------


def test_negative_equity_alert_present_only_when_a_crossover_exists(user_client, vehicle, interest_rate):
    # Large downpayment -> no crossover within the 60-month horizon.
    response = request_tco(user_client, vehicle, tenure_months=36, downpayment="60000.00")

    assert response.data["negative_equity_crossover_month"] is None
    codes = [alert["code"] for alert in response.data["risk_alerts"]]
    assert "negative_equity_within_horizon" not in codes


def test_negative_equity_alert_present_when_a_crossover_exists(user_client, brand, interest_rate, tmp_path):
    import joblib

    from apps.ml.models import ModelType, PredictionTarget, ProductionModel
    from apps.depreciation.tests.test_tco_endpoint import DecliningResaleEstimator

    model_path = tmp_path / "model.joblib"
    joblib.dump(DecliningResaleEstimator(initial_value=1.0, monthly_decline=0.015), model_path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = str(model_path)
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.save()

    vehicle = VehicleModel.objects.create(
        brand=brand, name="Crossover", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1498,
    )

    response = request_tco(user_client, vehicle, tenure_months=108, downpayment="10000.00")

    # Run 1: reducing-balance amount to settle -> first crossover at month 12
    # (see test_tco_endpoint's crossover test for the derivation).
    assert response.data["negative_equity_crossover_month"] == 12
    alerts = response.data["risk_alerts"]
    matching = [a for a in alerts if a["code"] == "negative_equity_within_horizon"]
    assert len(matching) == 1
    assert matching[0]["severity"] == "warning"
    assert "month 12" in matching[0]["message"]


def test_declared_mileage_mismatch_alert_absent_without_a_saved_profile(user_client, vehicle, interest_rate):
    response = request_tco(user_client, vehicle, mileage_band=MileageBand.STANDARD)

    codes = [alert["code"] for alert in response.data["risk_alerts"]]
    assert "declared_mileage_mismatch" not in codes


def test_declared_mileage_mismatch_alert_absent_when_bands_match(user_client, vehicle, interest_rate, regular_user):
    FinancialProfile.objects.create(
        user=regular_user,
        monthly_budget="2500.00",
        preferred_tenure_months=36,
        annual_mileage_band=AnnualMileageBand.KM_10000,  # maps to "standard"
        ownership_preference=OwnershipPreference.RETAIN,
    )

    response = request_tco(user_client, vehicle, mileage_band=MileageBand.STANDARD)

    codes = [alert["code"] for alert in response.data["risk_alerts"]]
    assert "declared_mileage_mismatch" not in codes


def test_declared_mileage_mismatch_alert_present_and_names_both_bands(
    user_client, vehicle, interest_rate, regular_user
):
    FinancialProfile.objects.create(
        user=regular_user,
        monthly_budget="2500.00",
        preferred_tenure_months=36,
        annual_mileage_band=AnnualMileageBand.KM_30000,  # maps to "very_high"
        ownership_preference=OwnershipPreference.RETAIN,
    )

    response = request_tco(user_client, vehicle, mileage_band=MileageBand.STANDARD)

    alerts = response.data["risk_alerts"]
    matching = [a for a in alerts if a["code"] == "declared_mileage_mismatch"]
    assert len(matching) == 1
    assert matching[0]["severity"] == "info"
    # Run 3 fix batch 6: both bands are named with the screen's own labels (the one definition).
    assert mileage_band_label(MileageBand.STANDARD) in matching[0]["message"]
    assert mileage_band_label(MileageBand.VERY_HIGH) in matching[0]["message"]


def test_declared_mileage_mismatch_alert_is_scoped_to_the_requesting_user(
    user_client, vehicle, interest_rate, create_user
):
    other_user = create_user(email="someone-else@example.com")
    FinancialProfile.objects.create(
        user=other_user,
        monthly_budget="2500.00",
        preferred_tenure_months=36,
        annual_mileage_band=AnnualMileageBand.KM_30000,
        ownership_preference=OwnershipPreference.RETAIN,
    )

    response = request_tco(user_client, vehicle, mileage_band=MileageBand.STANDARD)

    codes = [alert["code"] for alert in response.data["risk_alerts"]]
    assert "declared_mileage_mismatch" not in codes
