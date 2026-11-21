"""F012 - CSV validation and RandomForest/GradientBoosting training (UC012).

Framework-free where it matters: validate_columns/pick_best_and_deploy are
plain functions so the R^2 deployment gate and the malformed-CSV alt flow
can be tested without touching Django, Celery, or a real dataset.

What the model predicts (ML batch 1): the LOG of the resale price, from the
car's own attributes only - age, mileage, brand price tier, engine size (litres),
body type and whether it is a recond import (apps/ml/features.py is the one
definition of those columns, shared with the dataset build and inference).
That is what the FYP1 report describes ("predicted vehicle residual market
values"; UC012's columns Age, Mileage, Resale Price, Brand Code). Inference
uses only the SHAPE of the prediction - value at month m relative to month 0
- scaled to the car's real catalog price.

Why the old target was dropped: until this batch the model predicted a
value-retention ratio, resale_price / msrp_proxy. msrp_proxy was a USED price
(the highest other listing of the same model, on average 4.3 years old), so
the ratio compared each car with an old example of itself, while at inference
the same feature slot received the real NEW price - the feature meant
different things in training and in use. The best honest result on that
target was about 0.77, below the gate. msrp_proxy is no longer built.

Three candidates (ML batch 2): Random Forest and Gradient Boosting (the FYP1
report's two, with their grid searches) and a log-linear (hedonic) model
(apps/ml/log_linear.py) that gives each car model its own price level, so the
model mix of young listings no longer biases the age effect. All three are
scored on the same held-out rows; the highest R² wins as before, and the
winner must also pass the curve check (apps/ml/curve_check.py) to be
deploy-eligible.

Two metrics, both recorded on every run and both shown on the ML page:
- `r2` / `mae`: on the held-out 20%, on the log scale. `r2` is what the 0.80
  deployment gate checks (unchanged). `mae` on a log scale is a relative
  error: e^MAE - 1 is the typical error as a fraction of the price.
- `within_model_r2` ("depreciation-shape R²"): most of `r2` comes from telling
  an expensive car from a cheap one (price level), but the depreciation curve
  only uses how price changes within one car model. This R² is computed on the
  held-out rows after removing each car model's own mean (see within_model_r2),
  so it measures exactly that part. It is lower than `r2`; it is reported for
  transparency and does not gate deployment.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GridSearchCV, train_test_split

from .features import BODY_TYPES, NUMERIC_COLUMNS, feature_frame
from .log_linear import LogLinearDepreciationModel
from .models import CURRENT_PREDICTION_TARGET, ModelType, R2_DEPLOYMENT_THRESHOLD
from .run_texts import model_type_label

REQUIRED_COLUMNS = {
    "vehicle_age", "mileage", "resale_price", "brand_code", "engine_litres", "body_type", "recond",
}
# Optional: the car model each listing is of (e.g. "BMW 320i"). Used only for
# the within-model metric, never as a feature.
MODEL_KEY_COLUMN = "model_key"
TARGET_COLUMN = "resale_price"
PREDICTION_TARGET = CURRENT_PREDICTION_TARGET

# Small, defensible search grids - not exhaustive, but a real search
# rather than one hand-picked guess. ~1,000 real rows (see
# apps/ml/data/README_real_data.md) is small enough that GridSearchCV
# over these stays fast even with cv=3.
RF_PARAM_GRID = {"n_estimators": [100, 200, 300], "max_depth": [None, 8, 16]}
GB_PARAM_GRID = {"n_estimators": [100, 200], "learning_rate": [0.05, 0.1], "max_depth": [2, 3, 4]}
DEFAULT_CV = 3

# The within-model metric needs enough held-out rows that share a car model
# with another held-out row to mean anything.
WITHIN_MODEL_MIN_ROWS = 10

MAX_ENGINE_LITRES = 8.0
BRAND_CODES = (1, 2, 3, 4, 5)


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

INVALID_VALUE_RULES = (
    "resale_price must be > 0, mileage/vehicle_age must be >= 0, engine_litres must be > 0 and <= 8, "
    "recond must be 0 or 1, brand_code must be 1 to 5"
)


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

    All or nothing (UC012 alt flow, QA audit M10): any bad row rejects the
    whole upload with a message naming the rows - nothing is dropped and
    trained on silently. Checked in this order:
      - every required column is present (an old 5-column CSV with
        msrp_proxy fails here: "Missing required columns: [...]");
      - every numeric column parses as a finite number;
      - body_type is one of BODY_TYPES;
      - the values make sense (INVALID_VALUE_RULES).
    """
    try:
        df = pd.read_csv(file_obj)
    except Exception as exc:
        raise MalformedDatasetError(f"Dataset upload failed. Could not parse CSV file: {exc}") from exc

    validate_columns(df.columns)

    for column in NUMERIC_COLUMNS + [TARGET_COLUMN]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    numeric = NUMERIC_COLUMNS + [TARGET_COLUMN]

    unparseable_mask = ~np.isfinite(df[numeric]).all(axis=1)
    if unparseable_mask.any():
        rows = _row_numbers(df, unparseable_mask)
        raise MalformedDatasetError(
            f"Dataset upload failed. {len(rows)} row(s) have a non-numeric or non-finite value "
            f"in a required column and cannot be used: row(s) {rows}."
        )

    df["body_type"] = df["body_type"].astype("string").str.strip()
    unknown_body_mask = ~df["body_type"].isin(BODY_TYPES).fillna(False).astype(bool)
    if unknown_body_mask.any():
        rows = _row_numbers(df, unknown_body_mask)
        raise MalformedDatasetError(
            f"Dataset upload failed. {len(rows)} row(s) have a body_type that is not one of "
            f"{', '.join(BODY_TYPES)}: row(s) {rows}."
        )
    df["body_type"] = df["body_type"].astype(object)

    invalid_mask = (
        (df["resale_price"] <= 0)
        | (df["mileage"] < 0)
        | (df["vehicle_age"] < 0)
        | (df["engine_litres"] <= 0)
        | (df["engine_litres"] > MAX_ENGINE_LITRES)
        | ~df["recond"].isin([0, 1])
        | ~df["brand_code"].isin(BRAND_CODES)
    )
    if invalid_mask.any():
        rows = _row_numbers(df, invalid_mask)
        raise MalformedDatasetError(
            f"Dataset upload failed. {len(rows)} row(s) have an invalid value ({INVALID_VALUE_RULES}): "
            f"row(s) {rows}."
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


def within_model_r2(model_keys, actual, predicted, min_rows=WITHIN_MODEL_MIN_ROWS):
    """The depreciation-shape R²: how well the predictions explain price
    differences between listings of the SAME car model.

    Keeps the rows whose model key appears at least twice among these rows,
    subtracts each key's own mean from both the actual and the predicted
    values, and returns r2_score of the two. None when no key is given, fewer
    than `min_rows` rows qualify, or the qualifying actual values have no
    spread to explain."""
    if model_keys is None:
        return None
    frame = pd.DataFrame({
        "key": pd.Series(model_keys).reset_index(drop=True),
        "actual": np.asarray(actual, dtype=float),
        "predicted": np.asarray(predicted, dtype=float),
    })
    frame = frame[frame["key"].notna() & (frame["key"].astype(str).str.strip() != "")]
    frame = frame[frame["key"].map(frame["key"].value_counts()) >= 2]
    if len(frame) < min_rows:
        return None
    grouped = frame.groupby("key")
    actual_dev = frame["actual"] - grouped["actual"].transform("mean")
    predicted_dev = frame["predicted"] - grouped["predicted"].transform("mean")
    if float((actual_dev**2).sum()) == 0.0:
        return None
    return float(r2_score(actual_dev, predicted_dev))


def train_and_evaluate(df, random_state=42, cv=DEFAULT_CV, param_grids=None):
    """Runs a real GridSearchCV per candidate regressor - cv-fold search
    on the training split only, never touching the held-out test split -
    then evaluates each search's best_estimator_ on that untouched test
    split. That test-split score (not the CV score) is what's reported and
    gates deployment.

    `param_grids` lets tests substitute a tiny grid to stay fast without
    changing what this actually verifies; defaults to the real
    production grids (RF_PARAM_GRID / GB_PARAM_GRID) otherwise.

    Returns, per ModelType (Random Forest, Gradient Boosting and - ML batch 2 -
    the log-linear model): "estimator", "r2", "mae" (both on the log-price
    scale - see this module's docstring), "within_model_r2" (None without a
    model_key column) and "best_params" ({"alpha": ...} for the log-linear).
    """
    X = feature_frame(df)
    y = np.log(df[TARGET_COLUMN].astype(float))
    keys = df[MODEL_KEY_COLUMN] if MODEL_KEY_COLUMN in df.columns else pd.Series([None] * len(df), index=df.index)
    X_train, X_test, y_train, y_test, _keys_train, keys_test = train_test_split(
        X, y, keys, test_size=0.2, random_state=random_state
    )
    has_keys = MODEL_KEY_COLUMN in df.columns

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
            "within_model_r2": within_model_r2(keys_test, y_test, predictions) if has_keys else None,
            "best_params": search.best_params_,
        }

    # ML batch 2: the log-linear (hedonic) candidate, on the SAME split. Its
    # one hyperparameter (the ridge alpha) is chosen by RidgeCV on the
    # training split only; the held-out rows are scored with their own
    # model_key (a key seen in training gets its level, an unseen one none).
    log_linear = LogLinearDepreciationModel().fit(
        X_train, y_train, list(_keys_train) if has_keys else None
    )
    predictions = log_linear.predict(X_test, list(keys_test) if has_keys else None)
    results[ModelType.LOG_LINEAR] = {
        "estimator": log_linear,
        "r2": float(r2_score(y_test, predictions)),
        "mae": float(mean_absolute_error(y_test, predictions)),
        "within_model_r2": within_model_r2(keys_test, y_test, predictions) if has_keys else None,
        "best_params": {"alpha": log_linear.alpha},
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
    rows. `current_r2=None` (nothing deployed yet - the bootstrap case -
    or, since ML batch 1, a production model with a different prediction
    target, whose R² is not comparable) trivially satisfies this second
    gate.

    The two gates fail for genuinely different reasons, and
    `rejection_reason` says which one - "below the 0.80 threshold" is a
    data-quality problem with THIS run; "doesn't improve on production's
    0.89" is a relative comparison that says nothing about whether this
    run's data was bad. An admin reading training-run history needs to
    tell those apart, not see the same generic message either way.
    """
    best_model_type = max(results, key=lambda model_type: results[model_type]["r2"])
    best = results[best_model_type]
    # Run 3 fix batch 5 (F-26): the reason is shown on the ML page - the model's name, not its key.
    best_label = model_type_label(best_model_type)

    if best["r2"] < R2_DEPLOYMENT_THRESHOLD:
        rejection_reason = (
            f"Best validation R² ({best['r2']:.4f} from {best_label}) is below the "
            f"required {R2_DEPLOYMENT_THRESHOLD:.2f} threshold; keeping the current production model."
        )
        return best_model_type, best, False, rejection_reason

    if current_r2 is not None and best["r2"] < current_r2:
        rejection_reason = (
            f"Best validation R² ({best['r2']:.4f} from {best_label}) clears the "
            f"{R2_DEPLOYMENT_THRESHOLD:.2f} threshold but does not improve on the currently "
            f"deployed production model's R² ({current_r2:.4f}); keeping the current production model."
        )
        return best_model_type, best, False, rejection_reason

    return best_model_type, best, True, ""
