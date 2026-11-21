"""Run 1 fix batch 1, Step 2: every balance a screen shows comes from the
reducing-balance settlement_balance. Expected values are the hand-computed
"After" column of the batch prompt (standard mileage, 10% down), re-derived
independently outside the app; the "Before" values are noted beside them.

60-month-or-shorter TCO must NOT change - it never depended on a balance.

Run 3 fix batch 6: the standard-band residuals were recalibrated (36 / 48 / 60
months 0.5179 / 0.4379 / 0.3679, were 0.50 / 0.42 / 0.35), which moves the resale
curve, the GFV balloon and so every figure below that reads them; balances of a
Hire Purchase loan do not move. Re-derived by a standalone script (bisection solve
of the effective rate, the anchored curve) that first reproduced every old value.
"""

import importlib
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient

from apps.comparisons.arena import build_arena
from apps.policy.models import InterestRate
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal
seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")


def make(brand_name, rate, **fields):
    brand, _ = Brand.objects.get_or_create(name=brand_name, defaults={"tier_code": "2"})
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.get_or_create(brand=brand, is_active=True, defaults={"rate_percent": rate})
    vehicle = VehicleModel.objects.create(brand=brand, body_segment=BodySegment.SEDAN, **fields)
    vehicle.refresh_from_db()
    return vehicle


@pytest.fixture
def bmw():
    return make("BMW", "2.8000", name="3 Series", trim="320i Sport", msrp="265800.00",
                engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998)


@pytest.fixture
def xc90():
    return make("Volvo", "2.5000", name="XC90", trim="Ultra T8", msrp="434888.00",
                engine_capacity_kw="233.15", powertrain="phev", engine_capacity_cc=1969)


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


def tco(client, vehicle, tenure):
    down = (vehicle.msrp * D("0.10")).quantize(D("0.01"))
    response = client.get(
        "/api/depreciation/tco/",
        {"vehicle": vehicle.id, "tenure_months": tenure, "mileage_band": "standard", "downpayment": str(down)},
    )
    assert response.status_code == 200
    return response.data


def test_bmw_60_month_tco_is_unchanged(client, bmw):
    data = tco(client, bmw, 60)

    assert (D(data["tco_gross"]), D(data["tco_net"])) == (D("338397.80"), D("240609.98"))  # net was 245,367.80
    assert data["negative_equity_crossover_month"] is None  # before and after: none


def test_bmw_84_month_net_tco_credits_the_reducing_balance_equity(client, bmw):
    data = tco(client, bmw, 84)

    # gross unchanged; equity at month 60 = 97,787.82 - 77,461.81 (net was 254,481.21 on resale 93,030.00)
    assert D(data["tco_gross"]) == D("270049.40")
    assert D(data["tco_net"]) == D("249723.39")
    assert data["monthly_forecast"][60]["hp_outstanding_balance"] == "77461.81"


def test_bmw_84_month_crossover(client, bmw):
    data = tco(client, bmw, 84)

    # was month 12 / 379.71 (straight line), then 10 / 244.64 (before Run 3 fix batch 6)
    assert (data["negative_equity_crossover_month"], data["negative_equity_shortfall_amount"]) == (11, "261.95")


def test_xc90_t8_60_month_crossover(client, xc90):
    data = tco(client, xc90, 60)

    # was month 11 / 4,348.88 (straight line), then 9 / 1,380.83 (before Run 3 fix batch 6)
    assert (data["negative_equity_crossover_month"], data["negative_equity_shortfall_amount"]) == (10, "2371.85")


def test_the_chart_balance_is_the_reducing_balance_series(client, bmw):
    forecast = tco(client, bmw, 60)["monthly_forecast"]

    assert [forecast[m]["hp_outstanding_balance"] for m in (0, 1, 12, 24, 30, 48, 60)] == [
        "239220.00", "235727.48", "196280.44", "151017.78", "127476.28", "53013.63", "0.00",
    ]


def test_total_loss_bmw_60_months_month_24_with_excess_2500(client, bmw):
    response = client.get(
        "/api/depreciation/total-loss-sandbox/",
        {"vehicle": bmw.id, "tenure_months": 60, "mileage_band": "standard", "downpayment": "26580.00",
         "loss_month": 24, "excess_amount": "2500.00"},
    )

    assert response.status_code == 200
    hp, gfv = response.data["hire_purchase"], response.data["gfv_leasing"]
    # resale(24) 164,982.06 (was 162,138.00); GFV balloon 97,787.82 (was 93,030.00).
    # was 151,017.78 / +8,620.22 and 184,174.27 / -24,536.27 before Run 3 fix batch 6
    assert (hp["outstanding_balance"], hp["net_position"]) == ("151017.78", "11464.28")
    assert (gfv["outstanding_balance"], gfv["net_position"]) == ("185923.12", "-23441.06")


def test_arena_tco_for_an_84_month_tenure_uses_the_same_balance(bmw):
    results = build_arena(vehicles=[bmw], tenure_months=84, mileage_band="standard", downpayment=D("26580.00"))

    assert results[0]["tco_net"] == D("249723.39")  # was 254,481.21


def test_instalments_outlays_and_rates_are_untouched(client, bmw):
    comparison = client.get(
        "/api/comparisons/",
        {"vehicle": bmw.id, "tenure_months": 60, "mileage_band": "standard", "downpayment": "26580.00"},
    ).data

    assert comparison["hire_purchase"]["monthly_instalment"] == "4545.18"
    assert comparison["hire_purchase"]["effective_rate_percent"] == "5.2805"
    # the GFV figures follow the recalibrated 60-month residual (was 2,994.68 / 93,030.00)
    assert comparison["gfv_leasing"]["monthly_instalment"] == "2915.38"
    assert comparison["gfv_leasing"]["balloon_payment"] == "97787.82"
