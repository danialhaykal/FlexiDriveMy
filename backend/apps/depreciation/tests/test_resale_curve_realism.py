"""QA audit C8, item 4: "tests that pass while the feature is broken" -
the gap the audit named was that nothing actually loaded the REAL deployed
model and checked its output against the one property that genuinely
can't be false for a used car: it never resells for more than it cost new,
and it never gets more valuable with age. Every other inference test in
this package uses a hand-built fake estimator (WorkingEstimator,
DecliningResaleEstimator) with a known, controlled output - useful for
testing predict_resale_curve's own plumbing, but none of them would have
caught a real RandomForest/GradientBoosting trained on the real dataset
actually extrapolating past msrp or non-monotonically. This file trains a
real estimator against the real apps/ml/data/real_historical_pricing.csv
(983 rows since ML batch 1's build v2) - the same file
apps/ml/management/commands/run_real_retrain.py retrains production
against - deploys it for real, and asserts the sanity-clamp property end
to end for several vehicles spanning different price points, brand tiers,
body types and mileage bands.
"""

from decimal import Decimal
from pathlib import Path

import joblib
import pytest

from apps.depreciation import formulas, inference
from apps.ml import training
from apps.ml.models import ModelType, PredictionTarget, ProductionModel
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db

REAL_DATASET_PATH = Path(__file__).resolve().parents[3] / "apps" / "ml" / "data" / "real_historical_pricing.csv"

# A single-candidate grid per model type - this is still a real fit
# against the real 888-row dataset (not a mock), just without
# train_and_evaluate's full production grid search, so this test suite
# stays fast - the same "keep it fast without changing what's genuinely
# being exercised" reasoning apps/ml/tests/test_training.py's own
# make_learnable_dataset tests already use.
_FAST_GRIDS = {
    ModelType.RANDOM_FOREST: {"n_estimators": [100], "max_depth": [8]},
    ModelType.GRADIENT_BOOSTING: {"n_estimators": [100], "learning_rate": [0.1], "max_depth": [3]},
}


@pytest.fixture(scope="module")
def real_trained_estimator():
    """Deliberately does NOT assert should_deploy here: whether a model is
    accurate enough to trust in production (the 0.80 gate, checked in
    apps/ml) and whether its output obeys basic physical constraints are
    two different properties; this fixture exercises the second one using
    whichever candidate scored best, independent of the first.
    """
    with open(REAL_DATASET_PATH, "rb") as dataset_file:
        df = training.load_and_validate_csv(dataset_file)
    results = training.train_and_evaluate(df, cv=3, param_grids=_FAST_GRIDS)
    best_type, best, _, _ = training.pick_best_and_decide_deployment(results)
    return best["estimator"]


@pytest.fixture
def deployed_real_model(real_trained_estimator, tmp_path):
    model_path = tmp_path / "real_model.joblib"
    joblib.dump(real_trained_estimator, model_path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = str(model_path)
    # ML batch 1: train_and_evaluate fits the log resale price - the one
    # target inference accepts.
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.save()
    return production


def _make_vehicle(*, brand_name, tier_code, msrp, body_segment, engine_capacity_cc):
    brand = Brand.objects.create(name=brand_name, tier_code=tier_code)
    vehicle = VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=body_segment,
        msrp=msrp, engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=engine_capacity_cc,
    )
    vehicle.refresh_from_db()
    return vehicle


@pytest.mark.parametrize(
    "brand_name, tier_code, msrp, body_segment, engine_capacity_cc, annual_mileage_km",
    [
        ("RealismPremium", "1", "400000.00", BodySegment.SUV, 2995, Decimal("8000")),  # premium, low mileage
        ("RealismMid", "3", "120000.00", BodySegment.SEDAN, 1998, Decimal("17500")),  # mid tier, high mileage
        ("RealismBudget", "5", "60000.00", BodySegment.HATCHBACK, 1496, Decimal("25000")),  # budget, very high
        ("RealismMpv", "1", "548000.00", BodySegment.MPV, 2393, Decimal("15000")),  # an Alphard-like MPV
    ],
)
def test_real_deployed_model_curve_never_exceeds_msrp_and_never_increases(
    deployed_real_model, brand_name, tier_code, msrp, body_segment, engine_capacity_cc, annual_mileage_km
):
    vehicle = _make_vehicle(
        brand_name=brand_name, tier_code=tier_code, msrp=msrp, body_segment=body_segment,
        engine_capacity_cc=engine_capacity_cc,
    )

    values, degraded, reason = inference.predict_resale_curve(
        vehicle=vehicle, annual_mileage_km=annual_mileage_km
    )

    assert degraded is False, reason
    assert len(values) == formulas.HORIZON_MONTHS + 1
    # ML batch 1: month 0 is the car's own price by construction (exp(0) = 1).
    assert values[0] == vehicle.msrp
    assert values[60] < vehicle.msrp

    # The exact property the audit named: "nothing checks the output."
    assert all(value <= vehicle.msrp for value in values), (
        f"month-by-month values exceeded msrp ({vehicle.msrp}): {values}"
    )
    assert all(values[month] >= values[month + 1] for month in range(len(values) - 1)), (
        f"curve was not non-increasing: {values}"
    )
