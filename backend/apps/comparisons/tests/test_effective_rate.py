"""Audit batch 3: the dealer's FLAT rate is unchanged and still drives every
instalment; the effective (reducing-balance) rate a bank would disclose is
DERIVED beside it by formulas.effective_annual_rate - nominal annual rate
compounded monthly, as a percent:

    principal = payment x (1 - (1+i)^-t) / i + balloon x (1+i)^-t     (i = monthly rate)

Golden values come from the audit; the solver must agree to within 0.0005.
"""

from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.comparisons import formulas
from apps.comparisons.services import build_comparison
from apps.policy.models import InterestRate, MileageBand, ResidualBaseline, ResidualValueMatrix, SubscriptionPlan
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal
TOLERANCE = D("0.0005")


def hp_effective(flat_percent, tenure, price=D("265800")):
    down = price * D("0.1")
    exact = formulas.exact_hp_monthly(price, down, tenure, D(flat_percent) / 100)
    return formulas.effective_annual_rate(price - down, exact, tenure)


# --- golden values (HP's effective rate does not depend on price) ---------------


@pytest.mark.parametrize(
    "flat, tenure, price, expected",
    [
        ("2.8", 36, "265800", "5.3118"),    # BMW HP
        ("2.8", 48, "265800", "5.3027"),
        ("2.8", 60, "265800", "5.2805"),
        ("2.8", 108, "265800", "5.1558"),
        ("2.5", 48, "328888", "4.7510"),    # Volvo HP
        ("3.5", 48, "575000", "6.5760"),    # Macan Electric HP
    ],
)
def test_hire_purchase_effective_rate_golden_values(flat, tenure, price, expected):
    assert abs(hp_effective(flat, tenure, D(price)) - D(expected)) <= TOLERANCE


def test_hire_purchase_effective_rate_does_not_depend_on_price():
    assert hp_effective("2.8", 48, D("100000")) == hp_effective("2.8", 48, D("1430000"))


def test_gfv_effective_rate_golden_value():
    price = D("265800")
    down = price * D("0.1")
    balloon = formulas.calculate_gfv_balloon(price, D("0.42"))
    monthly = formulas.exact_gfv_monthly(price, down, 48, D("0.028"), balloon)

    effective = formulas.effective_annual_rate(price - down, monthly, 48, balloon)

    assert abs(effective - D("3.7556")) <= TOLERANCE


def test_the_result_is_a_decimal_rounded_to_four_places():
    result = hp_effective("2.8", 36)

    assert isinstance(result, Decimal)
    assert result == result.quantize(D("0.0001"))


# --- the solver is the inverse of the reducing-balance formula --------------------------


def payment_for(principal, monthly_rate, tenure, balloon=D("0")):
    discount = (1 + monthly_rate) ** -tenure
    return (principal - balloon * discount) * monthly_rate / (1 - discount)


@pytest.mark.parametrize("annual_percent", ["0.5", "3.0", "6.0", "12.5", "24.0"])
@pytest.mark.parametrize("tenure", [12, 48, 108])
def test_round_trip_a_payment_built_from_a_known_reducing_balance_rate_returns_that_rate(annual_percent, tenure):
    monthly_rate = D(annual_percent) / 100 / 12
    principal = D("200000")

    recovered = formulas.effective_annual_rate(principal, payment_for(principal, monthly_rate, tenure), tenure)

    assert abs(recovered - D(annual_percent)) <= D("0.0001")


def test_round_trip_with_a_balloon():
    monthly_rate = D("0.045") / 12
    principal, balloon = D("250000"), D("90000")

    recovered = formulas.effective_annual_rate(
        principal, payment_for(principal, monthly_rate, 48, balloon), 48, balloon
    )

    assert abs(recovered - D("4.5")) <= D("0.0001")


# --- no solution -> None, never an exception ------------------------------------------------


def test_a_zero_rate_loan_returns_none():
    assert formulas.effective_annual_rate(D("120000"), D("2500"), 48) is None  # 2,500 x 48 = principal exactly


def test_repaying_less_than_the_principal_a_negative_rate_returns_none():
    assert formulas.effective_annual_rate(D("120000"), D("2000"), 48) is None


def test_a_balloon_that_makes_the_total_no_more_than_the_principal_returns_none():
    assert formulas.effective_annual_rate(D("100000"), D("1000"), 48, D("52000")) is None  # 48,000 + 52,000 = 100,000


@pytest.mark.parametrize(
    "principal, payment, tenure",
    [("0", "100", 12), ("-5", "100", 12), ("1000", "100", 0), ("1000", "100", -3), ("1000", "-1", 12), ("abc", "1", 12)],
)
def test_nonsense_inputs_return_none(principal, payment, tenure):
    assert formulas.effective_annual_rate(principal, payment, tenure) is None


