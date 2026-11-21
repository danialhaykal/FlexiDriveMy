"""FX-1 (X1): written off in the GFV balloon month, the balloon is still owed. At month = tenure the sandbox's GFV
"amount to settle" is the balloon and the net position is the payout less it; month t-1, Hire Purchase (fully repaid at
month t), Subscription and the month refusals are unchanged. The BMW 320i case is the one Run 4 / 4B reported
(36 months, Standard, RM 26,780 down: GFV showed RM 0.00 to settle and the same net as HP)."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.comparisons.formulas import settlement_balance
from apps.comparisons.services import build_comparison
from apps.depreciation import formulas
from apps.depreciation.inference import predict_resale_curve
from apps.policy.mileage import representative_km
from apps.policy.models import InterestRate
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

URL = "/api/depreciation/total-loss-sandbox/"


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


def _car(brand_name, tier, rate, **fields):
    brand, _ = Brand.objects.get_or_create(name=brand_name, defaults={"tier_code": tier})
    InterestRate.objects.filter(brand=brand).update(is_active=False)
    InterestRate.objects.create(brand=brand, rate_percent=Decimal(rate))
    car = VehicleModel.objects.create(brand=brand, **fields)
    car.refresh_from_db()
    return car


@pytest.fixture
def bmw():
    # BMW 320i as in the catalog: RM 267,800, petrol 1,998 cc sedan, 2.80% flat; BMW and petrol add 0 residual points.
    return _car("BMW", "4", "2.8000", name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN,
                msrp=Decimal("267800.00"), engine_capacity_kw=Decimal("135.00"), powertrain="petrol", engine_capacity_cc=1998)


@pytest.fixture
def alphard():
    # Another car: a Toyota MPV, 48 months.
    return _car("Toyota", "3", "2.5000", name="Alphard", trim="2.4 Executive Lounge", body_segment=BodySegment.MPV,
                msrp=Decimal("548000.00"), engine_capacity_kw=Decimal("205.00"), powertrain="petrol", engine_capacity_cc=2393)


def get(client, car, tenure, downpayment, month, excess="0"):
    response = client.get(URL, {"vehicle": car.pk, "tenure_months": tenure, "mileage_band": "standard",
                                "downpayment": downpayment, "loss_month": month, "excess_amount": excess})
    assert response.status_code == 200, response.data
    return response.data


def payout(car, month, excess=Decimal("0")):
    curve, _degraded, _reason = predict_resale_curve(vehicle=car, annual_mileage_km=representative_km("standard"))
    return formulas.round_currency(max(curve[min(month, formulas.HORIZON_MONTHS)] - excess, Decimal("0")))


@pytest.mark.parametrize("tenure, balloon", [(36, "138693.62"), (60, "98523.62")])
def test_bmw_gfv_at_the_balloon_month_owes_the_balloon(client, bmw, tenure, balloon):
    data = get(client, bmw, tenure, "26780.00", tenure)
    gfv = data["gfv_leasing"]

    assert Decimal(gfv["outstanding_balance"]) == Decimal(balloon)
    assert Decimal(gfv["insurance_payout"]) == payout(bmw, tenure)
    assert Decimal(gfv["net_position"]) == payout(bmw, tenure) - Decimal(balloon)
    # Hire Purchase is fully repaid at month t: unchanged 0.00, so its net is the whole payout.
    assert Decimal(data["hire_purchase"]["outstanding_balance"]) == Decimal("0.00")
    assert Decimal(data["hire_purchase"]["net_position"]) == payout(bmw, tenure)
    assert data["subscription"]["outstanding_balance"] is None


@pytest.mark.parametrize("tenure, balloon", [(36, "138693.62"), (60, "98523.62")])
def test_bmw_gfv_one_month_before_the_term_is_unchanged(client, bmw, tenure, balloon):
    data = get(client, bmw, tenure, "26780.00", tenure - 1)
    principal = Decimal("267800.00") - Decimal("26780.00")
    exact = formulas.exact_gfv_monthly(Decimal("267800.00"), Decimal("26780.00"), tenure, Decimal("0.028"), Decimal(balloon))
    expected = settlement_balance(principal, exact, tenure, tenure - 1, Decimal(balloon))

    assert Decimal(data["gfv_leasing"]["outstanding_balance"]) == expected
    assert expected > Decimal(balloon)  # still on the glide path down to the balloon


def test_bmw_excess_comes_off_the_payout_before_the_balloon(client, bmw):
    data = get(client, bmw, 36, "26780.00", 36, excess="2000")
    gfv = data["gfv_leasing"]
    assert Decimal(gfv["insurance_payout"]) == payout(bmw, 36, Decimal("2000"))
    assert Decimal(gfv["net_position"]) == payout(bmw, 36, Decimal("2000")) - Decimal("138693.62")


def test_another_car_owes_its_own_balloon_at_the_term(client, alphard):
    # The comparison's own balloon for these inputs (the test database has the seeded baselines but no brand rows for
    # the adjustments, so 48 months / standard is the 0.4379 baseline: 548,000 x 0.4379 = 239,969.20).
    balloon = build_comparison(vehicle=alphard, tenure_months=48, mileage_band="standard",
                               downpayment=Decimal("54800.00"))["gfv_leasing"]["balloon_payment"]
    assert balloon == Decimal("239969.20")
    data = get(client, alphard, 48, "54800.00", 48)
    assert Decimal(data["gfv_leasing"]["outstanding_balance"]) == balloon
    assert Decimal(data["gfv_leasing"]["net_position"]) == payout(alphard, 48) - balloon
    assert Decimal(data["hire_purchase"]["outstanding_balance"]) == Decimal("0.00")
    # month t-1 is still the settlement figure, above the balloon
    assert Decimal(get(client, alphard, 48, "54800.00", 47)["gfv_leasing"]["outstanding_balance"]) > balloon


def test_month_refusals_are_unchanged(client, bmw):
    for month in (0, 37):
        response = client.get(URL, {"vehicle": bmw.pk, "tenure_months": 36, "mileage_band": "standard",
                                    "downpayment": "26780.00", "loss_month": month, "excess_amount": "0"})
        assert response.status_code == 400
        assert response.data["loss_month"] == ["Choose a month from 1 to 36."]
