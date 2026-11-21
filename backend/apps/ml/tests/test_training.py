import io
import math

import numpy as np
import pandas as pd
import pytest

from apps.ml import training
from apps.ml.features import BODY_TYPES
from apps.ml.models import ModelType, PredictionTarget

SYNTHETIC_DATASET_PATH = "apps/ml/data/synthetic_historical_pricing.csv"
HEADER = "vehicle_age,mileage,resale_price,brand_code,engine_litres,body_type,recond"


def make_csv(rows, header=HEADER):
    lines = [header] + rows
    return io.BytesIO("\n".join(lines).encode("utf-8"))


def row(age=2, mileage=20000, price=45000, brand=1, litres=2.0, body="sedan", recond=0):
    return f"{age},{mileage},{price},{brand},{litres},{body},{recond}"


def make_learnable_dataset(n_per_brand=100, random_state=42):
    """A small, deterministic, genuinely-learnable dataset in the ML batch 1
    schema: a price level per brand tier, engine size and body type, then the
    same age/mileage depreciation shape generate_synthetic_ml_dataset.py uses.
    model_key groups listings of the same synthetic car model."""
    rng = np.random.default_rng(random_state)
    brand_base_price = {1: 180000, 2: 120000, 3: 90000, 4: 70000, 5: 50000}
    rows = []
    for brand_code, base_price in brand_base_price.items():
        for _ in range(n_per_brand):
            body = BODY_TYPES[int(rng.integers(0, len(BODY_TYPES)))]
            litres = float(rng.choice([1.5, 2.0, 2.5, 3.0]))
            vehicle_age = rng.uniform(0, 10)
            mileage = max(0, vehicle_age * rng.uniform(8000, 18000) + rng.normal(0, 2000))
            depreciation_factor = 0.85**vehicle_age
            mileage_penalty = max(0.70, 1 - mileage * 0.000003)
            noise = rng.normal(1.0, 0.03)
            new_price = base_price * (1 + 0.1 * (litres - 2.0))
            resale_price = max(1000, new_price * depreciation_factor * mileage_penalty * noise)
            rows.append(
                {
                    "vehicle_age": round(vehicle_age, 2),
                    "mileage": round(mileage, 0),
                    "resale_price": round(resale_price, 2),
                    "brand_code": brand_code,
                    "engine_litres": litres,
                    "body_type": body,
                    "recond": int(rng.random() < 0.1),
                    "model_key": f"Brand{brand_code} {body} {litres}",
                }
            )
    return pd.DataFrame(rows).sample(frac=1, random_state=random_state).reset_index(drop=True)


# --- Malformed CSV (UC012 alternate flow) -----------------------------------


def test_missing_required_columns_rejected():
    csv_file = make_csv(["2,20000,45000,1"], header="vehicle_age,mileage,brand_code")

    with pytest.raises(training.MalformedDatasetError) as exc_info:
        training.load_and_validate_csv(csv_file)

    assert "Missing required columns" in str(exc_info.value)
    assert "resale_price" in str(exc_info.value)


def test_missing_columns_error_lists_every_missing_column():
    csv_file = make_csv(["45000"], header="resale_price")

    with pytest.raises(training.MalformedDatasetError) as exc_info:
        training.load_and_validate_csv(csv_file)

    message = str(exc_info.value)
    for column in ("vehicle_age", "mileage", "brand_code", "engine_litres", "body_type", "recond"):
        assert column in message


def test_an_old_five_column_msrp_proxy_csv_is_refused_with_the_missing_columns_message():
    """ML batch 1: the pre-batch schema (msrp_proxy, no engine/body/recond)."""
    csv_file = make_csv(["2,20000,45000,1,60000"], header="vehicle_age,mileage,resale_price,brand_code,msrp_proxy")

    with pytest.raises(training.MalformedDatasetError) as exc_info:
        training.load_and_validate_csv(csv_file)

    assert str(exc_info.value) == (
        "Dataset upload failed. Missing required columns: [body_type, engine_litres, recond]."
    )


def test_model_key_is_optional():
    df = training.load_and_validate_csv(make_csv([row(), row(age=5, price=25000, brand=2, body="suv")]))

    assert len(df) == 2
    assert "model_key" not in df.columns


