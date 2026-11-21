"""Audit batch 4's design goal, as a test: a NEW car - or a NEW brand - gets a
sensible GFV residual, depreciation curve and contract terms automatically,
with no per-car or per-brand keying.

The only things set up here are what a real admin must enter anyway: the
brand's interest rate, and the vehicle through the SAME serializer the Fleet
form uses, carrying only the new-vehicle contract fields. No residual rows,
no residual adjustment, no contract penalty rule, no cost band.
"""

from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.comparisons.services import build_comparison
from apps.policy.models import (
    ContractPenaltyRule,
    InterestRate,
    MileageBand,
    ResidualAdjustment,
    ResidualValueMatrix,
)
from apps.vehicles.models import BodySegment, Brand, VehicleModel
from apps.vehicles.serializers import VehicleModelSerializer

pytestmark = pytest.mark.django_db

D = Decimal


def create_through_the_serializer(brand, **fields):
    data = {
        "brand": brand.id, "name": "Brand New Model", "trim": "Launch Edition", "body_segment": BodySegment.SUV,
        "msrp": "400000.00", "engine_capacity_kw": "150.00",
    }
    data.update(fields)
    serializer = VehicleModelSerializer(data=data)
    assert serializer.is_valid(), serializer.errors
    vehicle = serializer.save()
    vehicle.refresh_from_db()
    return vehicle


def brand_with_only_a_rate():
    brand = Brand.objects.create(name="Startup Motors", tier_code="3")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    # Nothing else is keyed for this brand - and the fixture proves it:
    assert not ResidualValueMatrix.objects.filter(brand=brand).exists()
    assert not ResidualAdjustment.objects.filter(brand=brand).exists()
    assert not ContractPenaltyRule.objects.filter(brand=brand).exists()
    return brand


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


NEW_CARS = {
    "petrol": {"powertrain": "petrol", "engine_capacity_cc": 1998},
    "bev": {"powertrain": "bev"},
}


