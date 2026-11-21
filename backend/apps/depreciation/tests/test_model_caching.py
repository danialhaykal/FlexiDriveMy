"""QA audit M8: predict_resale_curve and explain_resale_prediction each
independently called _load_production_model() -> load_model() (a
joblib.load of the ~1.85MB deployed model file) - build_tco_report calls
both, so a single TCO request loaded the same file from disk twice.
apps/depreciation/inference.py now caches the deserialized estimator in
process, keyed by the production model's own file path (see
inference._model_cache); these tests assert that cache actually works -
at most one real load per request, and no reload at all across requests
while the deployed model is unchanged."""

from decimal import Decimal

import joblib
import pytest

from apps.depreciation import inference
from apps.depreciation.services import build_tco_report
from apps.ml.models import ModelType, PredictionTarget, ProductionModel
from apps.policy.models import InterestRate, MileageBand
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


class WorkingEstimator:
    """Log-price-scale (ML batch 1) fake 'model' - a real joblib round trip
    is what matters here, not what it predicts."""

    def predict(self, feature_rows):
        return [11.0] * len(feature_rows)


@pytest.fixture(autouse=True)
def _reset_model_cache():
    """inference._model_cache is a module-level global - reset it before
    and after every test in this file so one test's cached estimator can
    never leak into another test's call-count assertions."""
    inference._model_cache["path"] = None
    inference._model_cache["estimator"] = None
    yield
    inference._model_cache["path"] = None
    inference._model_cache["estimator"] = None


@pytest.fixture
def brand():
    return Brand.objects.create(name="CachingBrand", tier_code="3")


@pytest.fixture
def vehicle(brand):
    v = VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1498,
    )
    v.refresh_from_db()
    return v


@pytest.fixture
def configured(vehicle, brand):
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    return vehicle


@pytest.fixture
def deployed_model(tmp_path):
    model_path = tmp_path / "model.joblib"
    joblib.dump(WorkingEstimator(), model_path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = str(model_path)
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.save()
    return production


def _counting_load_model(monkeypatch):
    calls = []
    real_load_model = inference.load_model

    def _counted(path):
        calls.append(path)
        return real_load_model(path)

    monkeypatch.setattr(inference, "load_model", _counted)
    return calls


def _request_tco(vehicle, tenure_months=36):
    return build_tco_report(
        vehicle=vehicle,
        tenure_months=tenure_months,
        mileage_band=MileageBand.STANDARD,
        downpayment=Decimal("10000.00"),
    )


def test_build_tco_report_loads_the_model_from_disk_at_most_once(configured, deployed_model, monkeypatch):
    calls = _counting_load_model(monkeypatch)

    report = _request_tco(configured)

    assert report["model_degraded"] is False
    assert len(calls) == 1


def test_a_second_request_with_an_unchanged_production_model_does_not_reload(
    configured, deployed_model, monkeypatch
):
    calls = _counting_load_model(monkeypatch)

    _request_tco(configured, tenure_months=36)
    _request_tco(configured, tenure_months=48)

    assert len(calls) == 1  # ProductionModel.model_file_path never changed - still a cache hit


def test_a_newly_deployed_model_is_picked_up_on_the_very_next_call(
    configured, deployed_model, tmp_path, monkeypatch
):
    """H11's hot-swap must never serve a stale cached estimator -
    invalidation compares the cached path against the CURRENT
    ProductionModel.model_file_path on every call, never a TTL."""
    calls = _counting_load_model(monkeypatch)

    _request_tco(configured)
    assert len(calls) == 1

    new_model_path = tmp_path / "new_model.joblib"
    joblib.dump(WorkingEstimator(), new_model_path)
    production = ProductionModel.get_singleton()
    production.model_file_path = str(new_model_path)
    production.save()

    _request_tco(configured)
    assert len(calls) == 2
    assert calls[1] == str(new_model_path)