def test_unparseable_rows_reject_the_whole_upload_not_dropped_silently():
    """QA audit M10: a non-numeric row rejects the whole upload, naming the
    row (header is row 1), rather than being silently dropped."""
    csv_file = make_csv([row(), row(age="not-a-number"), row(age=3, price=42000)])

    with pytest.raises(training.MalformedDatasetError) as exc_info:
        training.load_and_validate_csv(csv_file)

    assert "1 row(s)" in str(exc_info.value)
    assert "[3]" in str(exc_info.value)


def test_several_unparseable_rows_are_all_named():
    csv_file = make_csv([row(), row(age="not-a-number"), row(age=3), row(mileage="abc")])

    with pytest.raises(training.MalformedDatasetError) as exc_info:
        training.load_and_validate_csv(csv_file)

    message = str(exc_info.value)
    assert "2 row(s)" in message
    assert "[3, 5]" in message


def test_all_rows_unparseable_is_malformed():
    csv_file = make_csv(["abc,def,ghi,jkl,mno,pqr,stu"])

    with pytest.raises(training.MalformedDatasetError):
        training.load_and_validate_csv(csv_file)


def test_infinite_value_is_rejected_not_passed_to_sklearn():
    csv_file = make_csv([row(price="inf"), row(age=3)])

    with pytest.raises(training.MalformedDatasetError) as exc_info:
        training.load_and_validate_csv(csv_file)

    # pandas parses the literal "inf" to a numeric +inf - caught by the
    # finite check, not the separate value-rules check.
    assert "non-numeric or non-finite" in str(exc_info.value)


# --- ML batch 1: body type and the value rules ---------------------------------


def test_an_unknown_body_type_is_refused_naming_the_rows():
    csv_file = make_csv([row(), row(body="wagon"), row(body="")])

    with pytest.raises(training.MalformedDatasetError) as exc_info:
        training.load_and_validate_csv(csv_file)

    assert str(exc_info.value) == (
        "Dataset upload failed. 2 row(s) have a body_type that is not one of sedan, hatchback, suv, mpv, "
        "pickup, coupe: row(s) [3, 4]."
    )


@pytest.mark.parametrize(
    "bad_row",
    [
        row(mileage=-500),
        row(price=0),
        row(age=-1),
        row(litres=0),
        row(litres=8.1),
        row(recond=2),
        row(recond=0.5),
        row(brand=0),
        row(brand=6),
        row(brand=2.5),
    ],
)
def test_each_value_rule_refuses_the_whole_upload(bad_row):
    csv_file = make_csv([row(age=3), bad_row])

    with pytest.raises(training.MalformedDatasetError) as exc_info:
        training.load_and_validate_csv(csv_file)

    assert str(exc_info.value) == (
        "Dataset upload failed. 1 row(s) have an invalid value (resale_price must be > 0, mileage/vehicle_age "
        "must be >= 0, engine_litres must be > 0 and <= 8, recond must be 0 or 1, brand_code must be 1 to 5): "
        "row(s) [3]."
    )


@pytest.mark.parametrize("good_row", [row(litres=8.0), row(recond=1), row(brand=5), row(body="coupe")])
def test_values_at_the_limits_are_accepted(good_row):
    df = training.load_and_validate_csv(make_csv([good_row]))

    assert len(df) == 1


# --- M10: too few rows for a meaningful 80/20 split + 3-fold CV --------------


def test_validate_minimum_rows_rejects_a_too_small_dataset():
    df = training.load_and_validate_csv(make_csv([row(age=2 + i, mileage=20000 + i) for i in range(5)]))

    with pytest.raises(training.MalformedDatasetError) as exc_info:
        training.validate_minimum_rows(df)

    assert "30" in str(exc_info.value)
    assert "5" in str(exc_info.value)


def test_validate_minimum_rows_accepts_a_dataset_at_the_floor():
    df = training.load_and_validate_csv(
        make_csv([row(age=2 + i % 8, mileage=20000 + i * 500, price=45000 - i * 100, brand=1 + i % 5) for i in range(30)])
    )

    training.validate_minimum_rows(df)  # does not raise


def test_valid_csv_parses_cleanly():
    df = training.load_and_validate_csv(make_csv([row(), row(age=5, mileage=60000, price=25000, brand=2, body="mpv")]))

    assert len(df) == 2
    assert list(df["brand_code"]) == [1, 2]
    assert list(df["body_type"]) == ["sedan", "mpv"]