@pytest.mark.parametrize("kind", NEW_CARS)
def test_a_new_car_on_a_new_brand_gets_gfv_a_tco_and_contract_terms_with_nothing_keyed(user_client, kind):
    brand = brand_with_only_a_rate()
    vehicle = create_through_the_serializer(brand, **NEW_CARS[kind])
    # powertrain adjustment: petrol 0 pts, bev -8 pts; this brand has no brand adjustment (0 pts).
    # Run 3 fix batch 6: the 36-month standard baseline is 0.5179 (was 0.50).
    expected_ratio = D("0.5179") if kind == "petrol" else D("0.4379")

    # --- GFV: available, with its basis ---
    comparison = build_comparison(
        vehicle=vehicle, tenure_months=36, mileage_band=MileageBand.STANDARD, downpayment=D("40000.00")
    )
    gfv = comparison["gfv_leasing"]
    assert gfv is not None and "gfv_leasing" not in comparison["unavailable"]
    assert gfv["residual_value_ratio"] == expected_ratio
    assert gfv["residual_basis"] == (
        f"Estimate: 51.79% baseline for 36 months / standard mileage, 0 points Startup Motors, "
        f"{'0 points petrol' if kind == 'petrol' else '-8 points electric'}"
    )
    # the project spec formulas, by hand: balloon = P x G; monthly = (P - D - balloon)/t + (P - D) x r / 12
    balloon = D("400000.00") * expected_ratio
    assert gfv["balloon_payment"] == balloon
    exact_monthly = (D("400000") - D("40000") - balloon) / D(36) + (D("400000") - D("40000")) * D("0.03") / D(12)
    assert gfv["monthly_instalment"] == exact_monthly.quantize(D("0.01"))

    # --- the API serialises the basis ---
    response = user_client.get(
        "/api/comparisons/",
        {"vehicle": vehicle.id, "tenure_months": 36, "mileage_band": "standard", "downpayment": "40000.00"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.data["gfv_leasing"]["residual_basis"] == gfv["residual_basis"]

    # --- TCO: 200, on the estimated curve anchored to that same residual ---
    tco = user_client.get(
        "/api/depreciation/tco/",
        {"vehicle": vehicle.id, "tenure_months": 36, "mileage_band": "standard", "downpayment": "40000.00"},
    )
    assert tco.status_code == status.HTTP_200_OK
    assert tco.data["model_degraded"] is True
    forecast = {row["month"]: row["predicted_resale_value"] for row in tco.data["monthly_forecast"]}
    assert forecast[0] == "400000.00"
    # month 36 resale = GFV residual x MSRP, so TCO and GFV agree
    assert D(forecast[36]) == D("400000.00") * expected_ratio

    # --- contract checklist: the default rule, no brand row keyed ---
    checklist = tco.data["contract_checklist"]
    assert checklist["rule_source"] == "default"
    assert checklist["excess_mileage_charge_per_km"] == "0.50"
    assert checklist["early_termination_months"] == "3.00"
    # Run 1: 3 months of THIS request's Subscription fee (36 months), and the
    # HP early settlement from the reducing-balance amount to settle.
    assert D(checklist["subscription_early_return_fee"]) == (
        D("3") * comparison["subscription"]["monthly_instalment"]
    ).quantize(D("0.01"))
    assert checklist["early_settlement"]["method"] == "reducing_balance"
    assert "early_termination_amount" not in checklist


@pytest.mark.parametrize("kind", NEW_CARS)
def test_a_new_car_gets_a_subscription_for_every_allowed_tenure_with_no_plan_keyed(user_client, kind):
    """Audit batch 5 (C1/C3): Subscription used to be "not available" for every
    car added after the seed (no plan keyed). Now it is estimated at 12/24/36
    months, and only the tenures it doesn't run for are unavailable."""
    from apps.policy.models import SubscriptionPlan

    brand = brand_with_only_a_rate()
    vehicle = create_through_the_serializer(brand, **NEW_CARS[kind])
    assert not SubscriptionPlan.objects.filter(vehicle=vehicle).exists()

    fees = []
    for tenure in (12, 24, 36):
        comparison = build_comparison(
            vehicle=vehicle, tenure_months=tenure, mileage_band=MileageBand.STANDARD, downpayment=D("40000.00")
        )
        sub = comparison["subscription"]
        assert sub is not None and "subscription" not in comparison["unavailable"]
        assert sub["fee_source"] == "estimate"
        assert sub["fee_basis"].startswith("Estimate: depreciation RM")
        # deposit = 2 months of fee, IS the upfront cash; outlay = fees only
        assert sub["refundable_deposit"] == sub["upfront_cash"] == (
            D("2") * sub["monthly_instalment"]).quantize(D("0.01"), rounding="ROUND_HALF_UP")
        assert sub["total_contract_outlay"] == sub["monthly_instalment"] * tenure
        fees.append(sub["monthly_instalment"])
    assert fees == sorted(fees, reverse=True)  # longer is cheaper per month

    for tenure in (18, 48, 60):
        comparison = build_comparison(
            vehicle=vehicle, tenure_months=tenure, mileage_band=MileageBand.STANDARD, downpayment=D("40000.00")
        )
        assert comparison["subscription"] is None
        assert comparison["unavailable"]["subscription"] == "Subscription plans run for 12, 24 or 36 months."

    response = user_client.get(
        "/api/comparisons/",
        {"vehicle": vehicle.id, "tenure_months": 48, "mileage_band": "standard", "downpayment": "40000.00"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.data["subscription"] is None
    assert response.data["unavailable"]["subscription"] == "Subscription plans run for 12, 24 or 36 months."


@pytest.mark.parametrize("trim, powertrain, cc, ratio", [
    ("B5 Core", "mild_hybrid", 1969, "0.3979"),   # XC60: 0.4379 - 0.04 (Run 3 fix batch 6; was 0.38)
    ("Ultra T8", "phev", 1969, "0.3679"),          # XC90: 0.4379 - 0.04 - 0.03 (was 0.35)
])
def test_volvo_now_shows_gfv_instead_of_the_wrong_reason_message(trim, powertrain, cc, ratio):
    """F1: a brand with no residual rows used to say GFV "isn't offered for
    this tenure and mileage combination on this model" - the wrong reason."""
    from importlib import import_module

    from django.apps import apps as django_apps

    volvo = Brand.objects.create(name="Volvo", tier_code="2")
    import_module(
        "apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule"
    ).seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=volvo, rate_percent="2.5000")
    vehicle = create_through_the_serializer(
        volvo, name="XC", trim=trim, msrp="434888.00", powertrain=powertrain, engine_capacity_cc=cc
    )

    comparison = build_comparison(
        vehicle=vehicle, tenure_months=48, mileage_band=MileageBand.STANDARD, downpayment=D("43488.80")
    )

    assert comparison["gfv_leasing"] is not None
    assert comparison["gfv_leasing"]["residual_value_ratio"] == D(ratio)
    assert "gfv_leasing" not in comparison["unavailable"]
    assert "isn't offered" not in str(comparison["unavailable"])
