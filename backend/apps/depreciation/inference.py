"""F006 - calls the deployed model for a 60-month resale forecast, with a
deterministic straight-line fallback on any failure or timeout (UC006
exception flow 3.1-3.4). Never raises - always returns a usable curve.

Also F012's explainability add-on: explain_resale_prediction() returns a
real SHAP-based per-feature breakdown of one prediction, or None. It
follows the exact same degrade-to-None philosophy as
predict_resale_curve - an explanation is a nice-to-have enhancement, not
core functionality, so it must never raise and never block the TCO
response.

ML batch 1: the deployed model predicts the LOG of the resale price from the
car's attributes (apps/ml/training.py; the feature columns come from
apps/ml/features.py, the one definition shared with training). Only the
curve's SHAPE is used: value at month m = msrp x exp(f_m - f_0), so month 0
is the car's real catalog price by construction and the model's price level
for a "typical" listing never leaks in. _clamp_resale_curve then enforces,
as genuine defense-in-depth (not reliant on the retrain alone), that month 0
never exceeds msrp and the curve never increases month-to-month - see that
function's docstring for the exact rule."""

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from django.conf import settings

from apps.ml.features import BODY_COLUMNS, FEATURE_COLUMNS, body_type_for_segment, car_feature_frame
from apps.ml.log_linear import LogLinearDepreciationModel, age_terms
from apps.ml.models import CURRENT_PREDICTION_TARGET, ProductionModel
from apps.ml.storage import load_model
from apps.vehicles.models import Powertrain

# QA audit L18: every failure path below used to degrade silently - the
# user-facing behavior (fallback curve / None explanation) is correct and
# stays unchanged, but an admin had no way to notice a model file going
# missing/corrupt, or predictions/SHAP consistently timing out, since
# nothing was ever recorded anywhere. logger.exception/.warning here
# don't change what's returned to the caller - purely an observability
# addition.
logger = logging.getLogger(__name__)

from apps.policy.residuals import ResidualConfigError, resolve_residual_ratio

from .formulas import HORIZON_MONTHS, round_currency, straight_line_resale_value

# Run 1 fix batch 5 (R1-4 flag 1): the buyer's "service degraded" wording,
# told apart honestly. DEGRADED_MESSAGE: no compatible model is serving
# forecasts at all (none deployed, or the deployed one predicts the old raw-
# price target, which is deliberately refused). MODEL_FAILED_MESSAGE: a usable
# model is deployed but could not produce this car's forecast (file missing,
# no brand tier, an error or a timeout).
DEGRADED_MESSAGE = (
    "Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast is "
    "switched off until a model passes the accuracy check."
)
MODEL_FAILED_MESSAGE = (
    "Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast could "
    "not be produced for this car just now."
)
# ML batch 1: the training data has no electric cars (and the engine-size
# feature needs a displacement), so a BEV - or any car without an engine cc -
# always gets the fallback curve, whatever model is deployed.
NOT_COVERED_EV_MESSAGE = (
    "Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast does "
    "not cover electric cars yet: the training data has none."
)
# ML batch 2: a body segment with no body type in apps.ml.features (one added
# later) is a lasting gap, not a passing failure, so it says so ("just now"
# stays for real runtime failures).
NOT_COVERED_BODY_MESSAGE = (
    "Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast does "
    "not cover this body type yet."
)


def forecast_is_switched_off():
    """True when no compatible model is serving forecasts: nothing deployed,
    or the deployed model's target isn't the log resale price the forecast
    needs (see _load_production_model)."""
    production = ProductionModel.objects.filter(pk=1).first()
    return (
        production is None
        or not production.model_file_path
        or production.prediction_target != CURRENT_PREDICTION_TARGET
    )


def _fallback_reason():
    return DEGRADED_MESSAGE if forecast_is_switched_off() else MODEL_FAILED_MESSAGE

# QA audit M8: the deserialized estimator is expensive to recreate
# (joblib.load of a ~1.85MB file) and ProductionModel is a genuine
# singleton (pk=1) - there is only ever one currently-deployed model, so a
# single-slot cache keyed by that model's own file path is enough; a
# dict keyed by every path ever seen would just accumulate one stale
# estimator per past deployment, for no benefit. Invalidated by comparing
# the cached path against ProductionModel.model_file_path on every call
# (never a TTL), so a freshly hot-swapped model (H11) is picked up on the
# very next request, never a stale window.
_model_cache = {"path": None, "estimator": None}

