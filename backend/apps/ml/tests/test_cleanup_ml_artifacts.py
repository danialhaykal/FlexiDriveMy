"""QA audit L18: cleanup_ml_artifacts deletes dataset/model files no
longer referenced by anything worth keeping, and never touches the
currently-deployed model or a recent run's own files."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.ml.models import MLTrainingRun, ModelType, ProductionModel

pytestmark = pytest.mark.django_db


def test_deletes_an_old_unreferenced_file(tmp_path, settings):
    settings.ML_DATASET_UPLOAD_DIR = str(tmp_path)
    settings.ML_MODELS_DIR = str(tmp_path / "models")
    (tmp_path / "models").mkdir()

    orphan = tmp_path / "orphan_dataset.csv"
    orphan.write_text("vehicle_age,mileage,resale_price,brand_code,msrp_proxy\n")

    call_command("cleanup_ml_artifacts", "--keep-days=30")

    assert not orphan.exists()


def test_never_deletes_the_currently_deployed_model(tmp_path, settings):
    settings.ML_DATASET_UPLOAD_DIR = str(tmp_path / "datasets")
    settings.ML_MODELS_DIR = str(tmp_path)
    (tmp_path / "datasets").mkdir()

    deployed = tmp_path / "deployed_model.joblib"
    deployed.write_bytes(b"fake")
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = str(deployed)
    production.save()

    call_command("cleanup_ml_artifacts", "--keep-days=30")

    assert deployed.exists()


def test_never_deletes_a_recent_runs_dataset_file(tmp_path, settings):
    settings.ML_DATASET_UPLOAD_DIR = str(tmp_path)
    settings.ML_MODELS_DIR = str(tmp_path / "models")
    (tmp_path / "models").mkdir()

    recent_dataset = tmp_path / "recent_upload.csv"
    recent_dataset.write_text("vehicle_age,mileage,resale_price,brand_code,msrp_proxy\n")
    MLTrainingRun.objects.create(dataset_filename="recent_upload.csv", dataset_path=str(recent_dataset))

    call_command("cleanup_ml_artifacts", "--keep-days=30")

    assert recent_dataset.exists()


def test_deletes_an_old_runs_dataset_file_past_keep_days(tmp_path, settings):
    settings.ML_DATASET_UPLOAD_DIR = str(tmp_path)
    settings.ML_MODELS_DIR = str(tmp_path / "models")
    (tmp_path / "models").mkdir()

    old_dataset = tmp_path / "old_upload.csv"
    old_dataset.write_text("vehicle_age,mileage,resale_price,brand_code,msrp_proxy\n")
    run = MLTrainingRun.objects.create(dataset_filename="old_upload.csv", dataset_path=str(old_dataset))
    MLTrainingRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(days=60))

    call_command("cleanup_ml_artifacts", "--keep-days=30")

    assert not old_dataset.exists()


def test_never_deletes_a_pending_deploy_candidates_file_regardless_of_age(tmp_path, settings):
    """Follow-up fix to a Batch 6B gap: a run that cleared both deployment
    gates (deploy_eligible=True) but hasn't been deployed yet must keep
    its candidate file indefinitely, not just within --keep-days - an
    admin can review and deploy it at any point, and deleting it out from
    under a pending Deploy action would silently make that action 400
    with "candidate model file is no longer available" for no real
    reason (the candidate itself was never actually stale)."""
    settings.ML_DATASET_UPLOAD_DIR = str(tmp_path / "datasets")
    settings.ML_MODELS_DIR = str(tmp_path)
    (tmp_path / "datasets").mkdir()

    candidate = tmp_path / "candidate_model.joblib"
    candidate.write_bytes(b"fake")
    run = MLTrainingRun.objects.create(
        deploy_eligible=True,
        deployed=False,
        candidate_model_type=ModelType.RANDOM_FOREST,
        candidate_model_file_path=str(candidate),
    )
    MLTrainingRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(days=60))

    call_command("cleanup_ml_artifacts", "--keep-days=30")

    assert candidate.exists()


def test_deletes_an_old_rejected_runs_candidate_file_same_as_before_this_fix(tmp_path, settings):
    """The negative case: a run that never cleared the deployment gates
    (deploy_eligible=False) has no "pending Deploy action" to protect -
    its candidate_model_file_path is blank, and old orphaned files
    unrelated to any pending action are still cleaned up normally."""
    settings.ML_DATASET_UPLOAD_DIR = str(tmp_path / "datasets")
    settings.ML_MODELS_DIR = str(tmp_path)
    (tmp_path / "datasets").mkdir()

    rejected_run_file = tmp_path / "rejected_run_model.joblib"
    rejected_run_file.write_bytes(b"fake")
    run = MLTrainingRun.objects.create(deploy_eligible=False, deployed=False)
    MLTrainingRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(days=60))

    call_command("cleanup_ml_artifacts", "--keep-days=30")

    assert not rejected_run_file.exists()


def test_deletes_an_already_deployed_runs_old_candidate_file(tmp_path, settings):
    """Once deployed, a candidate's file is no longer "pending" - it
    follows the normal age-based rule like any other file (the currently
    deployed model itself is protected separately via ProductionModel.
    model_file_path, not via this candidate-path set)."""
    settings.ML_DATASET_UPLOAD_DIR = str(tmp_path / "datasets")
    settings.ML_MODELS_DIR = str(tmp_path)
    (tmp_path / "datasets").mkdir()

    old_deployed_candidate = tmp_path / "superseded_model.joblib"
    old_deployed_candidate.write_bytes(b"fake")
    run = MLTrainingRun.objects.create(
        deploy_eligible=False,
        deployed=True,
        candidate_model_type=ModelType.RANDOM_FOREST,
        candidate_model_file_path=str(old_deployed_candidate),
    )
    MLTrainingRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(days=60))

    call_command("cleanup_ml_artifacts", "--keep-days=30")

    assert not old_deployed_candidate.exists()


def test_dry_run_reports_without_deleting(tmp_path, settings):
    settings.ML_DATASET_UPLOAD_DIR = str(tmp_path)
    settings.ML_MODELS_DIR = str(tmp_path / "models")
    (tmp_path / "models").mkdir()

    orphan = tmp_path / "orphan_dataset.csv"
    orphan.write_text("vehicle_age,mileage,resale_price,brand_code,msrp_proxy\n")

    call_command("cleanup_ml_artifacts", "--keep-days=30", "--dry-run")

    assert orphan.exists()
