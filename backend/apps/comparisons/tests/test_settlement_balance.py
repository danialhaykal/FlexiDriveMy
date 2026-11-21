"""Run 1 fix batch 1: settlement_balance - the estimated amount to settle an HP
or GFV loan early by the reducing-balance method (Hire-Purchase (Amendment) Act
2026), at the effective monthly rate the app already solves for every quote.

Golden values: BMW 320i, price 265,800, downpayment 26,580 (principal
239,220), dealer flat rate 2.8%. They were hand-computed outside the app (an
independent Decimal script) and are asserted to the sen. The exact (unrounded)
monthly comes from the same exact_hp_monthly / exact_gfv_monthly helpers the
app uses.
"""

from decimal import Decimal

import pytest

from apps.comparisons import formulas
from apps.comparisons.formulas import (
    effective_annual_rate,
    effective_monthly_rate,
    exact_gfv_monthly,
    exact_hp_monthly,
    settlement_balance,
    settlement_balances,
)

D = Decimal
PRICE, DOWN, RATE = D("265800.00"), D("26580.00"), D("0.028")
PRINCIPAL = PRICE - DOWN  # 239,220.00


def hp(t):
    return exact_hp_monthly(PRICE, DOWN, t, RATE)


def gfv(t, balloon):
    return exact_gfv_monthly(PRICE, DOWN, t, RATE, balloon)


@pytest.mark.parametrize(
    "tenure, month, expected",
    [
        (60, 0, "239220.00"),
        (60, 1, "235727.48"),
        (60, 12, "196280.44"),
        (60, 24, "151017.78"),
        (60, 30, "127476.28"),
        (60, 48, "53013.63"),
        (60, 60, "0.00"),
        (48, 12, "184074.51"),
        (48, 24, "125932.69"),
        (84, 12, "210148.63"),
        (84, 60, "77461.81"),
    ],
)
def test_hp_golden_balances(tenure, month, expected):
    assert settlement_balance(PRINCIPAL, hp(tenure), tenure, month) == D(expected)


def test_the_exact_monthly_used_is_the_unrounded_one():
    # 239,220 / 60 + 239,220 x 0.028 / 12 = 3,987.00 + 558.18 = 4,545.18 (exact, here it happens to be 2 dp)
    assert hp(60).quantize(D("0.01")) == D("4545.18")
    assert hp(48).quantize(D("0.01")) == D("5541.93")
    assert hp(84).quantize(D("0.01")) == D("3406.04")


@pytest.mark.parametrize(
    "tenure, balloon, month, expected",
    [
        (60, "93030.00", 24, "184174.27"),
        (48, "111636.00", 24, "177818.92"),
    ],
)
def test_gfv_golden_balances(tenure, balloon, month, expected):
    assert settlement_balance(PRINCIPAL, gfv(tenure, D(balloon)), tenure, month, D(balloon)) == D(expected)


def test_a_gfv_balance_glides_down_to_the_balloon_and_is_still_above_it_the_month_before_term():
    balloon = D("93030.00")
    just_before = settlement_balance(PRINCIPAL, gfv(60, balloon), 60, 59, balloon)

    assert just_before > balloon  # 95,709.94: one payment plus interest still to go
    assert just_before == D("95709.94")
    assert settlement_balance(PRINCIPAL, gfv(60, balloon), 60, 60, balloon) == D("0.00")  # balloon paid at month t


def test_the_balance_falls_every_month_and_is_zero_from_the_term_on():
    balances = settlement_balances(PRINCIPAL, hp(60), 60, range(0, 62))

    assert all(a > b for a, b in zip(balances[:60], balances[1:61]))
    assert balances[60] == balances[61] == D("0.00")


def test_reducing_balance_owes_more_early_on_than_the_old_straight_line_principal():
    # The old method: 239,220 x (1 - 24/60) = 143,532.00. Reducing balance
    # front-loads the interest, so less principal has been repaid at month 24.
    assert settlement_balance(PRINCIPAL, hp(60), 60, 24) == D("151017.78") > D("143532.00")


def test_settlement_balances_gives_the_same_figures_as_settlement_balance_month_for_month():
    months = [0, 1, 12, 24, 30, 48, 59, 60, 70]

    assert settlement_balances(PRINCIPAL, hp(60), 60, months) == [
        settlement_balance(PRINCIPAL, hp(60), 60, m) for m in months
    ]


# --- the zero-rate fallback -------------------------------------------------------------


def test_a_zero_rate_deal_falls_back_to_the_straight_line_balance():
    flat_free = exact_hp_monthly(PRICE, DOWN, 60, D("0"))  # 3,987.00: no interest at all

    assert effective_monthly_rate(PRINCIPAL, flat_free, 60) is None
    # (239,220 - 0) x (1 - 24/60) + 0 = 143,532.00
    assert settlement_balance(PRINCIPAL, flat_free, 60, 24) == D("143532.00")


def test_a_zero_rate_gfv_falls_back_to_the_straight_line_down_to_the_balloon():
    balloon = D("93030.00")
    flat_free = exact_gfv_monthly(PRICE, DOWN, 60, D("0"), balloon)

    # (239,220 - 93,030) x (1 - 24/60) + 93,030 = 87,714.00 + 93,030.00 = 180,744.00
    assert settlement_balance(PRINCIPAL, flat_free, 60, 24, balloon) == D("180744.00")


# --- effective_annual_rate is unchanged by the refactor ----------------------------------


@pytest.mark.parametrize(
    "tenure, expected",
    [(36, "5.3118"), (48, "5.3027"), (60, "5.2805"), (108, "5.1558")],
)
def test_effective_annual_rate_is_exactly_what_it_was(tenure, expected):
    assert abs(effective_annual_rate(PRINCIPAL, hp(tenure), tenure) - D(expected)) <= D("0.0005")


def test_effective_annual_rate_is_the_monthly_rate_times_twelve_times_one_hundred_to_four_places():
    monthly = effective_monthly_rate(PRINCIPAL, hp(60), 60)

    assert effective_annual_rate(PRINCIPAL, hp(60), 60) == (monthly * 12 * 100).quantize(formulas.FOUR_PLACES)


@pytest.mark.parametrize(
    "args",
    [(0, D("100"), 12), (D("1000"), D("10"), 12), (D("1000"), D("100"), 0), (D("1000"), D("-1"), 12)],
)
def test_effective_monthly_rate_returns_none_for_non_loans_and_never_raises(args):
    assert effective_monthly_rate(*args) is None
    assert effective_annual_rate(*args) is None
