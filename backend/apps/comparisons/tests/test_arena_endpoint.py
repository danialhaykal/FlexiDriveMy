"""Mirrors test_comparison_endpoint.py's fixture style. Expected
per-vehicle HP/GFV/subscription figures are computed here via the same
already-tested apps.comparisons.formulas functions the app itself calls
- this is not re-testing the formulas (test_formulas.py already does
that), it's verifying build_arena/compute_arena_winners correctly route
each vehicle's own config to those formulas and correctly pick the min,
i.e. testing the orchestration, not the math."""

from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.comparisons import formulas
from apps.policy.models import InterestRate, MileageBand, ResidualValueMatrix, SubscriptionPlan
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db

TENURE_MONTHS = 36
DOWNPAYMENT = Decimal("10000.00")

# Same shared SubscriptionPlan ins/tax/maint for all three, so only
# fee_monthly varies - makes the subscription winner obvious to verify.
SUB_INSURANCE = Decimal("1200.00")
SUB_ROAD_TAX = Decimal("600.00")
SUB_MAINTENANCE = Decimal("600.00")


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


def _make_vehicle(name, msrp, rate_percent, residual_ratio, fee_monthly, engine_capacity_kw="90.00"):
    brand = Brand.objects.create(name=f"ArenaBrand{name}", tier_code="A")
    vehicle = VehicleModel.objects.create(
        brand=brand,
        name=f"Model{name}",
        trim="X",
        body_segment=BodySegment.SUV,
        msrp=msrp,
        engine_capacity_kw=engine_capacity_kw,
        powertrain="petrol",
        engine_capacity_cc=1498,
    )
    InterestRate.objects.create(brand=brand, rate_percent=rate_percent)
    ResidualValueMatrix.objects.create(
        brand=brand,
        tenure_months=TENURE_MONTHS,
        mileage_band=MileageBand.STANDARD,
        residual_value_ratio=residual_ratio,
    )
    SubscriptionPlan.objects.create(
        vehicle=vehicle,
        fee_monthly=fee_monthly,
        insurance_annual=SUB_INSURANCE,
        road_tax_annual=SUB_ROAD_TAX,
        maintenance_annual=SUB_MAINTENANCE,
    )
    # Real callers always get `vehicle` via a fresh DB fetch (DRF's
    # PrimaryKeyRelatedField), which normalizes msrp to Decimal. A plain
    # .create() leaves it as the raw string passed in until refetched -
    # refresh here so expected_comparison()'s arithmetic below matches
    # how the code is actually called.
    vehicle.refresh_from_db()
    return vehicle


@pytest.fixture
def vehicle_a():
    # Highest residual ratio (0.60) -> smallest amortized principal ->
    # designed to win GFV despite a middling price/rate.
    return _make_vehicle("A", msrp="80000.00", rate_percent="4.0000", residual_ratio="0.6000", fee_monthly="900.00")


@pytest.fixture
def vehicle_b():
    # Lowest price + lowest rate -> designed to win HP.
    return _make_vehicle("B", msrp="70000.00", rate_percent="2.5000", residual_ratio="0.3000", fee_monthly="1100.00")


@pytest.fixture
def vehicle_c():
    # Lowest subscription fee -> designed to win Subscription.
    return _make_vehicle("C", msrp="95000.00", rate_percent="3.0000", residual_ratio="0.4000", fee_monthly="650.00")


def expected_comparison(vehicle, rate_percent, residual_ratio, fee_monthly):
    """The same formulas.py functions build_comparison() itself calls -
    an oracle for "what should this vehicle's pathway figures be",
    independent of build_arena's own orchestration (which is the thing
    actually under test here)."""
    price = vehicle.msrp
    annual_rate = Decimal(rate_percent) / Decimal(100)
    hp_monthly = formulas.calculate_hp_monthly(price, DOWNPAYMENT, TENURE_MONTHS, annual_rate)
    gfv_balloon = formulas.calculate_gfv_balloon(price, Decimal(residual_ratio))
    gfv_monthly = formulas.calculate_gfv_monthly(price, DOWNPAYMENT, TENURE_MONTHS, annual_rate, gfv_balloon)
    # QA audit H8: monthly_instalment is the real, gross fee the
    # subscriber is billed - not calculate_subscription_net_cost's
    # NetCost (an economic comparison figure only, see that function's
    # own docstring).
    subscription_monthly = Decimal(fee_monthly)
    return hp_monthly, gfv_monthly, subscription_monthly


