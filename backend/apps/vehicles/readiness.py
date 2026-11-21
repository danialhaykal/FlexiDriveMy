"""Vehicle readiness (audit batch 6): after adding any car or brand, can the app
fully price it?

Every check CALLS THE SAME CODE the screens use, never a hand-kept copy of its
rules, so a rule added to one of those code paths shows up here automatically:

  specs              powertrain_spec_errors (the new-vehicle contract)
  price              the vehicle's own msrp
  running costs      apps.policy.operating_costs.estimate_operating_costs
  interest rate      apps.comparisons.services.get_active_interest_rate
  residuals (GFV)    apps.policy.residuals.resolve_residual_ratio, every
                     tenure from the minimum to the GFV horizon in 12-month
                     steps, at every mileage band
  subscription       apps.policy.subscription_pricing.resolve_subscription_fee
                     at every tenure it is offered for
  min. downpayment   apps.common.constants.minimum_downpayment_for
  contract rule      apps.policy.contract_rules.get_contract_rules
  road-tax class     a warning (never blocking) for a crossover or a class
                     set differently from the body type's default
  resale forecast    informational: the machine-learning model or the estimated
                     curve, and why (apps.depreciation.inference.forecast_outlook)
  model year, photo  recommended only: a warning, never blocking

A check is "ok", "missing" (the app cannot fully price this car), "warning"
(worth fixing, never blocks) or "info" (just says how something is done, never
blocks and is not counted). A vehicle is "ready" unless any check is missing.
"""

from decimal import ROUND_HALF_UP, Decimal

from apps.common.constants import MIN_TENURE_MONTHS, minimum_downpayment_for
from apps.comparisons.services import ComparisonConfigError, get_active_interest_rate
from apps.depreciation.formulas import HORIZON_MONTHS
from apps.depreciation.inference import (
    FORECAST_SOURCE_ML,
    GAP_BODY_TYPE_NOT_MAPPED,
    GAP_ELECTRIC_CAR,
    GAP_MODEL_NOT_SERVING,
    GAP_NO_BRAND_TIER,
    GAP_NO_ENGINE_SIZE,
    forecast_outlook,
)
from apps.policy.contract_rules import get_contract_rules
from apps.policy.models import MileageBand
from apps.policy.operating_costs import OperatingCostConfigError, estimate_operating_costs
from apps.policy.residuals import SOURCE_OVERRIDE, ResidualConfigError, resolve_residual_ratio, residual_tables_snapshot
from apps.policy.subscription_pricing import (
    SubscriptionConfigError,
    get_active_policy,
    offered_tenures,
    resolve_subscription_fee,
)

from .models import BodySegment, Powertrain, VehicleModel, powertrain_spec_errors

OK, MISSING, WARNING, INFO = "ok", "missing", "warning", "info"
READY, NEEDS_ATTENTION = "ready", "needs_attention"

# The GFV tenures a car should be priceable for: from the shortest allowed
# tenure up to the GFV horizon, in 12-month steps (the residual baseline's own
# step).
GFV_TENURES = range(MIN_TENURE_MONTHS, HORIZON_MONTHS + 1, 12)


def _check(key, label, status, detail):
    return {"key": key, "label": label, "status": status, "detail": detail}


def _band_name(band):
    return band.replace("_", " ")


def _specs(vehicle):
    errors = powertrain_spec_errors(vehicle.powertrain, vehicle.engine_capacity_cc)
    if errors:
        return _check("specs", "Specs complete", MISSING, " ".join(errors.values()))
    return _check("specs", "Specs complete", OK, "Powertrain and engine details are filled in.")


def _price(vehicle):
    if vehicle.msrp is not None and vehicle.msrp > 0:
        return _check("price", "Price set", OK, f"RM {vehicle.msrp:,.2f}.")
    return _check("price", "Price set", MISSING, "The price must be more than RM 0.")


