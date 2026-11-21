import math
import time
from decimal import Decimal

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor

from apps.depreciation import inference
from apps.ml.features import BODY_TYPES, feature_frame
from apps.ml.log_linear import LogLinearDepreciationModel
from apps.ml.models import ModelType, PredictionTarget, ProductionModel
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db

FACTORS = {"vehicle_age", "mileage", "brand_code", "engine_litres", "body_type", "recond"}


@pytest.fixture
def vehicle():
    # tier_code must be a real, parseable value and the car needs an engine cc
    # - inference.py degrades otherwise (see the tests at the bottom).
    brand = Brand.objects.create(name="ExplainBrand", tier_code="3")
    v = VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    v.refresh_from_db()
    return v


def fit_log_price_estimator(estimator_cls, n=300):
    """A genuinely fitted tree-based regressor on the ML batch 1 features
    (apps.ml.features.feature_frame) and the LOG resale price - SHAP's
    TreeExplainer introspects real tree structure, so this can't be faked."""
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "vehicle_age": rng.uniform(0, 10, n),
        "mileage": rng.uniform(0, 200000, n),
        "brand_code": rng.integers(1, 6, n).astype(float),
        "engine_litres": rng.choice([1.5, 2.0, 2.5, 3.0], n),
        "recond": rng.integers(0, 2, n).astype(float),
        "body_type": rng.choice(BODY_TYPES, n),
    })
    y = (
        12.5 - 0.12 * df["vehicle_age"] - df["mileage"] * 0.000001 - 0.2 * df["brand_code"]
        + 0.15 * df["engine_litres"] + 0.1 * (df["body_type"] == "suv") - 0.05 * df["recond"]
    )
    if estimator_cls is LogLinearDepreciationModel:
        # ML batch 2: the hedonic candidate, fitted without model keys.
        return LogLinearDepreciationModel().fit(feature_frame(df), y, None)
    if estimator_cls is RandomForestRegressor:
        estimator = estimator_cls(n_estimators=50, random_state=42)
    else:
        estimator = estimator_cls(random_state=42)
    estimator.fit(feature_frame(df), y)
    return estimator


def _deploy(tmp_path, estimator, target=PredictionTarget.LOG_RESALE_PRICE):
    model_path = tmp_path / "model.joblib"
    joblib.dump(estimator, model_path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = str(model_path)
    production.prediction_target = target
    production.save()


# --- additivity, and that the parts describe the curve's own maths --------


@pytest.mark.parametrize("estimator_cls", [RandomForestRegressor, GradientBoostingRegressor, LogLinearDepreciationModel])
@pytest.mark.parametrize("month", [36, 30])
def test_additivity_holds_for_all_three_model_types(vehicle, tmp_path, estimator_cls, month):
    """ML batch 2: month 30 sits halfway between years 2 and 3, so the
    explanation must follow the curve's own interpolation, f(30) = f(2) +
    0.5 x (f(3) - f(2))."""
    estimator = fit_log_price_estimator(estimator_cls)
    _deploy(tmp_path, estimator)

    explanation = inference.explain_resale_prediction(
        vehicle=vehicle, annual_mileage_km=Decimal("15000"), month=month
    )

    assert explanation is not None
    assert set(explanation["contributions"]) == FACTORS
    # The body one-hots are one factor, never six.
    assert not any(name.startswith("body_") and name != "body_type" for name in explanation["contributions"])

    # base = the new price; base + every contribution = the prediction.
    assert explanation["base_value"] == 100000.0
    reconstructed = explanation["base_value"] + sum(explanation["contributions"].values())
    assert reconstructed == pytest.approx(explanation["predicted_value"], abs=1e-6)

    # And predicted_value is msrp x exp(f(m) - f(0)) from the model itself - the
    # same quantity the curve uses before its clamp.
    car, _ = inference._resolve_car_features(vehicle)
    f = estimator.predict(inference._build_feature_rows(15000, car))
    f_month = f[2] + 0.5 * (f[3] - f[2]) if month == 30 else f[3]
    assert explanation["predicted_value"] == pytest.approx(100000.0 * math.exp(f_month - f[0]), rel=1e-7)
    monthly = inference.monthly_log_prices(f)
    if all(monthly[m] >= monthly[m + 1] for m in range(month)):
        # nothing was clamped up to this month, so the card and the curve show the same value
        values, _, _ = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))
        assert float(values[month]) == pytest.approx(explanation["predicted_value"], abs=0.006)


def test_the_log_linear_explanation_is_exact_per_design_column(vehicle, tmp_path):
    model = fit_log_price_estimator(LogLinearDepreciationModel)
    _deploy(tmp_path, model)

    explanation = inference.explain_resale_prediction(vehicle=vehicle, annual_mileage_km=Decimal("15000"), month=24)

    car, _ = inference._resolve_car_features(vehicle)
    design = model.design(inference._build_feature_rows(15000, car, years=[0, 2]))
    delta = dict(zip(design.columns, model.ridge.coef_ * (design.iloc[1] - design.iloc[0]).to_numpy()))
    age = sum(delta[c] for c in ("vehicle_age", "age_sq", "age_x_tier1", "age_x_tier2", "age_x_tier3",
                                 "age_x_tier4", "age_x_tier5"))
    total = age + delta["km_10k"]
    change = explanation["predicted_value"] - 100000.0
    assert explanation["contributions"]["vehicle_age"] == pytest.approx(change * age / total)
    assert explanation["contributions"]["mileage"] == pytest.approx(change * delta["km_10k"] / total)
    # Same in both rows, so exactly nothing:
    for factor in ("brand_code", "engine_litres", "body_type", "recond"):
        assert explanation["contributions"][factor] == 0.0