def request_arena(client, vehicles, tenure_months=TENURE_MONTHS, mileage_band=MileageBand.STANDARD, downpayment=None):
    if downpayment is None:
        downpayment = DOWNPAYMENT
    return client.get(
        "/api/comparisons/arena/",
        {
            "vehicles": [vehicle.id for vehicle in vehicles],
            "tenure_months": tenure_months,
            "mileage_band": mileage_band,
            "downpayment": str(downpayment),
        },
    )


# --- Access control ----------------------------------------------------


def test_requires_authentication(vehicle_a, vehicle_b):
    client = APIClient()
    response = request_arena(client, [vehicle_a, vehicle_b])
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_a_vehicle_whose_brand_is_archived_is_rejected(user_client, vehicle_a, vehicle_b):
    """QA audit H13: same rule as the single-vehicle comparison endpoint -
    an archived brand's vehicle can't be selected into the arena either.
    """
    vehicle_a.brand.is_active = False
    vehicle_a.brand.save(update_fields=["is_active"])

    response = request_arena(user_client, [vehicle_a, vehicle_b])

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- 3 fully-configured vehicles: all "ok", winners hand-verifiable -----


def test_three_vehicles_all_ok_with_distinct_winners_per_category(
    user_client, vehicle_a, vehicle_b, vehicle_c
):
    response = request_arena(user_client, [vehicle_a, vehicle_b, vehicle_c])

    assert response.status_code == status.HTTP_200_OK
    results = {entry["vehicle_id"]: entry for entry in response.data["results"]}
    assert len(results) == 3
    assert all(entry["ok"] for entry in results.values())

    hp_a, gfv_a, sub_a = expected_comparison(vehicle_a, "4.0000", "0.6000", "900.00")
    hp_b, gfv_b, sub_b = expected_comparison(vehicle_b, "2.5000", "0.3000", "1100.00")
    hp_c, gfv_c, sub_c = expected_comparison(vehicle_c, "3.0000", "0.4000", "650.00")

    assert Decimal(results[vehicle_a.id]["comparison"]["hire_purchase"]["monthly_instalment"]) == hp_a
    assert Decimal(results[vehicle_a.id]["comparison"]["gfv_leasing"]["monthly_instalment"]) == gfv_a
    assert Decimal(results[vehicle_a.id]["comparison"]["subscription"]["monthly_instalment"]) == sub_a
    assert Decimal(results[vehicle_b.id]["comparison"]["hire_purchase"]["monthly_instalment"]) == hp_b
    assert Decimal(results[vehicle_b.id]["comparison"]["gfv_leasing"]["monthly_instalment"]) == gfv_b
    assert Decimal(results[vehicle_b.id]["comparison"]["subscription"]["monthly_instalment"]) == sub_b
    assert Decimal(results[vehicle_c.id]["comparison"]["hire_purchase"]["monthly_instalment"]) == hp_c
    assert Decimal(results[vehicle_c.id]["comparison"]["gfv_leasing"]["monthly_instalment"]) == gfv_c
    assert Decimal(results[vehicle_c.id]["comparison"]["subscription"]["monthly_instalment"]) == sub_c

    # By construction: B has the lowest HP, A the lowest GFV, C the
    # cheapest subscription - three genuinely distinct winners.
    assert min([(hp_a, vehicle_a.id), (hp_b, vehicle_b.id), (hp_c, vehicle_c.id)])[1] == vehicle_b.id
    assert min([(gfv_a, vehicle_a.id), (gfv_b, vehicle_b.id), (gfv_c, vehicle_c.id)])[1] == vehicle_a.id
    assert min([(sub_a, vehicle_a.id), (sub_b, vehicle_b.id), (sub_c, vehicle_c.id)])[1] == vehicle_c.id

    winners = response.data["winners"]
    # QA audit L10: {"winner_id", "tied_with"} - none of these three are
    # ties by construction, so tied_with is a single-element list each.
    assert winners["cheapest_hp"] == {"winner_id": vehicle_b.id, "tied_with": [vehicle_b.id]}
    assert winners["cheapest_gfv"] == {"winner_id": vehicle_a.id, "tied_with": [vehicle_a.id]}
    assert winners["cheapest_subscription"] == {"winner_id": vehicle_c.id, "tied_with": [vehicle_c.id]}
    # No ProductionModel deployed in this test DB -> every vehicle's TCO
    # is degraded (straight-line fallback), so there's no non-degraded
    # figure to race - lowest_tco correctly stays None rather than
    # picking one arbitrarily (see test_arena_formulas.py for the
    # hand-built-data version of this same rule).
    assert winners["lowest_tco"] is None
    assert all(entry["model_degraded"] is True for entry in results.values())


# --- Partial failure: one vehicle's OWN pathway is missing --------------