def _running_costs(vehicle):
    try:
        costs = estimate_operating_costs(vehicle)
    except OperatingCostConfigError as exc:
        return _check("running_costs", "Running costs", MISSING, str(exc))
    return _check(
        "running_costs", "Running costs", OK,
        f"Road tax RM {costs.road_tax_annual:,.2f}, insurance RM {costs.insurance_annual:,.2f} and "
        f"maintenance RM {costs.maintenance_annual:,.2f} a year.",
    )


def _interest_rate(vehicle):
    try:
        rate = get_active_interest_rate(vehicle.brand)
    except ComparisonConfigError as exc:
        # The technical reason (which brand, which rate), not the buyer's wording.
        return _check("interest_rate", "Interest rate", MISSING, exc.admin_message)
    # Run 3 fix batch 5 (F-18): 2 dp, as the buyer screens show it ("2.80%", not "2.8000%").
    shown = Decimal(rate.rate_percent).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return _check("interest_rate", "Interest rate", OK, f"{vehicle.brand.name} has a flat rate of {shown}% a year.")


def _residuals(vehicle):
    failing, overrides, total = [], 0, 0
    for tenure in GFV_TENURES:
        for band in MileageBand.values:
            total += 1
            try:
                result = resolve_residual_ratio(vehicle, tenure, band)
            except ResidualConfigError:
                failing.append(f"{tenure} months / {_band_name(band)}")
                continue
            overrides += result.source == SOURCE_OVERRIDE
    if failing:
        return _check(
            "residuals", "Residuals (GFV)", MISSING,
            "No residual can be worked out for: " + "; ".join(failing) + ".",
        )
    source = f"{overrides} from admin overrides, the rest estimated" if overrides else "all estimated"
    return _check(
        "residuals", "Residuals (GFV)", OK,
        f"Resolved for all {total} tenure and mileage-band combinations ({source}).",
    )


def _subscription(vehicle):
    try:
        tenures = offered_tenures(get_active_policy())
    except SubscriptionConfigError as exc:
        return _check("subscription", "Subscription", MISSING, str(exc))
    if not tenures:
        return _check("subscription", "Subscription", MISSING, "Subscription isn't offered for any tenure right now.")
    sources = set()
    for tenure in tenures:
        try:
            quote = resolve_subscription_fee(vehicle, tenure, MileageBand.STANDARD)
        except SubscriptionConfigError as exc:
            return _check("subscription", "Subscription", MISSING, f"At {tenure} months: {exc}")
        sources.add(quote.source)
    months = ", ".join(str(t) for t in tenures)
    how = "provider quote" if sources == {"quote"} else "estimated" if sources == {"estimate"} else "provider quote and estimate"
    return _check("subscription", "Subscription", OK, f"Priced at {months} months ({how}).")


def _minimum_downpayment(vehicle):
    if vehicle.msrp is None or vehicle.msrp <= 0:
        return _check("minimum_downpayment", "Minimum downpayment", MISSING, "It can't be worked out without a price.")
    minimum = minimum_downpayment_for(Decimal(vehicle.msrp))
    return _check("minimum_downpayment", "Minimum downpayment", OK, f"RM {minimum:,.2f} (10% of the price).")


def _contract_rule(vehicle):
    brand_rule, default_rule = get_contract_rules(vehicle.brand)
    if brand_rule is not None:
        return _check("contract_rule", "Contract penalty rule", OK, f"{vehicle.brand.name} has its own rule.")
    if default_rule is not None:
        return _check("contract_rule", "Contract penalty rule", OK, "Uses the default rule.")
    return _check(
        "contract_rule", "Contract penalty rule", MISSING,
        f"{vehicle.brand.name} has no rule and there is no default rule.",
    )


ROAD_TAX_CLASS_CHECK_MESSAGE = "Check road-tax class on the VOC"


