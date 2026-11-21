"""FX-3 (item 1): two additive, read-only API fields - figures the screens could only name by parsing a sentence.

- comparison `gfv_max_downpayment`: price less the GFV balloon for this term, the same figure the "exceeds the
  amount financed under GFV (maximum RM ...)" reason quotes; null when GFV has no term (or rate) to limit.
- TCO `operating_cost_policy.maintenance_cap_annual`: the yearly maintenance cap of the rate row the engine used.

Neither changes any other figure; the reference values are worked out by hand below."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.comparisons.services import build_comparison
from apps.policy.models import InterestRate, MileageBand, OperatingCostRate
from apps.policy.operating_costs import estimate_operating_costs
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def car():
    brand = Brand.objects.create(name="Limit Motors", tier_code="3")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    return VehicleModel.objects.create(
        brand=brand, name="Limit", trim="One", body_segment=BodySegment.SEDAN, msrp=D("400000.00"),
        engine_capacity_kw=D("135.00"), powertrain="petrol", engine_capacity_cc=1998,
    )


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


# 36 months / standard: residual 0.5179 (baseline, 0 pts brand, 0 pts petrol) -> balloon 400,000 x 0.5179
# = 207,160.00 -> maximum downpayment 400,000 - 207,160 = 192,840.00.
MAX_36 = D("192840.00")


def compare(car, tenure, downpayment):
    return build_comparison(vehicle=car, tenure_months=tenure, mileage_band=MileageBand.STANDARD,
                            downpayment=D(downpayment))


def test_the_limit_is_sent_while_gfv_is_offered(car):
    result = compare(car, 36, "40000.00")

    assert result["gfv_leasing"]["balloon_payment"] == D("207160.00")
    assert result["gfv_max_downpayment"] == MAX_36


def test_the_limit_is_the_figure_the_exceeds_sentence_quotes(car):
    result = compare(car, 36, "200000.00")

    assert result["gfv_leasing"] is None
    assert result["gfv_max_downpayment"] == MAX_36
    # the sentence is unchanged and quotes the same figure
    assert result["unavailable"]["gfv_leasing"] == (
        "Your downpayment exceeds the amount financed under GFV (maximum RM 192,840.00 for this term)."
    )


def test_a_downpayment_exactly_at_the_limit_still_gets_gfv(car):
    result = compare(car, 36, "192840.00")

    assert result["gfv_leasing"] is not None
    assert result["gfv_max_downpayment"] == MAX_36


def test_no_limit_when_gfv_is_not_offered_for_the_term(car):
    result = compare(car, 72, "40000.00")

    assert result["gfv_leasing"] is None
    assert result["gfv_max_downpayment"] is None


def test_no_limit_without_an_interest_rate(car):
    InterestRate.objects.filter(brand=car.brand).update(is_active=False)

    result = compare(car, 36, "40000.00")

    assert result["gfv_max_downpayment"] is None


def test_the_comparison_endpoint_sends_it_as_money(user_client, car):
    query = f"vehicle={car.id}&tenure_months=36&mileage_band=standard"
    body = user_client.get(f"/api/comparisons/?{query}&downpayment=40000.00").json()
    beyond = user_client.get(f"/api/comparisons/?{query}&downpayment=200000.00").json()
    not_offered = user_client.get(f"/api/comparisons/?vehicle={car.id}&tenure_months=72&mileage_band=standard"
                                  "&downpayment=40000.00").json()

    assert body["gfv_max_downpayment"] == "192840.00"
    assert beyond["gfv_max_downpayment"] == "192840.00"
    assert not_offered["gfv_max_downpayment"] is None


# --- maintenance cap ---------------------------------------------------------------------------------------------

def test_the_engine_reports_the_cap_of_the_rate_row_it_used(car):
    rate = OperatingCostRate.objects.get(is_active=True, powertrain="petrol")

    costs = estimate_operating_costs(car)

    assert costs.maintenance_cap_annual == rate.maintenance_cap_annual == D("8000.00")


def test_the_tco_response_names_the_cap(user_client, car):
    body = user_client.get(f"/api/depreciation/tco/?vehicle={car.id}&tenure_months=36&mileage_band=standard"
                           "&downpayment=40000.00").json()

    assert body["operating_cost_policy"] == {"maintenance_cap_annual": "8000.00"}
    # 1.0% of 400,000 = 4,000.00 is under the cap, so the figure is unchanged by it
    assert body["maintenance_annual"] == "4000.00"


def test_no_cap_is_sent_as_null(user_client, car):
    OperatingCostRate.objects.filter(is_active=True, powertrain="petrol").update(maintenance_cap_annual=None)

    body = user_client.get(f"/api/depreciation/tco/?vehicle={car.id}&tenure_months=36&mileage_band=standard"
                           "&downpayment=40000.00").json()

    assert body["operating_cost_policy"] == {"maintenance_cap_annual": None}
