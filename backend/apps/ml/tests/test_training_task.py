import math
import os

import pytest

from apps.ml.models import MLTrainingRun, ModelType, PredictionTarget, ProductionModel, TrainingRunStatus
from apps.ml.tasks import run_training_task
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db


class DummyEstimator:
    """Simple picklable stand-in fitted estimator for deploy-path tests -
    a real object joblib.dump() can serialize, without needing an actual
    (slow) sklearn fit. ML batch 2: its log price falls 0.13 a year (keeps
    about 88% after 12 months and 52% after 60), so the winner passes the
    curve check unless a test says otherwise."""

    def predict(self, X):
        return [math.log(80000) - 0.13 * age for age in X["vehicle_age"]]


class FlatEstimator:
    """Keeps 100% of the price for ever - fails the curve check."""

    def predict(self, X):
        return [11.0] * len(X)


@pytest.fixture(autouse=True)
def catalog_car():
    """ML batch 2: the curve check reads the active catalog cars the forecast covers."""
    brand = Brand.objects.create(name="TaskBrand", tier_code="2")
    return VehicleModel.objects.create(
        brand=brand, name="Sedan", trim="X", body_segment=BodySegment.SEDAN, msrp="200000.00",
        engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998,
    )


def _default_csv_content():
    # QA audit M10: run_training_task now re-validates the minimum row
    # count (>= training.MIN_TRAINING_ROWS) before calling
    # train_and_evaluate, even though that function is monkeypatched in
    # most of this file's tests - the real load_and_validate_csv call
    # still runs first, against this real CSV, so it needs enough rows to
    # clear that gate on its own.
    header = "vehicle_age,mileage,resale_price,brand_code,engine_litres,body_type,recond\n"
    rows = "\n".join(
        f"{2 + i % 8},{20000 + i * 500},{45000 - i * 100},{1 + i % 5},2.0,sedan,0" for i in range(30)
    )
    return header + rows + "\n"


@pytest.fixture
def make_run(tmp_path):
    def _make_run(csv_content=None):
        dataset_path = tmp_path / "dataset.csv"
        dataset_path.write_text(csv_content if csv_content is not None else _default_csv_content())
        return MLTrainingRun.objects.create(dataset_filename="dataset.csv", dataset_path=str(dataset_path))

    return _make_run


def fake_results(rf_r2, gb_r2, ll_r2=0.5, winner_estimator=None):
    """Three candidates (ML batch 2). The log-linear defaults to a low R² so
    the RF/GB scenarios below keep their winner."""
    results = {
        ModelType.RANDOM_FOREST: {
            "estimator": DummyEstimator(),
            "r2": rf_r2,
            "mae": 1000.0,
            "within_model_r2": 0.55,
            "best_params": {"n_estimators": 200, "max_depth": None},
        },
        ModelType.GRADIENT_BOOSTING: {
            "estimator": DummyEstimator(),
            "r2": gb_r2,
            "mae": 1100.0,
            "within_model_r2": 0.65,
            "best_params": {"n_estimators": 100, "learning_rate": 0.1, "max_depth": 3},
        },
        ModelType.LOG_LINEAR: {
            "estimator": DummyEstimator(),
            "r2": ll_r2,
            "mae": 0.15,
            "within_model_r2": 0.72,
            "best_params": {"alpha": 0.3857},
        },
    }
    if winner_estimator is not None:
        for result in results.values():
            result["estimator"] = winner_estimator
    return results


# --- R^2 >= 0.80 gate, end to end through the task (UC012 Rule 1) ----------


def test_low_r2_retrain_keeps_old_model_deployed_and_reports_rejection(make_run, monkeypatch):
    old_production = ProductionModel.get_singleton()
    old_production.model_type = ModelType.RANDOM_FOREST
    old_production.model_file_path = "/existing/old_model.joblib"
    old_production.r2_score = 0.92
    old_production.save()

    run = make_run()
    monkeypatch.setattr(
        "apps.ml.tasks.training_module.train_and_evaluate",
        lambda df: fake_results(rf_r2=0.55, gb_r2=0.60),
    )

    run_training_task(run.pk)

    run.refresh_from_db()
    assert run.status == TrainingRunStatus.SUCCEEDED
    assert run.deployed is False
    assert run.deployed_model_type == ""
    assert "0.80" in run.rejection_reason
    assert run.rf_r2 == 0.55
    assert run.gb_r2 == 0.60

    old_production.refresh_from_db()
    assert old_production.model_file_path == "/existing/old_model.joblib"
    assert old_production.model_type == ModelType.RANDOM_FOREST
    assert old_production.r2_score == 0.92


