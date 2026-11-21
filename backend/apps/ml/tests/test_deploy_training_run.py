"""Batch 6B / UC012 steps 7-8: the separate, human-gated "Deploy New
Model Weights" action - apps.ml.views.MLTrainingRunDeployView +
apps.ml.tasks.deploy_training_run. Training-time eligibility itself
(deploy_eligible set without auto-deploying) is covered in
test_training_task.py; this file covers the deploy action itself.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditActionCategory, AuditLog
from apps.ml.models import MLTrainingRun, ModelType, PredictionTarget, ProductionModel
from apps.ml.storage import save_model

pytestmark = pytest.mark.django_db


class DummyEstimator:
    """Same reasoning as test_training_task.py's own DummyEstimator - a
    real, picklable object joblib.dump()/load() can round-trip, without
    needing an actual sklearn fit."""

    def predict(self, X):
        return [1.0] * len(X)


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def eligible_run(tmp_path, settings):
    settings.ML_MODELS_DIR = str(tmp_path)
    file_path = save_model(DummyEstimator(), 1, ModelType.GRADIENT_BOOSTING)
    return MLTrainingRun.objects.create(
        status="succeeded",
        rf_r2=0.83,
        rf_mae=0.25,
        gb_r2=0.91,
        gb_mae=0.2,
        prediction_target=PredictionTarget.LOG_RESALE_PRICE,
        deploy_eligible=True,
        candidate_model_type=ModelType.GRADIENT_BOOSTING,
        candidate_model_file_path=file_path,
    )


def deploy_url(run_id):
    return f"/api/ml/training-runs/{run_id}/deploy/"


def test_deploying_an_eligible_run_hot_swaps_production_and_writes_audit_log(admin_client, eligible_run):
    response = admin_client.post(deploy_url(eligible_run.pk))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["deployed"] is True
    assert response.data["deploy_eligible"] is False

    eligible_run.refresh_from_db()
    assert eligible_run.deployed is True
    assert eligible_run.deployed_model_type == ModelType.GRADIENT_BOOSTING
    assert eligible_run.deploy_eligible is False

    production = ProductionModel.get_singleton()
    assert production.model_type == ModelType.GRADIENT_BOOSTING
    assert production.r2_score == 0.91
    assert production.model_file_path == eligible_run.candidate_model_file_path
    assert production.training_run_id == eligible_run.pk

    log = AuditLog.objects.get(action=AuditActionCategory.UPDATE, resource_type="ml.ProductionModel")
    assert log.after_data["model_type"] == ModelType.GRADIENT_BOOSTING
    assert log.after_data["training_run_id"] == eligible_run.pk


def test_deploying_a_non_eligible_run_rejects_with_a_clean_400(admin_client):
    run = MLTrainingRun.objects.create(status="succeeded", deploy_eligible=False)

    response = admin_client.post(deploy_url(run.pk))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["detail"] == "This run is not eligible for deployment."
    run.refresh_from_db()
    assert run.deployed is False
    production = ProductionModel.get_singleton()
    assert production.model_type == ""


def test_deploying_an_already_deployed_run_rejects_with_a_clean_400_and_no_duplicate_audit_row(
    admin_client, eligible_run
):
    first = admin_client.post(deploy_url(eligible_run.pk))
    assert first.status_code == status.HTTP_200_OK

    second = admin_client.post(deploy_url(eligible_run.pk))

    assert second.status_code == status.HTTP_400_BAD_REQUEST
    assert second.data["detail"] == "This run has already been deployed."
    assert AuditLog.objects.filter(resource_type="ml.ProductionModel").count() == 1


def test_deploy_requires_admin_role(regular_user, eligible_run):
    client = APIClient()
    client.force_authenticate(user=regular_user)

    response = client.post(deploy_url(eligible_run.pk))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    eligible_run.refresh_from_db()
    assert eligible_run.deployed is False


def test_deploying_a_second_eligible_run_clears_the_first_runs_deployed_flag(
    admin_client, eligible_run, tmp_path, settings
):
    """Singleton-pointer bug fix, flagged in the fix prompt: ProductionModel
    only ever points at ONE model, so at most one MLTrainingRun row should
    ever read deployed=True - deploying a second run must clear the first's
    flag, not leave both reading True."""
    settings.ML_MODELS_DIR = str(tmp_path)
    admin_client.post(deploy_url(eligible_run.pk))
    eligible_run.refresh_from_db()
    assert eligible_run.deployed is True

    second_file_path = save_model(DummyEstimator(), 2, ModelType.RANDOM_FOREST)
    second_run = MLTrainingRun.objects.create(
        status="succeeded",
        rf_r2=0.95,
        rf_mae=800.0,
        deploy_eligible=True,
        candidate_model_type=ModelType.RANDOM_FOREST,
        candidate_model_file_path=second_file_path,
    )

    response = admin_client.post(deploy_url(second_run.pk))
    assert response.status_code == status.HTTP_200_OK

    eligible_run.refresh_from_db()
    second_run.refresh_from_db()
    assert eligible_run.deployed is False
    assert second_run.deployed is True

    production = ProductionModel.get_singleton()
    assert production.training_run_id == second_run.pk


def test_deploying_a_run_whose_candidate_file_is_missing_rejects_with_a_clean_400(admin_client, eligible_run):
    eligible_run.candidate_model_file_path = "/nonexistent/path/model.joblib"
    eligible_run.save(update_fields=["candidate_model_file_path"])

    response = admin_client.post(deploy_url(eligible_run.pk))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "no longer available" in response.data["detail"]
    production = ProductionModel.get_singleton()
    assert production.model_type == ""


def test_deploying_a_nonexistent_run_returns_404(admin_client):
    response = admin_client.post(deploy_url(99999))
    assert response.status_code == status.HTTP_404_NOT_FOUND


# --- ML batch 1 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target", [PredictionTarget.LOG_RESALE_PRICE, PredictionTarget.VALUE_RETENTION_RATIO]
)
def test_production_records_the_deployed_runs_own_target(admin_client, eligible_run, target):
    """Was hard-coded to the value-retention ratio whatever the run predicted."""
    eligible_run.prediction_target = target
    eligible_run.save(update_fields=["prediction_target"])

    admin_client.post(deploy_url(eligible_run.pk))

    assert ProductionModel.get_singleton().prediction_target == target
    log = AuditLog.objects.get(resource_type="ml.ProductionModel")
    assert log.after_data["prediction_target"] == target


def test_deploying_a_log_linear_run_records_its_own_r2_and_mae(admin_client, eligible_run):
    """ML batch 2: the third candidate deploys like the other two."""
    from apps.ml.log_linear import LogLinearDepreciationModel
    from apps.ml.storage import save_model as save

    eligible_run.ll_r2, eligible_run.ll_mae = 0.9124, 0.1473
    eligible_run.candidate_model_type = ModelType.LOG_LINEAR
    eligible_run.candidate_model_file_path = save(LogLinearDepreciationModel(), eligible_run.pk, ModelType.LOG_LINEAR)
    eligible_run.save()

    response = admin_client.post(deploy_url(eligible_run.pk))

    assert response.status_code == status.HTTP_200_OK
    production = ProductionModel.get_singleton()
    assert (production.model_type, production.r2_score, production.mae) == (ModelType.LOG_LINEAR, 0.9124, 0.1473)


def test_a_retired_run_can_never_be_deployed(admin_client, eligible_run):
    from django.utils import timezone

    eligible_run.retired_at = timezone.now()
    eligible_run.retired_reason = "Retired: stale deployed flag from before single-deploy was enforced."
    eligible_run.save(update_fields=["retired_at", "retired_reason"])

    response = admin_client.post(deploy_url(eligible_run.pk))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["detail"] == "This run has been retired."
    assert ProductionModel.get_singleton().model_type == ""
    assert not AuditLog.objects.filter(resource_type="ml.ProductionModel").exists()