def test_legacy_synthetic_dataset_is_incompatible_with_current_schema():
    # synthetic_historical_pricing.csv is kept unmodified as bootstrap-phase
    # history (see apps/ml/data/README.md) - NOT regenerated for the current
    # REQUIRED_COLUMNS; this fails loudly if it is fed in by mistake.
    with open(SYNTHETIC_DATASET_PATH, "rb") as f:
        with pytest.raises(training.MalformedDatasetError) as exc_info:
            training.load_and_validate_csv(f)

    assert "Missing required columns" in str(exc_info.value)
    assert "engine_litres" in str(exc_info.value)


# --- the within-model (depreciation-shape) R² ---------------------------------


def test_within_model_r2_on_a_hand_made_frame():
    """Two car models at different price levels. Within each model, the
    predictions get the price differences exactly right except one:
      A: actual 10, 12, 14 (mean 12 -> -2, 0, +2); predicted 1, 3, 5 (mean 3 -> -2, 0, +2)
      B: actual 20, 22, 24, 26 (mean 23 -> -3, -1, +1, +3);
         predicted 5, 7, 9, 13 (mean 8.5 -> -3.5, -1.5, +0.5, +4.5)
    The level is wildly off (which the plain R² punishes) but irrelevant here.
    SS_res = 0.25 + 0.25 + 0.25 + 2.25 = 3.0; SS_tot (of the actual
    deviations, mean 0) = 4 + 0 + 4 + 9 + 1 + 1 + 9 = 28 -> 1 - 3/28."""
    keys = ["A", "A", "A", "B", "B", "B", "B", "C"]  # C has one row: left out
    actual = [10, 12, 14, 20, 22, 24, 26, 99]
    predicted = [1, 3, 5, 5, 7, 9, 13, 0]

    value = training.within_model_r2(keys, actual, predicted, min_rows=7)

    assert value == pytest.approx(1 - 3 / 28)


def test_within_model_r2_is_none_without_keys_or_with_too_few_rows():
    assert training.within_model_r2(None, [1, 2], [1, 2]) is None
    # 9 qualifying rows < the 10-row floor
    assert training.within_model_r2(["A"] * 9, list(range(9)), list(range(9))) is None
    assert training.within_model_r2(["A"] * 10, list(range(10)), list(range(10))) == pytest.approx(1.0)
    # blank keys never qualify
    assert training.within_model_r2([""] * 10 + [None] * 2, list(range(12)), list(range(12))) is None


# --- R^2 >= 0.80 deployment gate --------------------------------------------


def test_deploys_whichever_model_has_higher_r2_when_both_clear_threshold():
    results = {
        ModelType.RANDOM_FOREST: {"estimator": object(), "r2": 0.85, "mae": 1000.0},
        ModelType.GRADIENT_BOOSTING: {"estimator": object(), "r2": 0.91, "mae": 900.0},
    }

    best_type, best, should_deploy, reason = training.pick_best_and_decide_deployment(results)

    assert best_type == ModelType.GRADIENT_BOOSTING
    assert should_deploy is True
    assert reason == ""


def test_rejects_deployment_when_best_r2_below_threshold():
    results = {
        ModelType.RANDOM_FOREST: {"estimator": object(), "r2": 0.62, "mae": 5000.0},
        ModelType.GRADIENT_BOOSTING: {"estimator": object(), "r2": 0.55, "mae": 5500.0},
    }

    best_type, best, should_deploy, reason = training.pick_best_and_decide_deployment(results)

    assert best_type == ModelType.RANDOM_FOREST  # still identifies the better of the two
    assert should_deploy is False
    assert "0.80" in reason
    assert "0.62" in reason


def test_gate_is_inclusive_at_exactly_080():
    results = {
        ModelType.RANDOM_FOREST: {"estimator": object(), "r2": 0.80, "mae": 1000.0},
        ModelType.GRADIENT_BOOSTING: {"estimator": object(), "r2": 0.70, "mae": 1200.0},
    }

    _, _, should_deploy, reason = training.pick_best_and_decide_deployment(results)

    assert should_deploy is True
    assert reason == ""


# --- H11: a candidate must also beat (or tie) the currently-deployed R^2 ----


def test_rejects_deployment_when_best_r2_clears_threshold_but_does_not_beat_production():
    results = {
        ModelType.RANDOM_FOREST: {"estimator": object(), "r2": 0.84, "mae": 1000.0},
        ModelType.GRADIENT_BOOSTING: {"estimator": object(), "r2": 0.81, "mae": 1100.0},
    }

    best_type, best, should_deploy, reason = training.pick_best_and_decide_deployment(results, current_r2=0.89)

    assert best_type == ModelType.RANDOM_FOREST
    assert should_deploy is False
    assert "0.89" in reason
    assert "0.84" in reason
    assert "does not improve" in reason