# The SHAP explanation's factors: one per numeric feature, plus the six body
# one-hot columns grouped into one "body_type" factor (only one of them is ever
# 1, so they are one fact about the car).
EXPLANATION_FACTORS = ["vehicle_age", "mileage", "brand_code", "engine_litres", "body_type", "recond"]


def _load_production_model():
    """Shared 'load the production model or bail' step for both
    predict_resale_curve and explain_resale_prediction. Returns the
    loaded estimator, or None if nothing is deployed or the file fails
    to load - never raises.

    QA audit M8: a single request (e.g. build_tco_report) calls this
    twice (once for the curve, once for the SHAP explanation) - without
    caching, that's two separate joblib.load() disk reads per request,
    on top of settings.ML_INFERENCE_TIMEOUT_SECONDS already being close to
    the 3s page-load NFR on its own. Cache hit: the model_file_path on the
    production row is unchanged since the last load, so the in-memory
    estimator is reused with no disk I/O at all.
    """
    production = ProductionModel.objects.filter(pk=1).first()
    if production is None or not production.model_file_path:
        return None
    # QA audit C8 correction, ML batch 1: every call site below treats the
    # raw prediction as a LOG resale price on the features.py columns. A
    # model with any other target (raw price, the old value-retention ratio)
    # or a blank one ("unknown, therefore incompatible") would produce
    # nonsense through that maths, so it is never used. This check runs
    # BEFORE the cache lookup below, so an incompatible model is never read
    # into, or served from, the cache either.
    if production.prediction_target != CURRENT_PREDICTION_TARGET:
        return None
    if _model_cache["path"] == production.model_file_path:
        return _model_cache["estimator"]
    try:
        estimator = load_model(production.model_file_path)
    except Exception:
        logger.exception(
            "Failed to load production model file %r (ProductionModel pk=%s).",
            production.model_file_path,
            production.pk,
        )
        return None
    _model_cache["path"] = production.model_file_path
    _model_cache["estimator"] = estimator
    return estimator