def test_candidate_clearing_080_but_not_beating_production_is_rejected(make_run, monkeypatch):
    """QA audit H11 end to end through the real task: a candidate that
    clears the fixed 0.80 floor must ALSO beat (or tie) whatever's
    currently deployed - previously only the 0.80 floor was checked here
    at all, so this exact scenario (a mediocre retrain replacing a
    genuinely better production model) was the live bug.
    """
    old_production = ProductionModel.get_singleton()
    old_production.model_type = ModelType.GRADIENT_BOOSTING
    old_production.model_file_path = "/existing/good_model.joblib"
    # ML batch 1: the comparison applies only to a production model with the
    # same target as the candidate (the log resale price).
    old_production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    old_production.r2_score = 0.93
    old_production.save()

    run = make_run()
    monkeypatch.setattr(
        "apps.ml.tasks.training_module.train_and_evaluate",
        lambda df: fake_results(rf_r2=0.84, gb_r2=0.81),
    )

    run_training_task(run.pk)

    run.refresh_from_db()
    assert run.status == TrainingRunStatus.SUCCEEDED
    assert run.deployed is False
    assert run.deployed_model_type == ""
    # Names the comparison, not just "below 0.80" - this run's own R^2
    # (0.84) genuinely clears the operational floor.
    assert "0.93" in run.rejection_reason
    assert "0.84" in run.rejection_reason
    assert "does not improve" in run.rejection_reason

    old_production.refresh_from_db()
    assert old_production.model_file_path == "/existing/good_model.joblib"
    assert old_production.model_type == ModelType.GRADIENT_BOOSTING
    assert old_production.r2_score == 0.93


def test_high_r2_retrain_marks_deploy_eligible_but_does_not_auto_deploy(make_run, monkeypatch, admin_user):
    """Batch 6B: clearing both gates used to deploy immediately (see the
    git history of this test's old name,
    test_high_r2_retrain_deploys_the_better_of_the_two_models) - UC012's
    actual main flow has train+evaluate and the "admin clicks Deploy New
    Model Weights" step as two SEPARATE, human-gated actions. Training
    alone must now only save the winning estimator to disk and flag the
    run eligible; ProductionModel stays untouched until the new deploy
    endpoint (apps.ml.tasks.deploy_training_run) is actually called.
    """
    run = make_run()
    monkeypatch.setattr(
        "apps.ml.tasks.training_module.train_and_evaluate",
        lambda df: fake_results(rf_r2=0.83, gb_r2=0.91),
    )

    run_training_task(run.pk, actor_id=admin_user.id, ip_address="127.0.0.1")

    run.refresh_from_db()
    assert run.status == TrainingRunStatus.SUCCEEDED
    assert run.deployed is False
    assert run.deployed_model_type == ""
    assert run.deploy_eligible is True
    assert run.candidate_model_type == ModelType.GRADIENT_BOOSTING
    assert run.candidate_model_file_path
    assert os.path.exists(run.candidate_model_file_path)
    assert run.rf_best_params == {"n_estimators": 200, "max_depth": None}
    assert run.gb_best_params == {"n_estimators": 100, "learning_rate": 0.1, "max_depth": 3}

    production = ProductionModel.get_singleton()
    assert production.model_type == ""
    assert production.r2_score is None


def test_training_alone_never_writes_a_productionmodel_audit_log_entry(make_run, monkeypatch, admin_user):
    """Batch 6B: the audit row for a ProductionModel change now only ever
    comes from an actual deploy (apps.ml.tasks.deploy_training_run) - see
    test_deploy_training_run.py. Training a run that clears both gates
    must not write one on its own."""
    from apps.audit.models import AuditLog

    run = make_run()
    monkeypatch.setattr(
        "apps.ml.tasks.training_module.train_and_evaluate",
        lambda df: fake_results(rf_r2=0.90, gb_r2=0.85),
    )

    run_training_task(run.pk, actor_id=admin_user.id, ip_address="10.0.0.1")

    assert not AuditLog.objects.filter(resource_type="ml.ProductionModel").exists()


def test_rejected_retrain_does_not_write_an_audit_log_entry(make_run, monkeypatch):
    from apps.audit.models import AuditLog

    run = make_run()
    monkeypatch.setattr(
        "apps.ml.tasks.training_module.train_and_evaluate",
        lambda df: fake_results(rf_r2=0.40, gb_r2=0.30),
    )

    run_training_task(run.pk)

    assert not AuditLog.objects.filter(resource_type="ml.ProductionModel").exists()


def test_rejected_retrain_is_not_deploy_eligible(make_run, monkeypatch):
    run = make_run()
    monkeypatch.setattr(
        "apps.ml.tasks.training_module.train_and_evaluate",
        lambda df: fake_results(rf_r2=0.40, gb_r2=0.30),
    )

    run_training_task(run.pk)

    run.refresh_from_db()
    assert run.deploy_eligible is False
    assert run.candidate_model_type == ""
    assert run.candidate_model_file_path == ""


# --- ML batch 1: the run records its target and both R² values; the second gate
# compares only R² measured on the same target --------------------------------------


def _production_holding(target, r2):
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = "/existing/run5_model.joblib"
    production.prediction_target = target
    production.r2_score = r2
    production.save()
    return production


def test_the_run_records_its_target_and_both_within_model_r2_values(make_run, monkeypatch):
    run = make_run()
    monkeypatch.setattr("apps.ml.tasks.training_module.train_and_evaluate", lambda df: fake_results(0.86, 0.88))

    run_training_task(run.pk)

    run.refresh_from_db()
    assert run.prediction_target == PredictionTarget.LOG_RESALE_PRICE
    assert (run.rf_within_model_r2, run.gb_within_model_r2) == (0.55, 0.65)


