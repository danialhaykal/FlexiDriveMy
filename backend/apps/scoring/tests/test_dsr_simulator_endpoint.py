from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import InterestRate, MileageBand, ResidualValueMatrix, SubscriptionPlan
from apps.scoring import formulas
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db

DSR_SIMULATOR_URL = "/api/scoring/dsr-simulator/"
SCORING_URL = "/api/scoring/"


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def brand():
    return Brand.objects.create(name="DsrSimBrand", tier_code="A")


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


def simulator_params(vehicle, **overrides):
    params = {
        "vehicle": vehicle.id,
        "tenure_months": 36,
        "mileage_band": MileageBand.STANDARD,
        "downpayment": "10000.00",
        "monthly_income": "10000.00",
        "max_dsr_percent": "30.00",
    }
    params.update(overrides)
    return params


def scoring_params(vehicle, **overrides):
    params = {
        "vehicle": vehicle.id,
        "tenure_months": 36,
        "mileage_band": MileageBand.STANDARD,
        "downpayment": "10000.00",
        "upfront_cash_preservation": 5,
        "maintenance_protection": 3,
        "ownership_equity": 2,
        "monthly_income": "10000.00",
        "max_dsr_percent": "30.00",
    }
    params.update(overrides)
    return params


def test_requires_authentication(fully_configured):
    client = APIClient()
    response = client.get(DSR_SIMULATOR_URL, simulator_params(fully_configured))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Reference case, hand-checked against the same oracle the formula uses -


def test_reference_case_matches_calculate_total_dsr_percent_directly(user_client, fully_configured):
    """HP monthly = (90000)/36 + 90000*0.03/12 = 2500.00 + 225.00 = 2725.00.
    GFV balloon = 100000*0.5 = 50000; GFV monthly = (40000)/36 + 225.00 = 1336.11.
    Subscription: QA audit H8 - monthly_instalment is the real, gross fee
    billed (1800.00 in full), not the netted comparison figure
    (1800 - (3600+1200+1800)/12 = 1250.00, now a separate informational
    field on F005's own comparison response, not surfaced here).
    With no existing commitments, dsr_percent is each of those over the
    10000.00 declared income - computed independently here via the same
    formulas.calculate_total_dsr_percent the endpoint itself calls, to
    verify routing/orchestration rather than re-deriving the arithmetic.
    """
    response = user_client.get(DSR_SIMULATOR_URL, simulator_params(fully_configured))
    assert response.status_code == status.HTTP_200_OK

    pathways = response.data["pathways"]
    assert Decimal(pathways["hire_purchase"]["monthly_instalment"]) == Decimal("2725.00")
    assert Decimal(pathways["gfv_leasing"]["monthly_instalment"]) == Decimal("1336.11")
    assert Decimal(pathways["subscription"]["monthly_instalment"]) == Decimal("1800.00")

    for pathway in formulas.PATHWAYS:
        expected = formulas.calculate_total_dsr_percent(
            monthly_instalment=Decimal(pathways[pathway]["monthly_instalment"]),
            existing_monthly_commitments=Decimal("0"),
            monthly_income=Decimal("10000.00"),
        )
        assert Decimal(pathways[pathway]["dsr_percent"]) == expected
        assert Decimal(pathways[pathway]["existing_monthly_commitments"]) == Decimal("0.00")

    # 27.25%, 13.36%, and 18.00% (1800/10000) are all under the 30% limit.
    assert pathways["hire_purchase"]["exceeds_dsr"] is False
    assert pathways["gfv_leasing"]["exceeds_dsr"] is False
    assert pathways["subscription"]["exceeds_dsr"] is False


# --- Cross-check against F007's own endpoint (the "genuine superset" proof) -


def test_zero_existing_commitments_matches_f007_own_dsr_percent_exactly(user_client, fully_configured):
    """With no other debt declared, "total DSR" and "this pathway's own
    DSR" are the same number - so this endpoint must reproduce exactly
    what GET /api/scoring/ already reports for the identical inputs. This
    is what proves the new calculation is a genuine superset of the old
    one, not a divergent reinvention.
    """
    scoring_response = user_client.get(SCORING_URL, scoring_params(fully_configured))
    simulator_response = user_client.get(
        DSR_SIMULATOR_URL, simulator_params(fully_configured, existing_monthly_commitments="0")
    )
    assert scoring_response.status_code == status.HTTP_200_OK
    assert simulator_response.status_code == status.HTTP_200_OK

    for pathway in formulas.PATHWAYS:
        scoring_pathway = scoring_response.data["pathways"][pathway]
        simulator_pathway = simulator_response.data["pathways"][pathway]
        assert Decimal(simulator_pathway["dsr_percent"]) == Decimal(scoring_pathway["dsr_percent"])
        assert simulator_pathway["exceeds_dsr"] == scoring_pathway["exceeds_dsr"]


