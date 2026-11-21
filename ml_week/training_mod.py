"""F012 - CSV validation and RandomForest/GradientBoosting training (UC012).

Framework-free where it matters: validate_columns/pick_best_and_deploy are
plain functions so the R^2 deployment gate and the malformed-CSV alt flow
can be tested without touching Django, Celery, or a real dataset.

NOTE on the feature set: the project spec's ML section specifies a 5-feature
vector [Vehicle Age, Annual Mileage, MSRP, Brand Tier Code, Engine
Capacity/kW]. As of Sprint 9, the model trains on 4 of those 5
(vehicle_age, mileage, brand_code, msrp_proxy - see
apps/ml/data/README_real_data.md for exactly how msrp_proxy is derived
from real_historical_pricing.csv) to predict resale_price. Engine
capacity is still a deliberate, flagged omission: the raw dataset only
gives engine size as displacement in liters from listing text, which
isn't a clean conversion to VehicleModel.engine_capacity_kw's power
output in kW - adding it needs a real schema decision (probably a new
displacement field on VehicleModel), not this sprint's scope.

QA audit C8: the model is trained and evaluated against a VALUE-RETENTION
RATIO (resale_price / msrp_proxy), not raw resale_price. Root cause:
msrp_proxy is a USED-car-market proxy (see README_real_data.md - it's
derived from other listings' resale prices, never a true original
showroom price), but apps/depreciation/inference.py substitutes the
vehicle's real, catalog-stored NEW-car msrp into that same feature slot
at inference time. Training on an absolute RM target taught the model
"resale_price as a function of msrp_proxy-scale inputs"; fed real-msrp-
scale inputs (a different, generally higher scale) at inference, a
RandomForest/GradientBoosting has no choice but to extrapolate - which is
exactly how predictions above the car's own price and non-monotonic
"value rising with age" curves arose. A ratio target is scale-invariant
with respect to that proxy-vs-real mismatch: whatever scale `msrp` is on,
"what fraction of it does this car retain" is the same learned quantity,
so R^2/MAE below describe RETENTION-FRACTION accuracy, not RM accuracy -
every docstring/label touching these numbers says so explicitly, not
just this one.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GridSearchCV, train_test_split

class ModelType:
    RANDOM_FOREST='random_forest'; GRADIENT_BOOSTING='gradient_boosting'
R2_DEPLOYMENT_THRESHOLD=0.80

REQUIRED_COLUMNS = {"vehicle_age", "mileage", "resale_price", "brand_code", "msrp_proxy"}
FEATURE_COLUMNS = ["vehicle_age", "mileage", "brand_code", "msrp_proxy"]
TARGET_COLUMN = "resale_price"
# QA audit C8: the real fit/eval target - resale_price / msrp_proxy,
# clipped to 1.0 (see RATIO_CLIP_MAX below). Kept as a separate name from
# TARGET_COLUMN (resale_price stays a REQUIRED_COLUMNS name, the raw input
# the ratio is computed from) rather than overloading one column for two
# meanings.
RATIO_TARGET_COLUMN = "value_retention_ratio"

# msrp_proxy is an approximation (see README_real_data.md), not a true
# ceiling, so a genuine listing can have resale_price > msrp_proxy without
# anything being wrong with that row - 129 of the real 888-row dataset's
# rows (14.5%) do, up to ~6x in the most extreme case. Excluding all 129
# would throw away real signal from otherwise-valid rows (and skew the
# brand mix, since they're not evenly distributed). Clipping the TARGET at
# 1.0 is the chosen fix instead: a used car cannot genuinely retain more
# than 100% of its original value, so a ratio above 1.0 is necessarily an
# artifact of msrp_proxy being an underestimate for that specific row, not
# a fact about the car - clipping corrects the proxy's error without
# discarding the row's otherwise-valid age/mileage/brand signal. This is
# also the same ceiling the inference-time sanity clamp enforces (see
# apps/depreciation/inference.py), so training and inference agree on what
# "100% retained" means.
RATIO_CLIP_MAX = 1.0

# Small, defensible search grids - not exhaustive, but a real search
# rather than one hand-picked guess. 888 real rows (see
# apps/ml/data/README_real_data.md) is small enough that GridSearchCV
# over these stays fast even with cv=3.
RF_PARAM_GRID = {"n_estimators": [100, 200, 300], "max_depth": [None, 8, 16]}
GB_PARAM_GRID = {"n_estimators": [100, 200], "learning_rate": [0.05, 0.1], "max_depth": [2, 3, 4]}
DEFAULT_CV = 3


class MalformedDatasetError(Exception):
    """UC012 alt flow: missing required columns, unparseable/invalid rows,
    or too few rows to train. Raised before any training is attempted; the
    caller must leave the currently deployed production model untouched."""


# QA audit M10: a defensible floor, not an arbitrary one. train_and_evaluate
# does an 80/20 train_test_split followed by a 3-fold GridSearchCV on the
# training split - below this many rows, either the test split or a CV
# fold can end up with only a handful of rows (or, at the extreme, raise
# from inside sklearn outright), making both the reported R^2/MAE and the
# search itself unreliable rather than just "less accurate". 30 rows keeps
# >=24 rows in the training split and >=8 rows per CV fold - still a small
# sample, but a defensible floor rather than an exact science.
MIN_TRAINING_ROWS = 30

# QA audit M10: build_real_ml_dataset.py's own sanity filter (resale_price
# > 0, msrp_proxy > 0, mileage >= 0, vehicle_age >= 0) applied here too, so
# the SAME invalid values that are rejected at one-time dataset-build time
# are also rejected at live-upload time - this path previously had no such
# check at all, so a negative/zero/infinite value sailed through
# pd.to_numeric (it's a numerically valid float) and crashed training deep
# inside sklearn as an unhandled 500 instead of a clean 400.
_POSITIVE_COLUMNS = ("resale_price", "msrp_proxy")
_NON_NEGATIVE_COLUMNS = ("mileage", "vehicle_age")


def validate_columns(columns):
    missing = REQUIRED_COLUMNS - set(columns)
    if missing:
        raise MalformedDatasetError(
            f"Dataset upload failed. Missing required columns: [{', '.join(sorted(missing))}]."
        )


def _row_numbers(df, mask):
    """1-based row numbers as a human uploading the CSV would count them
    (header is row 1, the first data row is row 2) - not the 0-based
    DataFrame index these errors would otherwise leak."""
    return [int(i) + 2 for i in df.index[mask]]


def load_and_validate_csv(file_obj):
    """Parse an uploaded CSV into a DataFrame ready for training.

    QA audit M10: previously, any row with a non-numeric value in a
    required column was silently coerced to NaN and dropped via dropna -
    no error, no count, so a CSV with a few garbled rows trained
    successfully on a silently-shrunk dataset. UC012's alt flow calls for
    halting ingestion with a clear message instead, so this now raises
    MalformedDatasetError naming exactly which rows failed and why,
    rather than dropping and continuing:
      - any required-column value that doesn't parse as a finite number
        (NaN, +-inf) at all, or
      - a required-column value that parses but is semantically invalid
        (resale_price/msrp_proxy <= 0, mileage/vehicle_age < 0).
    Nothing is dropped-and-proceeded in either case - the whole upload is
    rejected, matching the already-existing "missing columns" alt flow's
    all-or-nothing behaviour.
    """
    try:
        df = pd.read_csv(file_obj)
    except Exception as exc:
        raise MalformedDatasetError(f"Dataset upload failed. Could not parse CSV file: {exc}") from exc

    validate_columns(df.columns)

    required = list(REQUIRED_COLUMNS)
    for column in required:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    unparseable_mask = ~np.isfinite(df[required]).all(axis=1)
    if unparseable_mask.any():
        rows = _row_numbers(df, unparseable_mask)
        raise MalformedDatasetError(
            f"Dataset upload failed. {len(rows)} row(s) have a non-numeric or non-finite value "
            f"in a required column and cannot be used: row(s) {rows}."
        )

    invalid_mask = pd.Series(False, index=df.index)
    for column in _POSITIVE_COLUMNS:
        invalid_mask |= df[column] <= 0
    for column in _NON_NEGATIVE_COLUMNS:
        invalid_mask |= df[column] < 0
    if invalid_mask.any():
        rows = _row_numbers(df, invalid_mask)
        raise MalformedDatasetError(
            f"Dataset upload failed. {len(rows)} row(s) have an invalid value (resale_price/"
            f"msrp_proxy must be > 0, mileage/vehicle_age must be >= 0): row(s) {rows}."
        )

    if df.empty:
        raise MalformedDatasetError("Dataset upload failed. No data rows found.")

    return df


def validate_minimum_rows(df):
    """QA audit M10: a CSV with too few rows for a meaningful 80/20 split
    + 3-fold GridSearchCV previously reached train_and_evaluate anyway and
    raised from inside sklearn as an unhandled 500. Called separately from
    (and after) load_and_validate_csv, right before train_and_evaluate -
    not folded into load_and_validate_csv itself, since several existing
    tests deliberately exercise train_and_evaluate's deploy-gate behaviour
    against tiny hand-built DataFrames independent of row-count realism.
    """
    if len(df) < MIN_TRAINING_ROWS:
        raise MalformedDatasetError(
            f"Dataset upload failed. At least {MIN_TRAINING_ROWS} rows are required to train "
            f"and validate a model reliably; only {len(df)} row(s) were provided."
        )


def train_and_evaluate(df, random_state=42, cv=DEFAULT_CV, param_grids=None):
    """Runs a real GridSearchCV per candidate regressor - cv-fold search
    on the training split only, never touching the held-out test split -
    then evaluates each search's best_estimator_ on that untouched test
    split exactly as before. That test-split score (not the CV score) is
    what's reported and gates deployment.

    `param_grids` lets tests substitute a tiny grid to stay fast without
    changing what this actually verifies; defaults to the real
    production grids (RF_PARAM_GRID / GB_PARAM_GRID) otherwise.

    Returns the same {"estimator", "r2", "mae"} keys as before per
    ModelType, plus a new "best_params" key - the winning hyperparameters
    GridSearchCV chose, so run_training_task/MLTrainingRun can record
    them (see apps/ml/models.py's rf_best_params/gb_best_params).

    QA audit C8: `r2`/`mae` describe fit against RATIO_TARGET_COLUMN
    (resale_price / msrp_proxy, clipped to RATIO_CLIP_MAX), not raw
    resale_price - see this module's docstring for why. `mae` is
    therefore a retention-FRACTION error (e.g. 0.05 == "off by 5
    percentage points of retained value"), never an RM figure - a caller
    printing/recording it must not label it "RM" (see
    apps/ml/data/README_real_data.md's retrain write-up and
    apps/ml/management/commands/run_real_retrain.py, both updated to say
    so explicitly).
    """
    df = df.copy()
    df[RATIO_TARGET_COLUMN] = (df[TARGET_COLUMN] / df["msrp_proxy"]).clip(upper=RATIO_CLIP_MAX)

    X = df[FEATURE_COLUMNS]
    y = df[RATIO_TARGET_COLUMN]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=random_state)

    grids = param_grids or {
        ModelType.RANDOM_FOREST: RF_PARAM_GRID,
        ModelType.GRADIENT_BOOSTING: GB_PARAM_GRID,
    }
    base_estimators = {
        ModelType.RANDOM_FOREST: RandomForestRegressor(random_state=random_state),
        ModelType.GRADIENT_BOOSTING: GradientBoostingRegressor(random_state=random_state),
    }

    results = {}
    for model_type, base_estimator in base_estimators.items():
        search = GridSearchCV(base_estimator, grids[model_type], cv=cv, scoring="r2")
        search.fit(X_train, y_train)

        best_estimator = search.best_estimator_
        predictions = best_estimator.predict(X_test)
        results[model_type] = {
            "estimator": best_estimator,
            "r2": float(r2_score(y_test, predictions)),
            "mae": float(mean_absolute_error(y_test, predictions)),
            "best_params": search.best_params_,
        }
    return results


def pick_best_and_decide_deployment(results, current_r2=None):
    """the project spec: 'deploy whichever has the higher validation R^2' - but
    only if that R^2 also clears the 0.80 operational threshold (UC012
    Rule 1). Returns (best_model_type, best_result, should_deploy, rejection_reason).

    QA audit H11: a SECOND gate, now required in addition to the 0.80
    floor - the candidate's R^2 must also be >= `current_r2`, the
    CURRENTLY deployed production model's own r2_score (apps/ml/tasks.py
    reads it from ProductionModel.get_singleton() and passes it in here;
    this function stays framework-free and testable without Django, so it
    takes the number rather than looking it up itself). Previously only
    the fixed 0.80 threshold was checked, with no comparison to what was
    already deployed at all - a tiny, barely-adequate CSV (e.g. a 12-row
    upload that happened to clear 0.80 on a 3-row test split) could
    silently replace a genuinely better model trained on hundreds of real
    rows. `current_r2=None` (nothing deployed yet - the bootstrap case)
    trivially satisfies this second gate, same as before.

    The two gates fail for genuinely different reasons, and
    `rejection_reason` says which one - "below the 0.80 threshold" is a
    data-quality problem with THIS run; "doesn't improve on production's
    0.89" is a relative comparison that says nothing about whether this
    run's data was bad. An admin reading training-run history needs to
    tell those apart, not see the same generic message either way.
    """
    best_model_type = max(results, key=lambda model_type: results[model_type]["r2"])
    best = results[best_model_type]

    if best["r2"] < R2_DEPLOYMENT_THRESHOLD:
        rejection_reason = (
            f"Best validation R² ({best['r2']:.4f} from {best_model_type}) is below the "
            f"required {R2_DEPLOYMENT_THRESHOLD:.2f} threshold; keeping the current production model."
        )
        return best_model_type, best, False, rejection_reason

    if current_r2 is not None and best["r2"] < current_r2:
        rejection_reason = (
            f"Best validation R² ({best['r2']:.4f} from {best_model_type}) clears the "
            f"{R2_DEPLOYMENT_THRESHOLD:.2f} threshold but does not improve on the currently "
            f"deployed production model's R² ({current_r2:.4f}); keeping the current production model."
        )
        return best_model_type, best, False, rejection_reason

    return best_model_type, best, True, ""