def test_a_raw_price_production_model_does_not_block_a_log_price_candidate(make_run, monkeypatch):
    """Run 5 (raw price, R² 0.892) is not comparable with a log-price R²."""
    _production_holding(PredictionTarget.RAW_RESALE_PRICE, 0.892)
    run = make_run()
    monkeypatch.setattr("apps.ml.tasks.training_module.train_and_evaluate", lambda df: fake_results(0.83, 0.85))

    run_training_task(run.pk)

    run.refresh_from_db()
    assert run.deploy_eligible is True
    assert run.rejection_reason == ""
    assert run.candidate_model_type == ModelType.GRADIENT_BOOSTING


def test_a_same_target_production_model_that_scores_higher_still_wins(make_run, monkeypatch):
    _production_holding(PredictionTarget.LOG_RESALE_PRICE, 0.90)
    run = make_run()
    monkeypatch.setattr("apps.ml.tasks.training_module.train_and_evaluate", lambda df: fake_results(0.83, 0.85))

    run_training_task(run.pk)

    run.refresh_from_db()
    assert run.deploy_eligible is False
    assert run.rejection_reason == (
        # Run 3 fix batch 5 (F-26): the model's name, not its key (was "from gradient_boosting").
        "Best validation R² (0.8500 from Gradient Boosting) clears the 0.80 threshold but does not improve on "
        "the currently deployed production model's R² (0.9000); keeping the current production model."
    )


# --- ML batch 2: three candidates and the curve check ----------------------------------


def test_all_three_candidates_are_recorded_and_the_log_linear_can_win(make_run, monkeypatch):
    run = make_run()
    monkeypatch.setattr(
        "apps.ml.tasks.training_module.train_and_evaluate", lambda df: fake_results(0.86, 0.88, ll_r2=0.91)
    )

    run_training_task(run.pk)

    run.refresh_from_db()
    assert (run.rf_r2, run.gb_r2, run.ll_r2) == (0.86, 0.88, 0.91)
    assert (run.ll_mae, run.ll_within_model_r2, run.ll_best_params) == (0.15, 0.72, {"alpha": 0.3857})
    assert run.curve_check_passed is True and run.curve_check_report == []
    assert run.deploy_eligible is True
    assert run.candidate_model_type == ModelType.LOG_LINEAR
    assert "log_linear" in os.path.basename(run.candidate_model_file_path)


def test_a_winner_that_fails_the_curve_check_is_not_deploy_eligible(make_run, monkeypatch):
    run = make_run()
    monkeypatch.setattr(
        "apps.ml.tasks.training_module.train_and_evaluate",
        lambda df: fake_results(0.86, 0.88, winner_estimator=FlatEstimator()),
    )

    run_training_task(run.pk)

    run.refresh_from_db()
    assert run.curve_check_passed is False
    assert run.curve_check_report == [
        "TaskBrand Sedan X: keeps 100.0% after 12 months (limit 95%)",
        "TaskBrand Sedan X: keeps 100.0% after 60 months (allowed 20%-75%)",
    ]
    assert run.deploy_eligible is False
    assert run.candidate_model_file_path == ""
    assert run.rejection_reason == (
        "Curve check failed: TaskBrand Sedan X: keeps 100.0% after 12 months (limit 95%) (+1 more)"
    )


def test_with_no_catalog_car_to_check_the_run_is_not_eligible(make_run, monkeypatch, catalog_car):
    catalog_car.powertrain = "bev"
    catalog_car.engine_capacity_cc = None
    catalog_car.save()  # the only car is electric: nothing the forecast covers
    run = make_run()
    monkeypatch.setattr("apps.ml.tasks.training_module.train_and_evaluate", lambda df: fake_results(0.86, 0.88))

    run_training_task(run.pk)

    run.refresh_from_db()
    assert run.curve_check_report == ["no catalog car to check"]
    assert run.deploy_eligible is False
    assert run.rejection_reason == "Curve check failed: no catalog car to check"


def test_a_gate_failure_keeps_its_own_reason_and_still_records_the_curve_check(make_run, monkeypatch):
    run = make_run()
    monkeypatch.setattr(
        "apps.ml.tasks.training_module.train_and_evaluate",
        lambda df: fake_results(0.55, 0.60, winner_estimator=FlatEstimator()),
    )

    run_training_task(run.pk)

    run.refresh_from_db()
    assert "below the required 0.80 threshold" in run.rejection_reason
    assert run.curve_check_passed is False


# --- Malformed dataset discovered at task time (defense in depth) ---------


def test_malformed_dataset_at_task_time_marks_run_failed(make_run):
    run = make_run(csv_content="vehicle_age,mileage,resale_price\n2,20000,45000\n")  # missing brand_code

    with pytest.raises(Exception):
        run_training_task(run.pk)

    run.refresh_from_db()
    assert run.status == TrainingRunStatus.FAILED
    assert "Missing required columns" in run.error_message