def test_a_zero_change_gives_zero_contributions(vehicle, tmp_path):
    """month 0: f_m - f_0 = 0, so nothing moved the value."""
    _deploy(tmp_path, fit_log_price_estimator(GradientBoostingRegressor))

    explanation = inference.explain_resale_prediction(vehicle=vehicle, annual_mileage_km=Decimal("15000"), month=0)

    assert explanation["predicted_value"] == 100000.0
    assert set(explanation["contributions"].values()) == {0.0}


def test_the_shares_are_proportional_to_the_log_scale_shap_differences(vehicle, tmp_path):
    import shap

    estimator = fit_log_price_estimator(RandomForestRegressor)
    _deploy(tmp_path, estimator)

    explanation = inference.explain_resale_prediction(vehicle=vehicle, annual_mileage_km=Decimal("15000"), month=48)

    car, _ = inference._resolve_car_features(vehicle)
    rows = inference._build_feature_rows(15000, car, years=[0, 4])
    phi = shap.TreeExplainer(estimator).shap_values(rows)
    delta = dict(zip(rows.columns, phi[1] - phi[0]))
    total = sum(delta.values())
    change = explanation["predicted_value"] - 100000.0
    assert explanation["contributions"]["vehicle_age"] == pytest.approx(change * delta["vehicle_age"] / total)
    body = sum(v for k, v in delta.items() if k.startswith("body_"))
    assert explanation["contributions"]["body_type"] == pytest.approx(change * body / total)


# --- Degrades to None, never raises (same philosophy as predict_resale_curve) --


def test_no_production_model_deployed_returns_none(vehicle):
    explanation = inference.explain_resale_prediction(
        vehicle=vehicle, annual_mileage_km=Decimal("15000"), month=36
    )
    assert explanation is None


@pytest.mark.parametrize(
    "target", ["", PredictionTarget.VALUE_RETENTION_RATIO, PredictionTarget.RAW_RESALE_PRICE]
)
def test_any_other_prediction_target_returns_none_even_though_the_file_loads_fine(vehicle, tmp_path, target):
    """A blank target (unknown) or an older target is incompatible - never
    assumed compatible just because the file loads."""
    _deploy(tmp_path, fit_log_price_estimator(RandomForestRegressor), target=target)

    explanation = inference.explain_resale_prediction(
        vehicle=vehicle, annual_mileage_km=Decimal("15000"), month=36
    )
    assert explanation is None


def test_model_file_missing_on_disk_returns_none(vehicle):
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = "/this/path/does/not/exist.joblib"
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.save()

    explanation = inference.explain_resale_prediction(
        vehicle=vehicle, annual_mileage_km=Decimal("15000"), month=36
    )
    assert explanation is None


def test_shap_computation_error_returns_none(vehicle, tmp_path, monkeypatch):
    _deploy(tmp_path, fit_log_price_estimator(RandomForestRegressor))

    def _raise(model, feature_rows):
        raise RuntimeError("shap blew up")

    monkeypatch.setattr(inference, "_run_shap_explanation", _raise)

    explanation = inference.explain_resale_prediction(
        vehicle=vehicle, annual_mileage_km=Decimal("15000"), month=36
    )
    assert explanation is None


def test_shap_timeout_returns_none_without_waiting_for_the_full_hang(vehicle, tmp_path, monkeypatch, settings):
    _deploy(tmp_path, fit_log_price_estimator(RandomForestRegressor))
    settings.ML_INFERENCE_TIMEOUT_SECONDS = 0.05

    def _hang(model, feature_rows):
        time.sleep(2)
        return 0.0, [[0.0] * 11, [0.0] * 11, [0.0] * 11]

    monkeypatch.setattr(inference, "_run_shap_explanation", _hang)

    started = time.monotonic()
    explanation = inference.explain_resale_prediction(
        vehicle=vehicle, annual_mileage_km=Decimal("15000"), month=36
    )
    elapsed = time.monotonic() - started

    assert explanation is None
    assert elapsed < 1.0


def _car(brand, **fields):
    defaults = dict(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN, msrp="100000.00",
        engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    defaults.update(fields)
    vehicle = VehicleModel.objects.create(**defaults)
    vehicle.refresh_from_db()
    return vehicle


def test_blank_tier_code_returns_none_even_with_a_working_model_deployed(tmp_path):
    vehicle = _car(Brand.objects.create(name="NoTierBrand", tier_code=""))
    _deploy(tmp_path, fit_log_price_estimator(RandomForestRegressor))

    explanation = inference.explain_resale_prediction(
        vehicle=vehicle, annual_mileage_km=Decimal("15000"), month=36
    )
    assert explanation is None


def test_an_electric_car_is_never_explained(tmp_path):
    vehicle = _car(Brand.objects.create(name="EvBrand", tier_code="2"), powertrain="bev",
                   engine_capacity_cc=None, engine_capacity_kw="250.00")
    _deploy(tmp_path, fit_log_price_estimator(RandomForestRegressor))

    assert inference.explain_resale_prediction(vehicle=vehicle, annual_mileage_km=15000, month=36) is None
