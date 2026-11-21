"""Run 2 fix batch 2 (E3, C6, E5): plain-English notes that say what the two
resale figures on the TCO tab ARE. Words only - every number in them is one the
report already carries (the comparison's GFV block, the forecast, the deployed
run's own metric); nothing here changes a figure.

- resale_views_note: why the lender's GFV residual and the predicted market
  value differ (and that Subscription fees use the residual).
- resale_forecast_note: what the predicted curve is (a machine-learning
  estimate for the car's brand tier, age and mileage) and how far off it
  typically is.

Both are built here, on the server, so the screen, the saved snapshot and the
PDF show the same sentence, and a car added later gets it automatically. Both
are None when they do not apply; the client renders a note only when it is a
non-empty string, so an older saved snapshot (no such key) renders as before.
"""

from decimal import ROUND_HALF_UP, Decimal

from apps.ml.models import CURRENT_PREDICTION_TARGET, ModelType, ProductionModel
from apps.ml.serializers import typical_error_percent

# GFV is offered for 12 to 60 months (apps.policy.residuals); outside that there
# is no residual to compare the prediction with.
RESALE_VIEWS_MIN_TENURE = 12
RESALE_VIEWS_MAX_TENURE = 60

_ONE_PLACE = Decimal("0.1")


def _trimmed_percent(ratio):
    """Decimal('0.3500') -> '35', Decimal('0.4125') -> '41.25': a ratio as the
    percentage the GFV card shows, without trailing zeros."""
    return f"{(Decimal(ratio) * 100).normalize():f}"


def build_resale_views_note(*, tenure_months, gfv, predicted_value, price, degraded):
    """The GFV-versus-prediction explanation, or None.

    `gfv` is the comparison's GFV block (balloon_payment, residual_value_ratio),
    None when GFV is not available for this request; `predicted_value` the
    forecast's value at month `tenure_months`. None too when the curve is the
    estimated fallback: that curve is anchored to the same GFV residuals, so the
    two figures are equal by construction and there is nothing to explain.
    """
    if gfv is None or degraded or predicted_value is None:
        return None
    if not RESALE_VIEWS_MIN_TENURE <= tenure_months <= RESALE_VIEWS_MAX_TENURE:
        return None
    price = Decimal(price)
    if price <= 0:
        return None
    predicted_pct = (Decimal(predicted_value) / price * 100).quantize(_ONE_PLACE, rounding=ROUND_HALF_UP)
    return (
        f"At month {tenure_months}, the lender's GFV residual for this car is RM {gfv['balloon_payment']:,.2f} "
        f"({_trimmed_percent(gfv['residual_value_ratio'])}% of the price), while the predicted market value is "
        f"RM {Decimal(predicted_value):,.2f} ({predicted_pct}% of the price). The GFV figure is a guaranteed "
        "buy-back price that lenders set conservatively; the prediction is the expected market price, so the two "
        "are different things and can differ. Subscription fees are priced on the same conservative residual as GFV."
    )


def build_resale_forecast_note(*, degraded):
    """What the predicted curve is, or None when the curve is the estimated
    fallback (its own message already says so - never a second one).

    The typical-error sentence reads the deployed run's own metric through the
    same helper and rounding the ML Model Management page uses
    (apps.ml.serializers.typical_error_percent); it is dropped when that metric
    is not available. The log-linear model's curve depends on brand tier, age
    and mileage only (engine size and body type shift the price level, which
    cancels when the curve is scaled to the car's own price), so cars in a tier
    share one shape - said only for that model. A tree model uses more of the
    car, so it gets the plainer sentence."""
    if degraded:
        return None
    production = ProductionModel.objects.filter(pk=1).first()
    if production is None or production.prediction_target != CURRENT_PREDICTION_TARGET:
        return None
    if production.model_type == ModelType.LOG_LINEAR:
        note = (
            "Predicted resale value is a machine-learning estimate for this car's brand tier, age and mileage, "
            "scaled to this car's own price. Cars in the same brand tier share the same shape."
        )
    else:
        note = (
            "Predicted resale value is a machine-learning estimate from this car's brand tier, age, mileage, "
            "engine size and body type, scaled to this car's own price."
        )
    error_percent = typical_error_percent(production.mae) if production.mae is not None else None
    if error_percent is not None:
        note += f" Typical error is about {error_percent}% of the price."
    return note
