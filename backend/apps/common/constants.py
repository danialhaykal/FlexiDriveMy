from decimal import ROUND_UP, Decimal

from django.core.validators import MaxValueValidator, MinValueValidator

# HP_monthly's tenure t must be an integer in [12, 108] inclusive (the project spec).
# Shared by apps.policy (residual value matrix tenure) and apps.profiles
# (a user's preferred tenure, UC003 Rule 2) so the accepted range can't drift
# between the two.
MIN_TENURE_MONTHS = 12
MAX_TENURE_MONTHS = 108

# FYP1 report Ch.2 2.1.1: "Conventional HP loans mandate a minimum 10%
# downpayment"; A3 Update: HP "requiring a minimum 10% cash downpayment";
# the report's own GFV worked example uses exactly 10% (RM 40,000 on
# RM 400,000). Applies to HP and GFV (both are credit/leasing products
# needing a downpayment) - Subscription has none by design, so it's
# unaffected. Single source of truth, shared by every calculation
# endpoint that takes a downpayment (comparisons, depreciation, scoring).
MIN_DOWNPAYMENT_RATIO = Decimal("0.10")
_TWO_PLACES = Decimal("0.01")

# QA audit M15: a GFV residual ratio could be set as high as 100% in
# admin, which produces a negative/nonsensical monthly instalment (the
# same failure mode Batch 1's C5 fix guards against at calculation time:
# financed_amount = price - downpayment - balloon, and balloon grows with
# the ratio). Since every downpayment is already required to be >=
# MIN_DOWNPAYMENT_RATIO (C6), a ratio above (1 - MIN_DOWNPAYMENT_RATIO)
# makes financed_amount negative for EVERY legal downpayment, not just
# some of them - GFV would never be offerable at all for that row. This
# is the real, derived ceiling (not an arbitrary round number): the
# break-even case is exactly the minimum downpayment with zero interest
# financed.
MAX_GFV_RESIDUAL_RATIO = Decimal("1") - MIN_DOWNPAYMENT_RATIO


def minimum_downpayment_for(price):
    """10% of `price`, rounded UP to the cent - ROUND_UP (not this
    codebase's usual ROUND_HALF_UP currency convention) is deliberate: a
    minimum that rounded to-nearest or down could let a downpayment that
    reads as "10%" on screen actually fall fractionally under 10%. e.g.
    10% of RM 200,000.15 is 20,000.015, so the minimum is RM 20,000.02,
    not 20,000.01 or 20,000.02-rounds-to-nearest.
    """
    return (price * MIN_DOWNPAYMENT_RATIO).quantize(_TWO_PLACES, rounding=ROUND_UP)


def minimum_downpayment_message(price):
    minimum = minimum_downpayment_for(price)
    return f"Minimum downpayment is 10% of the vehicle price (RM {minimum:,.2f})."


# QA audit L1: UC003's own alternate-flow copy ("User enters negative
# values or alphabetic characters into numeric budget fields... System
# displays inline red validation error banners: 'Please enter a valid
# positive numerical amount.'") - not DRF's generic "Ensure this value is
# greater than or equal to 0." / "A valid number is required." text.
# Shared by every "positive financial amount" field across comparisons/
# depreciation/scoring (downpayment, monthly_income, existing monthly
# commitments) so the same exact copy appears everywhere one of these is
# invalid, not reworded per-endpoint. Pass as a DecimalField's
# `error_messages=POSITIVE_AMOUNT_ERROR_MESSAGES`.
POSITIVE_AMOUNT_ERROR_MESSAGES = {
    "min_value": "Please enter a valid positive numerical amount.",
    "invalid": "Please enter a valid positive numerical amount.",
}

# Run 2 fix batch 3 (A5): the Max DSR limit is a percentage from 1 to 100,
# wherever it is entered - the Financial Profile (model and serializer), the AI
# Recommendation request, the DSR simulator and a saved scenario's inputs (which
# copies the recommendation's field). One validator pair and one sentence, so the
# range can't drift between them. No "%" in the message: Django formats validator
# messages with %, so "1%" would break it. `dsr_limit_validators()` returns a fresh
# list each call (a field owns its list). Too many digits (e.g. 1000, 99999) also
# gets the range sentence rather than a digit-count one - what the buyer needs to
# know is the allowed range.
MIN_DSR_LIMIT_PERCENT = Decimal("1")
MAX_DSR_LIMIT_PERCENT = Decimal("100")
DSR_RANGE_MESSAGE = "Max DSR limit must be between 1 and 100 percent."
DSR_LIMIT_ERROR_MESSAGES = {
    "invalid": DSR_RANGE_MESSAGE,
    "max_digits": DSR_RANGE_MESSAGE,
    "max_whole_digits": DSR_RANGE_MESSAGE,
}


def dsr_limit_validators():
    return [
        MinValueValidator(MIN_DSR_LIMIT_PERCENT, message=DSR_RANGE_MESSAGE),
        MaxValueValidator(MAX_DSR_LIMIT_PERCENT, message=DSR_RANGE_MESSAGE),
    ]