def engine_litres_for_cc(engine_capacity_cc):
    """Displacement in litres the way listings write it: cc / 1000 rounded to
    one decimal place, half-up (1,998 cc -> 2.0, 2,393 cc -> 2.4)."""
    litres = (Decimal(engine_capacity_cc) / Decimal(1000)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(litres)


# Run 2 fix batch 3 (A14, X1): where a car's resale curve comes from, as the
# buyer-facing `forecast_source` field says it:
#   ml_model                     the deployed model produced it;
#   estimated_curve_unsupported  the model can't cover THIS car (electric, no
#                                engine size, body type not mapped) - a lasting
#                                fact about the car, nothing is broken;
#   model_unavailable            it could have, but nothing usable is serving (none
#                                deployed, an incompatible one, a load failure,
#                                a brand with no tier, a runtime error or timeout).
FORECAST_SOURCE_ML = "ml_model"
FORECAST_SOURCE_UNSUPPORTED = "estimated_curve_unsupported"
FORECAST_SOURCE_UNAVAILABLE = "model_unavailable"

# Why the model can't cover a car (coverage_gap), and the one extra reason used when no
# model is serving at all (forecast_outlook).
GAP_ELECTRIC_CAR = "electric_car"
GAP_NO_ENGINE_SIZE = "no_engine_size"
GAP_NO_BRAND_TIER = "no_brand_tier"
GAP_BODY_TYPE_NOT_MAPPED = "body_type_not_mapped"
GAP_MODEL_NOT_SERVING = "model_not_serving"
_UNSUPPORTED_GAPS = (GAP_ELECTRIC_CAR, GAP_NO_ENGINE_SIZE, GAP_BODY_TYPE_NOT_MAPPED)
_GAP_MESSAGES = {
    GAP_ELECTRIC_CAR: NOT_COVERED_EV_MESSAGE,
    GAP_NO_ENGINE_SIZE: NOT_COVERED_EV_MESSAGE,
    GAP_BODY_TYPE_NOT_MAPPED: NOT_COVERED_BODY_MESSAGE,
}


def coverage_gap(vehicle):
    """Why the model can't be used for THIS car (a property of the car, not of
    whatever happens to be deployed), or None when it can. The one eligibility
    rule: _resolve_car_features (the forecast itself), forecast_outlook (the
    comparison's GFV note, the TCO's forecast_source) and Vehicle Readiness all
    read it, so they can't disagree. The training data has no electric cars and
    the engine-size feature needs a displacement, so a BEV, or any car without an
    engine cc, is not covered; neither is a brand with no valid tier or a body
    segment with no body type in apps.ml.features. Never guesses a value."""
    if vehicle.powertrain == Powertrain.BEV:
        return GAP_ELECTRIC_CAR
    if vehicle.engine_capacity_cc is None:
        return GAP_NO_ENGINE_SIZE
    if _resolve_brand_tier_code(vehicle) is None:
        return GAP_NO_BRAND_TIER
    if body_type_for_segment(vehicle.body_segment) is None:
        return GAP_BODY_TYPE_NOT_MAPPED
    return None


def forecast_outlook(vehicle):
    """(forecast_source, gap code) for this car right now, WITHOUT running the
    model - the order predict_resale_curve follows: a model that isn't serving
    comes first (everything is then an estimated curve, whatever the car), then
    the car's own coverage. A runtime failure (an error, a timeout) can't be
    foreseen here; the TCO report catches it through forecast_source()."""
    if _load_production_model() is None:
        return FORECAST_SOURCE_UNAVAILABLE, GAP_MODEL_NOT_SERVING
    gap = coverage_gap(vehicle)
    if gap is None:
        return FORECAST_SOURCE_ML, None
    if gap in _UNSUPPORTED_GAPS:
        return FORECAST_SOURCE_UNSUPPORTED, gap
    return FORECAST_SOURCE_UNAVAILABLE, gap


def forecast_source(vehicle, degraded):
    """The `forecast_source` of a curve predict_resale_curve returned (`degraded`
    is its second value): the model's own when it wasn't degraded; otherwise an
    unsupported car is told apart from a model that isn't available, by the same
    eligibility check."""
    if not degraded:
        return FORECAST_SOURCE_ML
    source, _gap = forecast_outlook(vehicle)
    return FORECAST_SOURCE_UNSUPPORTED if source == FORECAST_SOURCE_UNSUPPORTED else FORECAST_SOURCE_UNAVAILABLE


def _resolve_car_features(vehicle):
    """The car's fixed model inputs, or why the model can't be used for it.

    Returns ({"brand_code", "engine_litres", "body_type"}, None), or
    (None, buyer message) when coverage_gap names a gap: an electric car or one
    with no engine cc (NOT_COVERED_EV_MESSAGE), a brand with no valid tier (the
    usual fallback wording), or a body segment with no body type
    (NOT_COVERED_BODY_MESSAGE)."""
    gap = coverage_gap(vehicle)
    if gap == GAP_NO_BRAND_TIER:
        return None, _fallback_reason()
    if gap is not None:
        return None, _GAP_MESSAGES[gap]
    return {
        "brand_code": _resolve_brand_tier_code(vehicle),
        "engine_litres": engine_litres_for_cc(vehicle.engine_capacity_cc),
        "body_type": body_type_for_segment(vehicle.body_segment),
    }, None


# ML batch 2: the model is read at whole years only (0..5 covers the 60-month
# horizon). The data records age in whole years (listing year - model year),
# so a reading at, say, 7 months is not something the model ever learned -
# and a tree would answer it with the same step as month 0 or month 12. The
# months between are interpolated linearly on the log scale (_month_weights).
ANCHOR_YEARS = list(range(HORIZON_MONTHS // 12 + 1))


def _build_feature_rows(annual_mileage_km, car, years=None):
    """The model's input frame (columns apps.ml.features.FEATURE_COLUMNS), one
    row per whole year of age (default 0..5) - apps.ml.features.car_feature_frame.

    'mileage' in the training data is a cumulative odometer reading
    correlated with age (realistic for used-car listings), not an annual
    rate. So the buyer's declared *annual* mileage is converted to an
    estimated cumulative mileage: annual km x age. recond = 0: catalog cars
    are sold new.

    Run 3 fix batch 6: that cumulative figure is capped, age by age, at the
    highest mileage the deployed model's training data has at that age
    (trained_mileage_caps) - never extrapolated beyond what the model has seen.
    """
    return car_feature_frame(
        car, annual_mileage_km, ANCHOR_YEARS if years is None else years, trained_mileage_caps()
    )


# Run 3 fix batch 6: the cap and its plain note (shown only when the cap changed something).
MILEAGE_CAP_NOTE = "The forecast is capped at the mileage the model has seen."
_caps_cache = {"key": None, "caps": None}


def trained_mileage_caps():
    """{age in whole years: the highest total mileage at that age in the deployed
    run's training data} for ages 0..5, or None (no model, no recorded dataset,
    the file can't be read - then nothing is capped). An age with no rows takes
    the cap of the nearest younger age. Cached per dataset file and mtime."""
    import os

    import pandas as pd

    production = ProductionModel.objects.filter(pk=1).select_related("training_run").first()
    run = production.training_run if production is not None else None
    path = getattr(run, "dataset_path", "") or ""
    try:
        key = (path, os.path.getmtime(path))
    except (OSError, TypeError):
        return None
    if _caps_cache["key"] == key:
        return _caps_cache["caps"]
    try:
        frame = pd.read_csv(path, usecols=["vehicle_age", "mileage"])
        by_age = frame.groupby("vehicle_age")["mileage"].max().to_dict()
    except Exception:  # noqa: BLE001 - a cap is a safeguard; never break a forecast over it
        logger.warning("Could not read the training mileage range from %s", path, exc_info=True)
        return None
    caps, last = {}, None
    for year in ANCHOR_YEARS:
        if year in by_age:
            last = float(by_age[year])
        if last is not None:
            caps[year] = last
    _caps_cache.update(key=key, caps=caps)
    return caps


def mileage_cap_applies(annual_mileage_km):
    """True when, at some whole year of the forecast, annual km x age is above the
    training data's highest mileage for that age (so the cap changes the forecast)."""
    caps = trained_mileage_caps()
    if not caps:
        return False
    km = float(annual_mileage_km)
    return any(km * year > caps[year] for year in ANCHOR_YEARS if year in caps)


def _month_weights(month):
    """(year, next year, weight) for month m: y = m // 12, w = (m - 12y) / 12,
    so f(m) = f(y) + w x (f(y+1) - f(y)). Month 60 is year 5 exactly."""
    year = min(month // 12, ANCHOR_YEARS[-1])
    weight = (month - 12 * year) / 12
    return year, min(year + 1, ANCHOR_YEARS[-1]), weight


def monthly_log_prices(yearly_logs):
    """f(m) for months 0..60 from the model's log prices at whole years 0..5."""
    values = []
    for month in range(HORIZON_MONTHS + 1):
        year, next_year, weight = _month_weights(month)
        values.append(yearly_logs[year] + weight * (yearly_logs[next_year] - yearly_logs[year]))
    return values


def _run_model_prediction(model, feature_rows):
    """Isolated so tests can monkeypatch it to simulate a hang or a
    parse/runtime failure without needing an actually slow or broken model."""
    return model.predict(feature_rows)


def mileage_band_for_km(annual_mileage_km):
    """The policy.MileageBand an annual mileage falls in - "up to and including"
    each band's limit, from the one band definition (apps.policy.mileage, Run 3
    fix batch 6). Every band's representative km falls inside its own band."""
    from apps.policy.mileage import band_for_km

    return band_for_km(annual_mileage_km)


# Month 0 retains the whole price; months 12..60 are the GFV residuals.
_FALLBACK_ANCHOR_MONTHS = (12, 24, 36, 48, 60)


def _fallback_curve(vehicle, annual_mileage_km):
    """Estimated depreciation curve used when no trained model can answer.

    Anchored to the SAME residuals GFV uses (apps.policy.residuals): month 0
    = 100% of MSRP, months 12/24/36/48/60 = resolve_residual_ratio(vehicle,
    month, band), and every month between is the straight-line interpolation
    of the retained RATIO between its neighbouring anchors - so the curve is
    front-loaded (it falls faster early), month 0 equals MSRP, and the
    month-36/48/60 values equal the GFV residual for the same car, so TCO
    and GFV agree. A running minimum keeps it non-increasing even if an
    admin override makes an anchor rise.

    Last resort only: if no residual can be resolved at all (the baseline
    table has been emptied), the old straight line is used rather than
    blocking the comparison flow.
    """
    band = mileage_band_for_km(annual_mileage_km)
    try:
        anchors = [(0, Decimal(1))] + [
            (month, resolve_residual_ratio(vehicle, month, band).ratio) for month in _FALLBACK_ANCHOR_MONTHS
        ]
    except ResidualConfigError:
        logger.exception("_fallback_curve: no residual baseline; using the straight-line formula.")
        return [straight_line_resale_value(vehicle.msrp, month) for month in range(HORIZON_MONTHS + 1)]

    values = []
    ceiling = Decimal(1)
    for month in range(HORIZON_MONTHS + 1):
        for (lo_month, lo_ratio), (hi_month, hi_ratio) in zip(anchors, anchors[1:]):
            if month <= hi_month:
                ratio = lo_ratio + (hi_ratio - lo_ratio) * Decimal(month - lo_month) / Decimal(hi_month - lo_month)
                break
        ceiling = min(ratio, ceiling)
        values.append(round_currency(vehicle.msrp * ceiling))
    return values


def _clamp_resale_curve(raw_values, msrp):
    """QA audit C8: genuine defense-in-depth against the exact failure the
    audit named - "nothing checks the output" - independent of how well
    any given retrain goes, for any model that's ever deployed, not just
    the one deployed today.

    Exact rule: value[0] = min(raw_values[0], msrp); value[month] =
    min(raw_values[month], value[month - 1], msrp) for month >= 1 - i.e.
    each month is clamped down to whichever is smallest of (a) what the
    model actually predicted for that month, (b) the previous month's
    ALREADY-clamped value, and (c) msrp itself. (b) is what guarantees
    non-increasing: a later month can never clamp-recover above an
    earlier month's clamped value, even if the model's own raw sequence
    briefly rises. (c) is the ceiling: month 0 - and therefore every later
    month, transitively, via the running min - can never exceed msrp.
    """
    clamped = []
    ceiling = msrp
    for raw_value in raw_values:
        ceiling = min(raw_value, ceiling)
        clamped.append(ceiling)
    return clamped


def _resolve_brand_tier_code(vehicle):
    """The model's brand_code feature is a data-driven 1-5 price tier
    (apps/ml/data/README_real_data.md's "Brand -> tier table"), stored on
    Brand.tier_code - NOT Django's own auto-increment vehicle.brand_id,
    which has no relationship whatsoever to the trained tier scheme.

    Returns None (never raises) when the brand's tier_code is blank or
    isn't a parseable, finite number - e.g. a freshly admin-added brand
    that isn't in the real 25-brand table - so callers can degrade the
    same way they already do for "no model deployed", rather than
    feeding the model a meaningless/invented value. QA audit M15:
    float("nan") parses without raising, so a "nan" tier_code (now
    prevented at the source by Brand.tier_code's own choices constraint,
    but checked here too as defense in depth - e.g. against a row
    written before that constraint existed, or any other bypass) used to
    silently reach the model as an actual NaN feature value and predict
    anyway, never setting the degraded flag.
    """
    try:
        value = float(vehicle.brand.tier_code)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def predict_resale_curve(*, vehicle, annual_mileage_km):
    """Returns (values, degraded, degraded_reason).

    `values` is a list of 61 Decimal resale-value predictions for months
    0..60. Falls back to _fallback_curve (the estimated curve anchored to
    the GFV residuals - see its docstring) if: no compatible model is
    deployed, the model file fails to load, the car is electric or has no
    engine cc, its brand has no valid tier_code, its body segment has no body
    type (see _resolve_car_features), or prediction raises or exceeds
    settings.ML_INFERENCE_TIMEOUT_SECONDS.

    ML batch 1/2: the model predicts the log resale price f at whole years
    0..5 (ANCHOR_YEARS - the data records age in whole years); month m uses f
    interpolated linearly between its two whole years (monthly_log_prices).
    Only the shape is used - value_m = msrp x exp(f(m) - f(0)) - so month 0 is
    exactly the car's catalog price. The log-linear model is called with no
    model key (its car-model level would cancel anyway). The sequence then
    goes through _clamp_resale_curve as a sanity ceiling/monotonicity net
    independent of how well the retrain went, and is rounded to money once.
    """
    model = _load_production_model()
    if model is None:
        return _fallback_curve(vehicle, annual_mileage_km), True, _fallback_reason()

    car, reason = _resolve_car_features(vehicle)
    if car is None:
        return _fallback_curve(vehicle, annual_mileage_km), True, reason

    feature_rows = _build_feature_rows(annual_mileage_km, car)
    timeout_seconds = settings.ML_INFERENCE_TIMEOUT_SECONDS

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_run_model_prediction, model, feature_rows)
    try:
        raw_predictions = future.result(timeout=timeout_seconds)
        yearly_logs = np.asarray(raw_predictions, dtype=float).reshape(-1)
        if len(yearly_logs) != len(ANCHOR_YEARS) or not np.isfinite(yearly_logs).all():
            raise ValueError("the model returned an unusable prediction")
    except Exception:
        # Covers FutureTimeoutError and any exception the prediction call
        # itself raises. Don't wait for a hung/slow prediction to finish
        # before falling back - shutdown(wait=False) lets it die in the background.
        logger.exception("predict_resale_curve: model prediction failed or timed out for vehicle id=%s.", vehicle.pk)
        executor.shutdown(wait=False)
        return _fallback_curve(vehicle, annual_mileage_km), True, _fallback_reason()
    executor.shutdown(wait=False)

    log_prices = monthly_log_prices(yearly_logs)
    msrp = float(vehicle.msrp)
    raw_rm_values = [msrp * math.exp(f - log_prices[0]) for f in log_prices]
    clamped_rm_values = _clamp_resale_curve(raw_rm_values, msrp)
    values = [round_currency(Decimal(str(v))) for v in clamped_rm_values]
    return values, False, None


def _run_shap_explanation(model, feature_rows):
    """Isolated so tests can monkeypatch it to simulate a hang or a
    computation failure, same pattern as _run_model_prediction.

    shap is imported lazily here, not at module level: if it's ever
    missing/broken in some environment, that must degrade this one
    enhancement to None (via the caller's except Exception), not break
    every import of this module (and therefore the whole TCO endpoint).
    """
    import shap

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(feature_rows)
    return explainer.expected_value, shap_values


def _group_feature_deltas(delta_by_column):
    """Per-column log-scale deltas -> the explanation's factors: the six body
    one-hots are one "body_type" factor; every other feature is its own."""
    return {
        factor: (
            sum(delta_by_column.get(column, 0.0) for column in BODY_COLUMNS)
            if factor == "body_type"
            else delta_by_column.get(factor, 0.0)
        )
        for factor in EXPLANATION_FACTORS
    }


def _log_linear_deltas(model, feature_rows, weight):
    """Exact deltas for the log-linear model: for every design column j,
    coef_j x (d_j(month) - d_j(year 0)), d(month) interpolated between its two
    whole years with the curve's own weight. age, age² and age x tier are the
    age effect ("vehicle_age"); km/10,000 is "mileage"; every other column is
    the same in both rows, so its delta is 0. No model key is passed."""
    design = model.design(feature_rows)
    d0, dy, dnext = (design.iloc[i].to_numpy(dtype=float) for i in range(3))
    d_month = dy + weight * (dnext - dy)
    column_deltas = dict(zip(design.columns, model.ridge.coef_ * (d_month - d0)))
    grouped = {"vehicle_age": sum(column_deltas[c] for c in age_terms()), "mileage": column_deltas["km_10k"]}
    for column, delta in column_deltas.items():
        if column in age_terms() or column == "km_10k":
            continue
        grouped[column] = grouped.get(column, 0.0) + delta
    return _group_feature_deltas(grouped)


def explain_resale_prediction(*, vehicle, annual_mileage_km, month):
    """Real per-feature contributions for the deployed model's predicted
    resale value at `month`. An enhancement, never core functionality - same
    degrade-to-None philosophy as predict_resale_curve: no compatible model, a
    car the model doesn't cover, a load failure, a SHAP computation error, or
    a timeout all mean None, never an exception, never a blocked TCO response.

    Returns {"base_value": float, "contributions": {factor: float, ...},
    "predicted_value": float} with base_value + sum(contributions) ==
    predicted_value (tested for Random Forest, Gradient Boosting and the
    log-linear model in apps/depreciation/tests/test_explanation.py).

    The explanation is of the curve's own quantity, msrp x exp(f(m) - f(0)),
    with f(m) interpolated between the month's two whole years (ML batch 2):
    - trees: SHAP values phi at year 0 and at the month's two whole years
      (TreeExplainer, log scale); phi(month) = phi(y) + w x (phi(y+1) - phi(y));
      delta_i = phi_i(month) - phi_i(year 0). The explainer's base value is
      the same for every row and cancels, so sum(delta) = f(m) - f(0);
    - log-linear: exact, per design column (_log_linear_deltas);
    - the six body one-hot columns are grouped into one "body_type" factor;
    - base_value = msrp (the new price); predicted_value = msrp x
      exp(sum(delta)), so the parts add up exactly; the RM change
      (predicted_value - msrp) is shared among the factors in proportion to
      their delta. When |sum(delta)| < 1e-12 every contribution is 0.
    "Worked out on a log scale and shared in proportion" - the card says so.

    Separately flagged: predicted_value is the model's unclamped output - it
    does NOT re-apply predict_resale_curve's _clamp_resale_curve net
    (a min() would break the additivity). The two only disagree for a
    month where the raw curve rose and was clamped.
    """
    model = _load_production_model()
    if model is None:
        return None

    car, _reason = _resolve_car_features(vehicle)
    if car is None:
        return None

    year, next_year, weight = _month_weights(month)
    feature_rows = _build_feature_rows(annual_mileage_km, car, years=[0, year, next_year])

    if isinstance(model, LogLinearDepreciationModel):
        try:
            deltas = _log_linear_deltas(model, feature_rows, weight)
        except Exception:
            logger.exception("explain_resale_prediction: log-linear explanation failed for vehicle id=%s.", vehicle.pk)
            return None
    else:
        timeout_seconds = settings.ML_INFERENCE_TIMEOUT_SECONDS
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_run_shap_explanation, model, feature_rows)
        try:
            _expected_value, shap_values = future.result(timeout=timeout_seconds)
        except Exception:
            logger.exception(
                "explain_resale_prediction: SHAP computation failed or timed out for vehicle id=%s.", vehicle.pk
            )
            executor.shutdown(wait=False)
            return None
        executor.shutdown(wait=False)
        try:
            phi = np.asarray(shap_values, dtype=float).reshape(3, len(FEATURE_COLUMNS))
            phi_month = phi[1] + weight * (phi[2] - phi[1])
            deltas = _group_feature_deltas(dict(zip(FEATURE_COLUMNS, phi_month - phi[0])))
        except Exception:
            logger.exception(
                "explain_resale_prediction: could not reshape SHAP output for vehicle id=%s.", vehicle.pk
            )
            return None

    try:
        log_change = sum(deltas.values())
        msrp = float(vehicle.msrp)
        if abs(log_change) < 1e-12:
            predicted_value = msrp
            contributions = {factor: 0.0 for factor in EXPLANATION_FACTORS}
        else:
            predicted_value = msrp * math.exp(log_change)
            change = predicted_value - msrp
            contributions = {factor: float(change * delta / log_change) for factor, delta in deltas.items()}
        if not all(math.isfinite(v) for v in (predicted_value, *contributions.values())):
            raise ValueError("non-finite explanation")
    except Exception:
        logger.exception("explain_resale_prediction: non-finite explanation for vehicle id=%s.", vehicle.pk)
        return None

    return {
        "base_value": msrp,
        "contributions": {factor: float(value) for factor, value in contributions.items()},
        "predicted_value": float(predicted_value),
    }
