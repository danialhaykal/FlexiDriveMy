"""Run 2 fix batch 3 (ML-3, A11, G6): the 'Why this predicted value?' figures as
the buyer reads them - whole sen, in one fixed order, adding up exactly.

inference.explain_resale_prediction returns the model's raw floats
(base_value + sum(contributions) == predicted_value to float precision). A card
that shows each of those rounded to 2 dp can be a sen or two out: six rounded
parts need not add up to the rounded whole. round_explanation() rounds once, in
Python (the only layer that does money arithmetic), and puts the leftover sen on
a factor so that, in sen,

    base_value + sum(contributions) == predicted_value        (exactly)

predicted_value is the same half-up rounding the TCO curve applies to its month
(inference.predict_resale_curve), so it equals the curve's value at that month to
the sen. The factors are returned in EXPLANATION_FACTORS order (Age, Mileage,
Brand tier, Engine size, Body type, Recond import), which the screen and the PDF
both follow.
"""

from decimal import Decimal

from .formulas import round_currency
from .inference import EXPLANATION_FACTORS


def _sen(value):
    return round_currency(Decimal(str(value)))


def round_explanation(explanation):
    """`explanation` (the dict explain_resale_prediction returns, or None) with
    every amount at 2 dp and the parts summing exactly. The leftover sen (the
    difference between the rounded total and the sum of the rounded parts) goes on
    the LAST factor that is not 0.00 in the fixed order; when every factor rounds
    to 0.00 it goes on the factor that moved the value most. None stays None."""
    if not explanation:
        return explanation

    base = _sen(explanation["base_value"])
    predicted = _sen(explanation["predicted_value"])
    raw = explanation["contributions"]
    parts = {factor: _sen(raw[factor]) for factor in EXPLANATION_FACTORS if factor in raw}

    leftover = predicted - base - sum(parts.values(), Decimal("0"))
    if leftover:
        non_zero = [factor for factor, value in parts.items() if value != 0]
        if non_zero:
            target = non_zero[-1]
        else:
            # Ties go to the later factor in the fixed order.
            target = max(parts, key=lambda factor: (abs(raw[factor]), EXPLANATION_FACTORS.index(factor)))
        parts[target] += leftover

    return {
        "base_value": float(base),
        "contributions": {factor: float(value) for factor, value in parts.items()},
        "predicted_value": float(predicted),
    }
