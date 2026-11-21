"""Formula-first tests: these pin down the project spec's calculation functions in
total isolation from Django/DRF, before any endpoint exists."""

from decimal import Decimal

from apps.comparisons.formulas import (
    calculate_gfv_balloon,
    calculate_gfv_monthly,
    calculate_hp_monthly,
    calculate_subscription_net_cost,
)

# the project spec's mandated reference case (must reproduce exactly, to 2dp):
# P=400000, D=40000, t=36, r=3%, G_ratio=50% -> balloon=200,000.00, GFV_monthly=5,344.44
REFERENCE_PRICE = Decimal("400000")
REFERENCE_DOWNPAYMENT = Decimal("40000")
REFERENCE_TENURE_MONTHS = 36
REFERENCE_RATE = Decimal("0.03")
REFERENCE_RESIDUAL_RATIO = Decimal("0.50")


def test_gfv_reference_case_balloon():
    balloon = calculate_gfv_balloon(REFERENCE_PRICE, REFERENCE_RESIDUAL_RATIO)
    assert balloon == Decimal("200000.00")


def test_gfv_reference_case_monthly():
    balloon = calculate_gfv_balloon(REFERENCE_PRICE, REFERENCE_RESIDUAL_RATIO)

    monthly = calculate_gfv_monthly(
        REFERENCE_PRICE, REFERENCE_DOWNPAYMENT, REFERENCE_TENURE_MONTHS, REFERENCE_RATE, balloon
    )

    assert monthly == Decimal("5344.44")


def test_gfv_monthly_manual_reconciliation():
    # Manually reconciled schedule, independent of the function under test:
    # principal = 400000 - 40000 = 360000
    # balloon = 400000 * 0.50 = 200000
    # amortized principal = 360000 - 200000 = 160000, spread over 36 months = 4444.444...
    # flat monthly interest = 360000 * 0.03 / 12 = 900.00
    # total = 4444.444... + 900.00 = 5344.444... -> 5344.44
    balloon = calculate_gfv_balloon(REFERENCE_PRICE, REFERENCE_RESIDUAL_RATIO)
    monthly = calculate_gfv_monthly(
        REFERENCE_PRICE, REFERENCE_DOWNPAYMENT, REFERENCE_TENURE_MONTHS, REFERENCE_RATE, balloon
    )
    principal = REFERENCE_PRICE - REFERENCE_DOWNPAYMENT
    expected_amortized_slice = (principal - balloon) / REFERENCE_TENURE_MONTHS
    expected_interest_slice = principal * REFERENCE_RATE / Decimal(12)
    expected = (expected_amortized_slice + expected_interest_slice).quantize(Decimal("0.01"))
    assert monthly == expected


# --- Hire Purchase --------------------------------------------------------
# No official the project spec reference case exists for HP; this is a manual
# reconciliation against the corrected formula's own definition, using the
# same inputs as the GFV reference case for direct comparability.


def test_hp_monthly_manual_reconciliation():
    monthly = calculate_hp_monthly(
        REFERENCE_PRICE, REFERENCE_DOWNPAYMENT, REFERENCE_TENURE_MONTHS, REFERENCE_RATE
    )
    # principal = 360000; amortized slice = 360000/36 = 10000.00
    # flat monthly interest = 360000 * 0.03 / 12 = 900.00
    # total = 10900.00
    assert monthly == Decimal("10900.00")


def test_hp_monthly_zero_rate_is_pure_amortization():
    monthly = calculate_hp_monthly(Decimal("120000"), Decimal("20000"), 24, Decimal("0"))
    assert monthly == Decimal("4166.67")  # 100000 / 24, no interest slice


def test_hp_monthly_rounds_to_two_decimal_places_half_up():
    # 100000/3 months = 33333.333... -> rounds to 33333.33 (not 33333.3333...)
    monthly = calculate_hp_monthly(Decimal("100000"), Decimal("0"), 3, Decimal("0"))
    assert monthly == Decimal("33333.33")


# --- Subscription -----------------------------------------------------


def test_subscription_net_cost_reference_style_case():
    # Fee=2000/mo, Insurance=3600/yr, Tax=1200/yr, Maintenance=1800/yr
    # offset = (3600+1200+1800)/12 = 6600/12 = 550.00
    # net = 2000 - 550 = 1450.00
    net_cost = calculate_subscription_net_cost(
        Decimal("2000.00"), Decimal("3600.00"), Decimal("1200.00"), Decimal("1800.00")
    )
    assert net_cost == Decimal("1450.00")


def test_subscription_net_cost_can_be_negative_if_offsets_exceed_fee():
    # A generous value-added offset can legitimately drive net cost below zero.
    net_cost = calculate_subscription_net_cost(
        Decimal("500.00"), Decimal("3600.00"), Decimal("1200.00"), Decimal("1800.00")
    )
    assert net_cost == Decimal("-50.00")
