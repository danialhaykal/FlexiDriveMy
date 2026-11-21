"""Run 3 fix batch 4 (F-19): the Total-Loss Sandbox offers Hire Purchase and GFV exactly when the comparison does, with
the comparison's own reason. Before, a downpayment above GFV's financed amount (BMW 320i, 12 months, RM 133,900 down)
got a GFV card whose 'amount to settle' rose above the amount financed. Every figure of an offered pathway is unchanged."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.comparisons.services import RATE_NOT_SET_MESSAGE, build_comparison
from apps.depreciation import formulas
from apps.depreciation.inference import predict_resale_curve
from apps.policy.mileage import representative_km
from apps.policy.models import InterestRate, MileageBand, ResidualValueMatrix
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

URL = "/api/depreciation/total-loss-sandbox/"


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


@pytest.fixture
def brand():
    return Brand.objects.create(name="SandboxBrand", tier_code="2")


@pytest.fixture
def car(brand):
    vehicle = VehicleModel.objects.create(
        brand=brand, name="Sandbox", trim="X", body_segment=BodySegment.SEDAN, msrp=Decimal("100000.00"),
        engine_capacity_kw=Decimal("110.00"), powertrain="petrol", engine_capacity_cc=1998,
    )
    vehicle.refresh_from_db()
    return vehicle


@pytest.fixture
def rate(brand):
    return InterestRate.objects.create(brand=brand, rate_percent=Decimal("3.0000"))


@pytest.fixture
def override_12(brand):
    # balloon RM 77,000 at 12 months: GFV finances at most RM 23,000 of downpayment.
    return ResidualValueMatrix.objects.create(brand=brand, tenure_months=12, mileage_band=MileageBand.STANDARD,
                                              residual_value_ratio=Decimal("0.7700"))


def get(client, car, tenure, downpayment, month, excess="0"):
    response = client.get(URL, {"vehicle": car.pk, "tenure_months": tenure, "mileage_band": "standard",
                                "downpayment": downpayment, "loss_month": month, "excess_amount": excess})
    assert response.status_code == 200, response.data
    return response.data


def expected_payout(car, month, excess=Decimal("0")):
    curve, _degraded, _reason = predict_resale_curve(vehicle=car, annual_mileage_km=representative_km("standard"))
    return formulas.round_currency(max(curve[min(month, formulas.HORIZON_MONTHS)] - excess, Decimal("0")))


def test_gfv_not_offered_when_the_downpayment_exceeds_what_gfv_finances(client, car, rate, override_12):
    comparison = build_comparison(vehicle=car, tenure_months=12, mileage_band="standard", downpayment=Decimal("50000.00"))
    assert comparison["gfv_leasing"] is None  # the comparison's decision

    data = get(client, car, 12, "50000.00", 6)

    assert data["gfv_leasing"] is None
    assert data["unavailable"]["gfv_leasing"] == comparison["unavailable"]["gfv_leasing"]
    assert data["unavailable"]["gfv_leasing"] == (
        "Your downpayment exceeds the amount financed under GFV (maximum RM 23,000.00 for this term).")
    # Hire Purchase is still offered, with the same figures as before.
    balance = formulas.hp_outstanding_balance(Decimal("100000.00"), Decimal("50000.00"), 12, 6, Decimal("0.03"))
    payout = expected_payout(car, 6)
    assert data["hire_purchase"]["outstanding_balance"] == f"{balance:.2f}"
    assert data["hire_purchase"]["insurance_payout"] == f"{payout:.2f}"
    assert data["hire_purchase"]["net_position"] == f"{formulas.round_currency(payout - balance):.2f}"
    assert "hire_purchase" not in data["unavailable"]


def test_gfv_not_offered_above_60_months_uses_the_comparisons_reason(client, car, rate):
    comparison = build_comparison(vehicle=car, tenure_months=72, mileage_band="standard", downpayment=Decimal("10000.00"))
    assert comparison["gfv_leasing"] is None

    data = get(client, car, 72, "10000.00", 30)

    assert data["gfv_leasing"] is None
    assert data["unavailable"]["gfv_leasing"] == comparison["unavailable"]["gfv_leasing"]
    assert "72 months" in data["unavailable"]["gfv_leasing"]
    assert data["hire_purchase"] is not None


def test_hire_purchase_and_gfv_not_offered_without_a_rate(client, car, override_12):
    data = get(client, car, 12, "10000.00", 6)

    assert data["hire_purchase"] is None and data["gfv_leasing"] is None
    assert data["unavailable"] == {"hire_purchase": RATE_NOT_SET_MESSAGE, "gfv_leasing": RATE_NOT_SET_MESSAGE}
    # Subscription keeps its "no ownership stake" card.
    assert data["subscription"]["has_ownership_exposure"] is False


def test_all_pathways_offered_figures_unchanged(client, car, rate, override_12):
    data = get(client, car, 12, "10000.00", 6, excess="2500")

    assert data["unavailable"] == {}
    payout = expected_payout(car, 6, Decimal("2500"))
    hp_balance = formulas.hp_outstanding_balance(Decimal("100000.00"), Decimal("10000.00"), 12, 6, Decimal("0.03"))
    balloon = Decimal("77000.00")
    gfv_balance = formulas.gfv_outstanding_balance(price=Decimal("100000.00"), downpayment=Decimal("10000.00"), tenure_months=12,
                                                   month=6, gfv_balloon=balloon, annual_rate=Decimal("0.03"))
    assert data["hire_purchase"] == {"insurance_payout": f"{payout:.2f}", "outstanding_balance": f"{hp_balance:.2f}",
                                     "net_position": f"{formulas.round_currency(payout - hp_balance):.2f}",
                                     "has_ownership_exposure": True}
    assert data["gfv_leasing"] == {"insurance_payout": f"{payout:.2f}", "outstanding_balance": f"{gfv_balance:.2f}",
                                   "net_position": f"{formulas.round_currency(payout - gfv_balance):.2f}",
                                   "has_ownership_exposure": True}


def test_the_threshold_downpayment_still_offers_gfv(client, car, rate, override_12):
    # Exactly the maximum GFV finances (price - balloon): offered, as in the comparison.
    data = get(client, car, 12, "23000.00", 6)
    assert data["gfv_leasing"] is not None
    assert "gfv_leasing" not in data["unavailable"]