def test_one_vehicle_with_an_unavailable_subscription_is_200_with_that_vehicles_own_error(
    user_client, vehicle_a, vehicle_b, vehicle_c
):
    """Per the Sprint-13 QA fix: an unavailable Subscription is no longer
    a whole-vehicle failure - build_comparison() reports it as just that
    one pathway being null (with its reason in `unavailable`), while HP
    and GFV for the same vehicle compute normally. The vehicle entry
    itself stays "ok": True.

    Audit batch 5: a missing PLAN no longer makes Subscription unavailable
    (the fee is estimated), so this makes it unavailable the way it now can
    be: no provider quote AND a car that can't be costed (specs incomplete -
    the estimate needs its running costs, and never guesses).
    """
    SubscriptionPlan.objects.filter(vehicle=vehicle_c).delete()
    VehicleModel.objects.filter(pk=vehicle_c.pk).update(powertrain="", engine_capacity_cc=None)

    response = request_arena(user_client, [vehicle_a, vehicle_b, vehicle_c])

    assert response.status_code == status.HTTP_200_OK  # not 400, not 500
    results = {entry["vehicle_id"]: entry for entry in response.data["results"]}

    assert results[vehicle_c.id]["ok"] is True
    assert results[vehicle_c.id]["comparison"]["subscription"] is None
    assert "missing its specs" in results[vehicle_c.id]["comparison"]["unavailable"]["subscription"]
    # HP and GFV don't depend on the running costs - still present
    # and correctly computed for the same vehicle.
    assert results[vehicle_c.id]["comparison"]["hire_purchase"] is not None
    assert results[vehicle_c.id]["comparison"]["gfv_leasing"] is not None

    assert results[vehicle_a.id]["ok"] is True
    assert results[vehicle_b.id]["ok"] is True

    # Winners computed only from the pathways actually available - C (the
    # designed subscription winner) is excluded from that one race only
    # (gross fee 900.00 for A vs 1100.00 for B - monthly_instalment is
    # now the real billed fee, QA audit H8), so A wins cheapest_subscription
    # by elimination. cheapest_hp/gfv are unaffected, since C's HP/GFV are
    # still fully present.
    winners = response.data["winners"]
    assert winners["cheapest_hp"] == {"winner_id": vehicle_b.id, "tied_with": [vehicle_b.id]}
    assert winners["cheapest_gfv"] == {"winner_id": vehicle_a.id, "tied_with": [vehicle_a.id]}
    assert winners["cheapest_subscription"] == {"winner_id": vehicle_a.id, "tied_with": [vehicle_a.id]}


# --- Shared downpayment exceeds one (cheaper) vehicle's own MSRP --------


def test_shared_downpayment_exceeding_one_vehicles_msrp_only_fails_that_vehicle(
    user_client, vehicle_a, vehicle_b, vehicle_c
):
    # vehicle_b's msrp is 70000.00 - a downpayment of 75000 exceeds it,
    # but not vehicle_a's (80000) or vehicle_c's (95000).
    response = request_arena(user_client, [vehicle_a, vehicle_b, vehicle_c], downpayment=Decimal("75000.00"))

    assert response.status_code == status.HTTP_200_OK
    results = {entry["vehicle_id"]: entry for entry in response.data["results"]}

    assert results[vehicle_b.id]["ok"] is False
    assert results[vehicle_b.id]["error"] == "Downpayment must be less than the vehicle's price."
    assert results[vehicle_a.id]["ok"] is True
    assert results[vehicle_c.id]["ok"] is True


# --- Request-shape validation (a 400, not a per-vehicle error) ----------


def test_a_single_vehicle_is_rejected(user_client, vehicle_a):
    response = request_arena(user_client, [vehicle_a])
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "vehicles" in response.data
    assert "between 2 and 3" in str(response.data["vehicles"])


def test_four_vehicles_is_rejected(user_client, vehicle_a, vehicle_b, vehicle_c):
    fourth = _make_vehicle("D", msrp="60000.00", rate_percent="3.0000", residual_ratio="0.5000", fee_monthly="800.00")
    response = request_arena(user_client, [vehicle_a, vehicle_b, vehicle_c, fourth])
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "vehicles" in response.data
    assert "between 2 and 3" in str(response.data["vehicles"])


def test_duplicate_vehicle_id_is_rejected(user_client, vehicle_a, vehicle_b):
    response = request_arena(user_client, [vehicle_a, vehicle_a, vehicle_b])
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "vehicles" in response.data
    assert "once" in str(response.data["vehicles"])


@pytest.mark.parametrize("tenure_months", [11, 109])
def test_tenure_outside_range_rejected(user_client, vehicle_a, vehicle_b, tenure_months):
    response = request_arena(user_client, [vehicle_a, vehicle_b], tenure_months=tenure_months)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
