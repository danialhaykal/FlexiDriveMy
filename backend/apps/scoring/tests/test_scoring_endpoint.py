from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import InterestRate, MileageBand, ResidualValueMatrix, SubscriptionPlan
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def brand():
    return Brand.objects.create(name="ScoringBrand", tier_code="A")


@pytest.fixture
def vehicle(brand):
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SUV,
        msrp="100000.00", engine_capacity_kw="90.00",
    )


@pytest.fixture
def fully_configured(vehicle, brand):
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    ResidualValueMatrix.objects.create(
        brand=brand, tenure_months=36, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.5000"
    )
    SubscriptionPlan.objects.create(
        vehicle=vehicle, fee_monthly="1800.00", insurance_annual="3600.00",
        road_tax_annual="1200.00", maintenance_annual="1800.00",
    )
    return vehicle


def valid_params(vehicle, **overrides):
    params = {
        "vehicle": vehicle.id,
        "tenure_months": 36,
        "mileage_band": MileageBand.STANDARD,
        "downpayment": "10000.00",
        "upfront_cash_preservation": 5,
        "maintenance_protection": 3,
        "ownership_equity": 2,
        "monthly_income": "10000.00",
        "max_dsr_percent": "60.00",
    }
    params.update(overrides)
    return params


def test_requires_authentication(fully_configured):
    client = APIClient()
    response = client.get("/api/scoring/", valid_params(fully_configured))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Incomplete quiz block (UC007 alternate flow) ---------------------------


@pytest.mark.parametrize(
    "missing_field", ["upfront_cash_preservation", "maintenance_protection", "ownership_equity"]
)
def test_missing_any_single_priority_blocks_scoring(user_client, fully_configured, missing_field):
    params = valid_params(fully_configured)
    del params[missing_field]

    response = user_client.get("/api/scoring/", params)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["priorities"] == ["Please rate all three priorities to receive a recommendation."]


def test_all_priorities_missing_blocks_scoring(user_client, fully_configured):
    params = valid_params(fully_configured)
    del params["upfront_cash_preservation"]
    del params["maintenance_protection"]
    del params["ownership_equity"]

    response = user_client.get("/api/scoring/", params)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "priorities" in response.data


# --- Successful scoring ------------------------------------------------


def test_successful_scoring_returns_ranked_pathways_with_recommendation(user_client, fully_configured):
    response = user_client.get("/api/scoring/", valid_params(fully_configured))

    assert response.status_code == status.HTTP_200_OK
    assert set(response.data["ranking"]) == {"hire_purchase", "gfv_leasing", "subscription"}
    assert response.data["recommended_pathway"] == response.data["ranking"][0]
    assert response.data["rationale"]  # a plain-language sentence was generated

    weights = response.data["weights"]
    total_weight = sum(Decimal(v) for v in weights.values())
    assert abs(total_weight - Decimal("1.0")) < Decimal("0.0001")


def test_dsr_override_reflected_through_the_endpoint(user_client, brand, fully_configured):
    # A tiny income forces every pathway's DSR sky-high, well past any
    # reasonable limit - every pathway should be zeroed and none recommended.
    response = user_client.get(
        "/api/scoring/",
        valid_params(fully_configured, monthly_income="1.00", max_dsr_percent="1.00"),
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["recommended_pathway"] is None
    assert all(response.data["pathways"][p]["exceeds_dsr"] for p in response.data["pathways"])
    assert all(
        Decimal(response.data["pathways"][p]["suitability_score"]) == Decimal("0.00")
        for p in response.data["pathways"]
    )


# --- Missing F010/F011 config -> that pathway only (UC007 step 3:
# "scores each available pathway"), never a blanket failure ----------------


def test_missing_interest_rate_scores_only_subscription(user_client, vehicle):
    """HP and GFV both depend on the brand's interest rate (shared, same
    as F005's own comparison engine); Subscription doesn't - a
    SubscriptionPlan is configured but no InterestRate/ResidualValueMatrix,
    so this is genuinely the 2-of-3-unavailable, 1-available case.
    Subscription's own upfront_cash is always 0, so its cash score is a
    perfect 1.0 regardless of price - no special code path needed for
    scoring a single remaining pathway.
    """
    SubscriptionPlan.objects.create(
        vehicle=vehicle, fee_monthly="1800.00", insurance_annual="3600.00",
        road_tax_annual="1200.00", maintenance_annual="1800.00",
    )

    response = user_client.get("/api/scoring/", valid_params(vehicle))

    assert response.status_code == status.HTTP_200_OK
    assert "hire_purchase" not in response.data["pathways"]
    assert "gfv_leasing" not in response.data["pathways"]
    assert "subscription" in response.data["pathways"]
    assert response.data["ranking"] == ["subscription"]
    assert response.data["recommended_pathway"] == "subscription"
    assert "financing rate hasn't been set up" in response.data["unavailable"]["hire_purchase"]
    assert "financing rate hasn't been set up" in response.data["unavailable"]["gfv_leasing"]


def test_every_pathway_unavailable_returns_200_with_no_recommendation(user_client, vehicle):
    # Nothing configured at all (no interest rate, no residual ratio, no
    # subscription plan) - still 200, just nothing to rank.
    response = user_client.get("/api/scoring/", valid_params(vehicle))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["pathways"] == {}
    assert response.data["ranking"] == []
    assert response.data["recommended_pathway"] is None
    assert set(response.data["unavailable"].keys()) == {"hire_purchase", "gfv_leasing", "subscription"}


# --- M4: suitability_score genuinely responds to downpayment size ----------


def test_suitability_score_differs_between_a_small_and_a_large_downpayment(user_client, fully_configured):
    """QA audit M4: previously the upfront-cash-preservation score was a
    min-max normalization across only the three pathways in this one
    comparison, which made it scale-invariant - HP's score was always
    exactly 1.0 regardless of whether the downpayment was RM 1 or close
    to the full price. Two otherwise-identical requests differing only
    in downpayment must now produce a genuinely different suitability_score.

    vehicle msrp=100000.00, GFV residual=0.50 -> balloon=50000.00, so GFV
    stays available (financed_amount = price - downpayment - balloon
    must stay >= 0) only up to downpayment=50000.00 - 49000.00 keeps GFV
    alive while still being far from the 10000.00 (10%) minimum.
    """
    small_response = user_client.get(
        "/api/scoring/", valid_params(fully_configured, downpayment="10000.00")
    )
    large_response = user_client.get(
        "/api/scoring/", valid_params(fully_configured, downpayment="49000.00")
    )

    assert small_response.status_code == status.HTTP_200_OK
    assert large_response.status_code == status.HTTP_200_OK

    small_hp_score = Decimal(small_response.data["pathways"]["hire_purchase"]["suitability_score"])
    large_hp_score = Decimal(large_response.data["pathways"]["hire_purchase"]["suitability_score"])
    assert small_hp_score != large_hp_score
    assert small_hp_score > large_hp_score  # smaller downpayment preserves more cash -> higher score

    small_gfv_score = Decimal(small_response.data["pathways"]["gfv_leasing"]["suitability_score"])
    large_gfv_score = Decimal(large_response.data["pathways"]["gfv_leasing"]["suitability_score"])
    assert small_gfv_score != large_gfv_score
    assert small_gfv_score > large_gfv_score


# --- Request validation ----------------------------------------------------


def test_downpayment_must_be_less_than_price(user_client, fully_configured):
    response = user_client.get(
        "/api/scoring/", valid_params(fully_configured, downpayment="100000.00")
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