# --- build_comparison exposes it beside the (unchanged) flat rate ------------------------------


@pytest.fixture
def bmw():
    brand = Brand.objects.create(name="EffBrand", tier_code="2")
    vehicle = VehicleModel.objects.create(
        brand=brand, name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN, msrp=D("265800.00"),
        engine_capacity_kw=D("135.00"), powertrain="petrol", engine_capacity_cc=1998,
    )
    vehicle.refresh_from_db()
    return vehicle


def configure(vehicle, flat="2.8000", residual="0.4200", tenure=48):
    InterestRate.objects.create(brand=vehicle.brand, rate_percent=flat)
    ResidualValueMatrix.objects.create(
        brand=vehicle.brand, tenure_months=tenure, mileage_band=MileageBand.STANDARD, residual_value_ratio=residual
    )
    SubscriptionPlan.objects.create(vehicle=vehicle, fee_monthly="6500.00")


def comparison_for(vehicle, tenure=48):
    return build_comparison(
        vehicle=vehicle, tenure_months=tenure, mileage_band=MileageBand.STANDARD, downpayment=D("26580.00")
    )


def test_build_comparison_returns_the_effective_rate_for_hp_and_gfv_and_keeps_the_flat_rate(bmw):
    configure(bmw)

    result = comparison_for(bmw)

    assert result["hire_purchase"]["interest_rate_percent"] == D("2.8000")  # flat rate, untouched
    assert abs(result["hire_purchase"]["effective_rate_percent"] - D("5.3027")) <= TOLERANCE
    assert abs(result["gfv_leasing"]["effective_rate_percent"] - D("3.7556")) <= TOLERANCE


def test_no_existing_instalment_or_outlay_figure_changed(bmw):
    """P=265,800, D=26,580, 48 months, 2.8% flat: principal 239,220 ->
    239,220/48 = 4,983.75 + 239,220 x 0.028 / 12 = 558.18 -> 5,541.93/month;
    outlay = 26,580 + 5,541.93 x 48 = 292,592.64. GFV: balloon = 42% x 265,800
    = 111,636.00 -> (239,220 - 111,636)/48 = 2,658.00 + 558.18 = 3,216.18/month."""
    configure(bmw)

    result = comparison_for(bmw)

    hp, gfv = result["hire_purchase"], result["gfv_leasing"]
    assert hp["monthly_instalment"] == D("5541.93")
    assert hp["total_contract_outlay"] == D("292592.64")
    assert gfv["balloon_payment"] == D("111636.00")
    assert gfv["monthly_instalment"] == D("3216.18")
    # 26,580 + 3,216.18 x 48 (= 154,376.64) + balloon 111,636.00 = 292,592.64 - the same total as HP,
    # as it must be: both repay the price plus the same flat interest.
    assert gfv["total_contract_outlay"] == D("292592.64")


def test_the_effective_rate_is_omitted_cleanly_when_a_pathway_is_unavailable(bmw):
    # No interest rate at all: HP and GFV are both None, so there is no key to be missing or null.
    SubscriptionPlan.objects.create(vehicle=bmw, fee_monthly="6500.00")

    result = comparison_for(bmw)

    assert result["hire_purchase"] is None and result["gfv_leasing"] is None


def test_gfv_alone_unavailable_leaves_hp_with_its_effective_rate(bmw):
    InterestRate.objects.create(brand=bmw.brand, rate_percent="2.8000")
    # No residual can be resolved for 48 months: no override, and the
    # estimator's baseline for that tenure is retired.
    ResidualBaseline.objects.filter(tenure_months=48).update(is_active=False)

    result = comparison_for(bmw)

    assert result["gfv_leasing"] is None
    assert abs(result["hire_purchase"]["effective_rate_percent"] - D("5.3027")) <= TOLERANCE


def test_the_endpoint_serialises_the_effective_rate_as_a_four_place_string(bmw, regular_user):
    configure(bmw)
    client = APIClient()
    client.force_authenticate(user=regular_user)

    response = client.get(
        "/api/comparisons/",
        {"vehicle": bmw.id, "tenure_months": 48, "mileage_band": MileageBand.STANDARD, "downpayment": "26580.00"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["hire_purchase"]["interest_rate_percent"] == "2.8000"
    assert response.data["hire_purchase"]["effective_rate_percent"] == "5.3027"
    assert response.data["gfv_leasing"]["effective_rate_percent"] == "3.7556"