def test_deploys_when_best_r2_clears_threshold_and_beats_production():
    results = {
        ModelType.RANDOM_FOREST: {"estimator": object(), "r2": 0.92, "mae": 800.0},
        ModelType.GRADIENT_BOOSTING: {"estimator": object(), "r2": 0.85, "mae": 900.0},
    }

    _, _, should_deploy, reason = training.pick_best_and_decide_deployment(results, current_r2=0.89)

    assert should_deploy is True
    assert reason == ""


def test_equal_r2_to_production_still_deploys_gate_is_inclusive():
    results = {
        ModelType.RANDOM_FOREST: {"estimator": object(), "r2": 0.89, "mae": 1000.0},
        ModelType.GRADIENT_BOOSTING: {"estimator": object(), "r2": 0.80, "mae": 1200.0},
    }

    _, _, should_deploy, _ = training.pick_best_and_decide_deployment(results, current_r2=0.89)

    assert should_deploy is True


def test_no_current_production_model_trivially_satisfies_the_comparison_gate():
    results = {
        ModelType.RANDOM_FOREST: {"estimator": object(), "r2": 0.81, "mae": 1000.0},
        ModelType.GRADIENT_BOOSTING: {"estimator": object(), "r2": 0.70, "mae": 1200.0},
    }

    _, _, should_deploy, reason = training.pick_best_and_decide_deployment(results, current_r2=None)

    assert should_deploy is True
    assert reason == ""


def test_the_gate_and_grids_are_unchanged():
    from apps.ml.models import R2_DEPLOYMENT_THRESHOLD

    assert R2_DEPLOYMENT_THRESHOLD == 0.80
    assert training.RF_PARAM_GRID == {"n_estimators": [100, 200, 300], "max_depth": [None, 8, 16]}
    assert training.GB_PARAM_GRID == {"n_estimators": [100, 200], "learning_rate": [0.05, 0.1], "max_depth": [2, 3, 4]}
    assert training.DEFAULT_CV == 3
    assert training.PREDICTION_TARGET == PredictionTarget.LOG_RESALE_PRICE


# --- A genuinely learnable dataset clears the deployment gate -----

TINY_GRIDS = {
    ModelType.RANDOM_FOREST: {"n_estimators": [100], "max_depth": [None]},
    ModelType.GRADIENT_BOOSTING: {"n_estimators": [100], "learning_rate": [0.1], "max_depth": [3]},
}


def test_learnable_dataset_trains_to_acceptable_r2_on_the_log_price():
    df = make_learnable_dataset()

    results = training.train_and_evaluate(df, cv=3, param_grids=TINY_GRIDS)
    best_type, best, should_deploy, reason = training.pick_best_and_decide_deployment(results)

    assert should_deploy is True, reason
    assert best["r2"] >= 0.80
    # log scale: a typical relative error well under 100% of the price
    assert 0 < best["mae"] < math.log(2)
    for result in results.values():
        assert result["within_model_r2"] is not None
        assert result["within_model_r2"] <= 1.0


def test_the_metrics_are_measured_on_log_price():
    """r2 equals r2_score on log(resale_price) of the held-out rows - not on the price."""
    from sklearn.metrics import r2_score
    from sklearn.model_selection import train_test_split

    from apps.ml.features import feature_frame

    df = make_learnable_dataset(n_per_brand=40)
    results = training.train_and_evaluate(df, cv=3, param_grids=TINY_GRIDS)

    X_train, X_test, y_train, y_test = train_test_split(
        feature_frame(df), np.log(df["resale_price"]), test_size=0.2, random_state=42
    )
    gb = results[ModelType.GRADIENT_BOOSTING]
    assert gb["r2"] == pytest.approx(r2_score(y_test, gb["estimator"].predict(X_test)))


def test_within_model_r2_is_none_when_the_upload_has_no_model_key():
    df = make_learnable_dataset(n_per_brand=40).drop(columns=["model_key"])

    results = training.train_and_evaluate(df, cv=3, param_grids=TINY_GRIDS)

    assert results[ModelType.RANDOM_FOREST]["within_model_r2"] is None
    assert results[ModelType.GRADIENT_BOOSTING]["within_model_r2"] is None
    assert results[ModelType.LOG_LINEAR]["within_model_r2"] is None
    assert results[ModelType.LOG_LINEAR]["estimator"].key_levels == []


