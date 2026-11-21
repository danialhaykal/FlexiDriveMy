"""Formula-first tests for Sprint 12's Total-Loss Exposure Sandbox,
independent of Django/DRF - same pattern as test_formulas.py."""

from decimal import Decimal

from apps.depreciation import formulas

# Reference case, hand-computable: price=100000, downpayment=10000,
# tenure=36, residual 50% -> balloon=50000.
# principal = 90000; remaining_to_amortize = 90000 - 50000 = 40000.
PRICE = Decimal("100000.00")
DOWNPAYMENT = Decimal("10000.00")
TENURE_MONTHS = 36
GFV_BALLOON = Decimal("50000.00")


def test_gfv_outstanding_balance_at_month_zero_is_full_remaining_to_amortize_plus_balloon():
    # 40000 (nothing amortized yet) + 50000 (balloon, always fully owed) = 90000.
    balance = formulas.gfv_outstanding_balance(
        price=PRICE, downpayment=DOWNPAYMENT, tenure_months=TENURE_MONTHS, month=0, gfv_balloon=GFV_BALLOON
    )
    assert balance == Decimal("90000.00")


def test_gfv_outstanding_balance_halfway_is_half_remaining_to_amortize_plus_full_balloon():
    # month 18 of 36: half of 40000 (=20000) + the FULL 50000 balloon = 70000.
    balance = formulas.gfv_outstanding_balance(
        price=PRICE, downpayment=DOWNPAYMENT, tenure_months=TENURE_MONTHS, month=18, gfv_balloon=GFV_BALLOON
    )
    assert balance == Decimal("70000.00")


def test_gfv_outstanding_balance_is_the_balloon_at_the_term_and_zero_after_it():
    # FX-1 (X1): written off in the balloon month, the balloon is still owed
    # (it was 0.00 here before, which gave the buyer the whole payout).
    balance_at_term = formulas.gfv_outstanding_balance(
        price=PRICE, downpayment=DOWNPAYMENT, tenure_months=TENURE_MONTHS, month=36, gfv_balloon=GFV_BALLOON
    )
    assert balance_at_term == GFV_BALLOON

    balance_beyond_term = formulas.gfv_outstanding_balance(
        price=PRICE, downpayment=DOWNPAYMENT, tenure_months=TENURE_MONTHS, month=50, gfv_balloon=GFV_BALLOON
    )
    assert balance_beyond_term == Decimal("0.00")


def test_gfv_outstanding_balance_always_owes_at_least_the_full_balloon_before_term_end():
    # One month before term end, only a sliver of remaining_to_amortize is
    # left, but the full, never-amortized balloon is still owed in full.
    balance = formulas.gfv_outstanding_balance(
        price=PRICE, downpayment=DOWNPAYMENT, tenure_months=TENURE_MONTHS, month=35, gfv_balloon=GFV_BALLOON
    )
    # remaining_fraction = 1/36; 40000 * 1/36 = 1111.11 (rounded) + 50000.
    assert balance == Decimal("51111.11")