def test_existing_monthly_commitments_defaults_to_zero_when_omitted(user_client, fully_configured):
    params = simulator_params(fully_configured)
    assert "existing_monthly_commitments" not in params  # relying on the default

    response = user_client.get(DSR_SIMULATOR_URL, params)

    assert response.status_code == status.HTTP_200_OK
    for pathway in formulas.PATHWAYS:
        assert Decimal(response.data["pathways"][pathway]["existing_monthly_commitments"]) == Decimal("0.00")


# --- Existing commitments increase DSR and can flip exceeds_dsr ------------


def test_existing_commitments_increase_dsr_and_can_flip_exceeds_dsr_to_true(user_client, fully_configured):
    """At existing=0, HP's DSR is 27.25% - fine under the 30% limit. Adding
    1000.00 of existing debt raises it to (2725+1000)/10000 = 37.25%,
    flipping exceeds_dsr to True for a pathway that was fine on its own.
    """
    baseline = user_client.get(DSR_SIMULATOR_URL, simulator_params(fully_configured))
    assert baseline.data["pathways"]["hire_purchase"]["exceeds_dsr"] is False
    assert Decimal(baseline.data["pathways"]["hire_purchase"]["dsr_percent"]) == Decimal("27.25")

    with_debt = user_client.get(
        DSR_SIMULATOR_URL,
        simulator_params(fully_configured, existing_monthly_commitments="1000.00"),
    )
    assert with_debt.status_code == status.HTTP_200_OK
    hp = with_debt.data["pathways"]["hire_purchase"]
    assert Decimal(hp["existing_monthly_commitments"]) == Decimal("1000.00")
    assert Decimal(hp["dsr_percent"]) == Decimal("37.25")
    assert hp["exceeds_dsr"] is True


# --- CCRIS-reportable labels: static, never computed -----------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        # downpayment stays >= the 10% minimum (C6) - varying income/
        # commitments is enough to prove these labels don't move with
        # the inputs.
        {"monthly_income": "500.00", "downpayment": "10000.00", "existing_monthly_commitments": "9000.00"},
    ],
)
def test_is_ccris_reportable_is_always_true_true_false(user_client, fully_configured, overrides):
    response = user_client.get(DSR_SIMULATOR_URL, simulator_params(fully_configured, **overrides))
    assert response.status_code == status.HTTP_200_OK
    pathways = response.data["pathways"]
    assert pathways["hire_purchase"]["is_ccris_reportable"] is True
    assert pathways["gfv_leasing"]["is_ccris_reportable"] is True
    assert pathways["subscription"]["is_ccris_reportable"] is False


# --- Missing F010/F011 config -> that pathway only, never a blanket
# failure (same "scores/reports only what's available" contract F007's
# own suitability scoring now has) -------------------------------------


def test_missing_interest_rate_reports_only_subscription(user_client, vehicle):
    SubscriptionPlan.objects.create(
        vehicle=vehicle, fee_monthly="1800.00", insurance_annual="3600.00",
        road_tax_annual="1200.00", maintenance_annual="1800.00",
    )

    response = user_client.get(DSR_SIMULATOR_URL, simulator_params(vehicle))

    assert response.status_code == status.HTTP_200_OK
    assert "hire_purchase" not in response.data["pathways"]
    assert "gfv_leasing" not in response.data["pathways"]
    assert "subscription" in response.data["pathways"]
    assert "financing rate hasn't been set up" in response.data["unavailable"]["hire_purchase"]
    assert "financing rate hasn't been set up" in response.data["unavailable"]["gfv_leasing"]


# --- Request validation ------------------------------------------------


def test_downpayment_must_be_less_than_price(user_client, fully_configured):
    response = user_client.get(
        DSR_SIMULATOR_URL, simulator_params(fully_configured, downpayment="100000.00")
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