def _road_tax_class(vehicle):
    """Run 1 fix batch 3: an amber note, never a blocker. A crossover is
    registered either way, and a class set differently from the body type's
    default is worth confirming against the registration card (VOC)."""
    if vehicle.powertrain == Powertrain.BEV:
        return _check("road_tax_class", "Road-tax class", OK, "Electric: road tax is by motor kW, not by class.")
    label = vehicle.get_road_tax_class_display() if vehicle.road_tax_class else "not set"
    if vehicle.body_segment == BodySegment.CROSSOVER:
        return _check(
            "road_tax_class", "Road-tax class", WARNING,
            f"{ROAD_TAX_CLASS_CHECK_MESSAGE}: crossovers are registered as either class (set to {label}).",
        )
    if not vehicle.road_tax_class_is_default:
        return _check(
            "road_tax_class", "Road-tax class", WARNING,
            f"{ROAD_TAX_CLASS_CHECK_MESSAGE}: set to {label}, which is not usual for body type "
            f"{vehicle.get_body_segment_display()}.",
        )
    return _check("road_tax_class", "Road-tax class", OK, f"{label} (usual for {vehicle.get_body_segment_display()}).")


# Run 2 fix batch 3 (A14, X1): which resale forecast this car gets - the machine-
# learning model or the estimated curve, and why. INFORMATIONAL: it is never
# "missing" or "warning", so it can't make a car "needs attention" (an electric car
# using the estimated curve is expected, nothing is broken). It asks the same
# eligibility check the TCO tab and the GFV note use (inference.forecast_outlook).
_FORECAST_REASONS = {
    GAP_ELECTRIC_CAR: (
        "electric car",
        "The training data has no electric cars, so this car uses the estimated curve from planning assumptions.",
    ),
    GAP_NO_ENGINE_SIZE: (
        "no engine size",
        "The model needs the engine size (cc), so this car uses the estimated curve from planning assumptions.",
    ),
    GAP_BODY_TYPE_NOT_MAPPED: (
        "body type not mapped",
        "This body type has no matching body type in the model yet, so the car uses the estimated curve.",
    ),
    GAP_NO_BRAND_TIER: (
        "brand price tier not set",
        "The brand has no valid price tier, which the model needs, so the car uses the estimated curve.",
    ),
    GAP_MODEL_NOT_SERVING: (
        "model not serving",
        "No compatible model is deployed (or it could not be loaded), so every car uses the estimated curve.",
    ),
}


def _resale_forecast(vehicle):
    source, gap = forecast_outlook(vehicle)
    if source == FORECAST_SOURCE_ML:
        return _check(
            "resale_forecast", "Resale forecast: machine-learning model", INFO,
            "The deployed model produces this car's resale curve.",
        )
    reason, detail = _FORECAST_REASONS[gap]
    return _check("resale_forecast", f"Resale forecast: estimated curve ({reason})", INFO, detail)


def _model_year(vehicle):
    if vehicle.model_year:
        return _check("model_year", "Model year", OK, str(vehicle.model_year))
    return _check("model_year", "Model year", WARNING, "No model year recorded (recommended, not required).")


def _photo(vehicle):
    if vehicle.thumbnail_url:
        return _check("photo", "Photo", OK, "A photo is set.")
    return _check("photo", "Photo", WARNING, "No photo - a placeholder is shown (recommended, not required).")


CHECKS = [
    _specs, _price, _running_costs, _road_tax_class, _interest_rate, _residuals, _subscription,
    _minimum_downpayment, _contract_rule, _resale_forecast, _model_year, _photo,
]


def vehicle_readiness(vehicle):
    """One vehicle's checks and overall status."""
    checks = [check(vehicle) for check in CHECKS]
    missing = sum(c["status"] == MISSING for c in checks)
    warnings = sum(c["status"] == WARNING for c in checks)
    return {
        "vehicle_id": vehicle.pk,
        "label": f"{vehicle.brand.name} {vehicle.name} {vehicle.trim}".strip(),
        "brand_name": vehicle.brand.name,
        "status": NEEDS_ATTENTION if missing else READY,
        "missing_count": missing,
        "warning_count": warnings,
        "checks": checks,
    }


def active_vehicles():
    return VehicleModel.objects.visible().select_related("brand").order_by("brand__name", "name", "trim")


def readiness_report():
    # FX-3 (X14): the residual tables are read once for the whole report (see
    # residual_tables_snapshot) - same checks, statuses and messages.
    with residual_tables_snapshot():
        return [vehicle_readiness(vehicle) for vehicle in active_vehicles()]