# --- ML batch 2: the log-linear (hedonic) candidate ---------------------------------


def test_three_candidates_are_trained_on_the_same_split():
    from sklearn.metrics import r2_score
    from sklearn.model_selection import train_test_split

    from apps.ml.features import feature_frame
    from apps.ml.log_linear import LogLinearDepreciationModel

    df = make_learnable_dataset(n_per_brand=40)

    results = training.train_and_evaluate(df, cv=3, param_grids=TINY_GRIDS)

    assert list(results) == [ModelType.RANDOM_FOREST, ModelType.GRADIENT_BOOSTING, ModelType.LOG_LINEAR]
    ll = results[ModelType.LOG_LINEAR]
    assert isinstance(ll["estimator"], LogLinearDepreciationModel)
    assert set(ll) == {"estimator", "r2", "mae", "within_model_r2", "best_params"}
    assert ll["best_params"] == {"alpha": ll["estimator"].alpha}
    assert ll["within_model_r2"] is not None
    # Scored on the same held-out rows as RF/GB, each held-out row with its own model_key.
    X_train, X_test, y_train, y_test, k_train, k_test = train_test_split(
        feature_frame(df), np.log(df["resale_price"]), df["model_key"], test_size=0.2, random_state=42
    )
    assert ll["r2"] == pytest.approx(r2_score(y_test, ll["estimator"].predict(X_test, list(k_test))))
    assert ll["estimator"].key_levels == sorted(set(k_train))


def test_the_log_linear_wins_only_by_the_usual_highest_r2_rule():
    results = {
        ModelType.RANDOM_FOREST: {"estimator": object(), "r2": 0.86, "mae": 0.2},
        ModelType.GRADIENT_BOOSTING: {"estimator": object(), "r2": 0.88, "mae": 0.2},
        ModelType.LOG_LINEAR: {"estimator": object(), "r2": 0.91, "mae": 0.15},
    }
    assert training.pick_best_and_decide_deployment(results)[0] == ModelType.LOG_LINEAR

    results[ModelType.LOG_LINEAR]["r2"] = 0.87
    assert training.pick_best_and_decide_deployment(results)[0] == ModelType.GRADIENT_BOOSTING


# --- Real hyperparameter search (not one hand-picked guess) -----------------


def test_grid_search_actually_searches_and_records_best_params():
    df = make_learnable_dataset()

    param_grids = {
        ModelType.RANDOM_FOREST: {"n_estimators": [50, 100], "max_depth": [4, None]},
        ModelType.GRADIENT_BOOSTING: {"n_estimators": [50, 100], "learning_rate": [0.05, 0.1], "max_depth": [2, 3]},
    }

    results = training.train_and_evaluate(df, cv=3, param_grids=param_grids)

    rf_params = results[ModelType.RANDOM_FOREST]["best_params"]
    gb_params = results[ModelType.GRADIENT_BOOSTING]["best_params"]

    assert rf_params["n_estimators"] in param_grids[ModelType.RANDOM_FOREST]["n_estimators"]
    assert rf_params["max_depth"] in param_grids[ModelType.RANDOM_FOREST]["max_depth"]
    assert gb_params["n_estimators"] in param_grids[ModelType.GRADIENT_BOOSTING]["n_estimators"]
    assert gb_params["learning_rate"] in param_grids[ModelType.GRADIENT_BOOSTING]["learning_rate"]
    assert gb_params["max_depth"] in param_grids[ModelType.GRADIENT_BOOSTING]["max_depth"]

    rf_estimator = results[ModelType.RANDOM_FOREST]["estimator"]
    assert rf_estimator.n_estimators == rf_params["n_estimators"]
    assert rf_estimator.max_depth == rf_params["max_depth"]


def test_default_param_grids_are_used_when_no_override_is_given():
    csv_file = make_csv(
        [
            row(age=2 + i % 8, mileage=20000 + i * 500, price=45000 - i * 100, brand=1 + i % 5,
                body=BODY_TYPES[i % 6])
            for i in range(30)
        ]
    )
    df = training.load_and_validate_csv(csv_file)

    results = training.train_and_evaluate(df, cv=2)

    rf_params = results[ModelType.RANDOM_FOREST]["best_params"]
    gb_params = results[ModelType.GRADIENT_BOOSTING]["best_params"]
    assert rf_params["n_estimators"] in training.RF_PARAM_GRID["n_estimators"]
    assert gb_params["max_depth"] in training.GB_PARAM_GRID["max_depth"]
