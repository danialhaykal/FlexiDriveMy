"""ML batch 2: the log-linear (hedonic) candidate (apps/ml/log_linear.py)."""

import joblib
import numpy as np
import pandas as pd
import pytest

from apps.ml.features import FEATURE_COLUMNS, feature_frame
from apps.ml.log_linear import RIDGE_ALPHAS, LogLinearDepreciationModel


def frame(rows):
    return feature_frame(pd.DataFrame(rows))


def listing(age, km, tier=2, litres=2.0, body="sedan", recond=0):
    return {"vehicle_age": age, "mileage": km, "brand_code": tier, "engine_litres": litres, "recond": recond,
            "body_type": body}


def sample(n=120, seed=0):
    """Two car models at different price levels, one shared depreciation."""
    rng = np.random.default_rng(seed)
    rows, keys, y = [], [], []
    for i in range(n):
        key = "Brand A" if i % 2 else "Brand B"
        age = float(rng.integers(0, 10))
        km = age * 15000 + rng.normal(0, 3000)
        rows.append(listing(age, km, tier=1 if key == "Brand A" else 3))
        keys.append(key)
        y.append((12.5 if key == "Brand A" else 11.0) - 0.12 * age - 0.01 * km / 10000 + rng.normal(0, 0.02))
    return frame(rows), np.array(y), keys


def test_the_design_columns_mirror_the_reference():
    X, y, keys = sample()
    model = LogLinearDepreciationModel().fit(X, y, keys)

    columns = list(model.design(X.head(2), keys[:2]).columns)

    assert columns == (
        [c for c in FEATURE_COLUMNS if c != "mileage"]
        + ["age_sq", "km_10k"] + [f"age_x_tier{t}" for t in range(1, 6)]
        + ["key=Brand A", "key=Brand B"]
    )
    d = model.design(frame([listing(3, 45000, tier=1)]), ["Brand A"]).iloc[0]
    assert (d["vehicle_age"], d["age_sq"], d["km_10k"]) == (3.0, 9.0, 4.5)
    assert (d["age_x_tier1"], d["age_x_tier2"]) == (3.0, 0.0)
    assert (d["key=Brand A"], d["key=Brand B"]) == (1.0, 0.0)


def test_an_unseen_key_and_no_key_at_all_get_all_zero_key_columns():
    X, y, keys = sample()
    model = LogLinearDepreciationModel().fit(X, y, keys)
    row = frame([listing(2, 30000)])

    unseen = model.design(row, ["Some Other Car"])
    no_key = model.design(row)

    for design in (unseen, no_key):
        assert design[["key=Brand A", "key=Brand B"]].to_numpy().tolist() == [[0.0, 0.0]]
    assert model.predict(row, ["Some Other Car"]) == pytest.approx(model.predict(row))


def test_it_learns_one_age_effect_across_car_models():
    X, y, keys = sample(n=400)
    model = LogLinearDepreciationModel().fit(X, y, keys)
    rows = frame([listing(0, 0, tier=1), listing(1, 15000, tier=1)])

    f0, f1 = model.predict(rows)

    # true per-year change: -0.12 (age) - 0.015 (15,000 km); the level cancels
    assert f1 - f0 == pytest.approx(-0.135, abs=0.03)
    assert model.alpha in RIDGE_ALPHAS


def test_without_model_keys_it_fits_with_no_key_columns():
    X, y, _ = sample()
    model = LogLinearDepreciationModel().fit(X, y, None)

    assert model.key_levels == []
    assert not any(c.startswith("key=") for c in model.design(X).columns)
    assert np.isfinite(model.predict(X)).all()


def test_a_blank_key_gets_no_level_of_its_own():
    X, y, keys = sample()
    keys = [float("nan") if i % 5 == 0 else ("" if i % 7 == 0 else k) for i, k in enumerate(keys)]

    model = LogLinearDepreciationModel().fit(X, y, keys)

    assert model.key_levels == ["Brand A", "Brand B"]


def test_it_saves_and_loads_with_joblib_like_the_other_models(tmp_path):
    X, y, keys = sample()
    model = LogLinearDepreciationModel().fit(X, y, keys)
    path = tmp_path / "ll.joblib"

    joblib.dump(model, path)
    loaded = joblib.load(path)

    assert isinstance(loaded, LogLinearDepreciationModel)
    assert loaded.predict(X.head(5)) == pytest.approx(model.predict(X.head(5)))
