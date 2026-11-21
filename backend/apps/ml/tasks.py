from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditActionCategory
from apps.audit.services import log_runtime_error, write_audit_log

from . import curve_check
from . import training as training_module
from .models import MLTrainingRun, ModelType, ProductionModel, TrainingRunStatus
from .storage import load_model, save_model

def curve_check_annual_km():
    """The standard band's representative mileage - the one the forecast uses
    for that band, from the one band definition (apps.policy.mileage)."""
    from apps.policy import mileage
    from apps.policy.models import MileageBand

    return mileage.representative_km(MileageBand.STANDARD)


def curve_check_reference_cars():
    """(name, features) for every active catalog car the ML forecast covers -
    the same rules as inference (not electric, has an engine cc, a body type
    the model knows, a valid brand tier)."""
    from apps.depreciation.inference import _resolve_car_features
    from apps.vehicles.models import VehicleModel

    cars = []
    for vehicle in VehicleModel.objects.filter(is_active=True).select_related("brand").order_by("pk"):
        car, _reason = _resolve_car_features(vehicle)
        if car is not None:
            cars.append((str(vehicle), car))
    return cars


@shared_task
def run_training_task(training_run_id, actor_id=None, ip_address=None):
    """F012 - UC012 main flow steps 5-8, run as a Celery background task.

    Re-validates and re-parses the dataset (the view already did this once
    synchronously for immediate upload feedback; this is the actual
    training pass, run out-of-band). Never leaves the run in a dangling
    RUNNING state: any exception is caught, recorded, and re-raised so
    Celery's own failure tracking still sees it.
    """
    run = MLTrainingRun.objects.get(pk=training_run_id)
    run.status = TrainingRunStatus.RUNNING
    run.save(update_fields=["status"])

    try:
        with open(run.dataset_path, "rb") as dataset_file:
            df = training_module.load_and_validate_csv(dataset_file)
        # QA audit M10: re-validated here too (defense in depth - the view
        # already rejected a too-small upload synchronously; this is the
        # same check re-run against whatever's actually on disk by the
        # time this out-of-band task runs).
        training_module.validate_minimum_rows(df)
        run.row_count = len(df)

        results = training_module.train_and_evaluate(df)
        run.prediction_target = training_module.PREDICTION_TARGET
        run.rf_r2 = results[ModelType.RANDOM_FOREST]["r2"]
        run.rf_mae = results[ModelType.RANDOM_FOREST]["mae"]
        run.rf_within_model_r2 = results[ModelType.RANDOM_FOREST]["within_model_r2"]
        run.rf_best_params = results[ModelType.RANDOM_FOREST]["best_params"]
        run.gb_r2 = results[ModelType.GRADIENT_BOOSTING]["r2"]
        run.gb_mae = results[ModelType.GRADIENT_BOOSTING]["mae"]
        run.gb_within_model_r2 = results[ModelType.GRADIENT_BOOSTING]["within_model_r2"]
        run.gb_best_params = results[ModelType.GRADIENT_BOOSTING]["best_params"]
        run.ll_r2 = results[ModelType.LOG_LINEAR]["r2"]
        run.ll_mae = results[ModelType.LOG_LINEAR]["mae"]
        run.ll_within_model_r2 = results[ModelType.LOG_LINEAR]["within_model_r2"]
        run.ll_best_params = results[ModelType.LOG_LINEAR]["best_params"]

        # QA audit H11: compare against what's CURRENTLY deployed, not
        # just the fixed 0.80 floor - see pick_best_and_decide_deployment's
        # own docstring for why both gates are needed. None (nothing
        # deployed yet) trivially satisfies the comparison gate.
        # ML batch 1: only an R² measured on the SAME target is comparable (a
        # raw-price R² and a log-price R² describe different quantities), so a
        # production model with another target is not compared against.
        production = ProductionModel.get_singleton()
        current_r2 = production.r2_score if production.prediction_target == run.prediction_target else None
        best_model_type, best, should_deploy, rejection_reason = training_module.pick_best_and_decide_deployment(
            results, current_r2=current_r2
        )

        # ML batch 2: the winner's curve must also pass the curve check
        # (apps/ml/curve_check.py) before it can be deployed. Recorded on
        # every run; a failure blocks eligibility with its first problem.
        problems = curve_check.curve_problems(
            best["estimator"], curve_check_reference_cars(), curve_check_annual_km()
        )
        run.curve_check_passed = not problems
        run.curve_check_report = problems
        if should_deploy and problems:
            should_deploy = False
            rejection_reason = curve_check.rejection_reason(problems)

        # Batch 6B / UC012 steps 7-8: clearing both gates no longer
        # auto-deploys - that collapsed two separate UC012 admin actions
        # (train+evaluate, then a LATER human-gated "admin reviews metrics
        # -> clicks Deploy New Model Weights") into one. The winning
        # estimator is saved to disk now regardless of whether/when an
        # admin actually deploys it - see deploy_training_run below, which
        # the new MLTrainingRunDeployView calls once an admin clicks
        # Deploy.
        if should_deploy:
            file_path = save_model(best["estimator"], run.pk, best_model_type)
            run.deploy_eligible = True
            run.candidate_model_type = best_model_type
            run.candidate_model_file_path = file_path
        else:
            run.deployed = False
            run.rejection_reason = rejection_reason

        run.status = TrainingRunStatus.SUCCEEDED
        run.save()
    except Exception as exc:
        run.status = TrainingRunStatus.FAILED
        run.error_message = str(exc)
        run.save()
        # Run 1 fix batch 4 (UC013): a failed training run is a runtime error.
        actor = get_user_model().objects.filter(pk=actor_id).first() if actor_id else None
        log_runtime_error(
            source="ml_training", error=exc, actor=actor, status=None, context={"training_run_id": run.pk},
        )
        raise


def deploy_training_run(run, actor=None, actor_id=None, ip_address=None):
    """Batch 6B / UC012 steps 7-8: hot-swaps ProductionModel to this run's
    already-trained, already-saved-to-disk candidate (see
    run_training_task above - `run.candidate_model_file_path` is written
    at training time, not here). Called from MLTrainingRunDeployView once
    an admin clicks "Deploy New Model Weights"; the view is responsible
    for the deploy_eligible/not-already-deployed checks (clean 400s), not
    this function.

    QA audit H1 (carried over from the old _deploy): the production-model
    swap and its audit-log write share one atomic transaction - either
    both commit or neither does.

    Adjacent bug fixed here, flagged explicitly per the fix prompt: under
    the old auto-deploy flow, deploying never cleared `deployed` on
    whichever OTHER run was previously flagged deployed=True, so two runs
    deployed in sequence could both read deployed=True even though
    ProductionModel is a singleton and only one is ever actually live.
    Fixed below by clearing every other run's flag in the same
    transaction as setting this run's.
    """
    from apps.users.models import User

    with transaction.atomic():
        production = ProductionModel.get_singleton()
        before = {
            "model_type": production.model_type,
            "prediction_target": production.prediction_target,
            "r2_score": production.r2_score,
            "training_run_id": production.training_run_id,
        }

        if run.candidate_model_type == ModelType.RANDOM_FOREST:
            r2_score_value, mae_value = run.rf_r2, run.rf_mae
        elif run.candidate_model_type == ModelType.LOG_LINEAR:
            r2_score_value, mae_value = run.ll_r2, run.ll_mae
        else:
            r2_score_value, mae_value = run.gb_r2, run.gb_mae

        # Sanity-check the saved file is still loadable before repointing
        # production at it - e.g. a candidate deleted out from under a
        # pending deploy by the cleanup_ml_artifacts management command
        # must surface as a clear error here, not a silently broken
        # production model path discovered later at inference time.
        load_model(run.candidate_model_file_path)

        production.training_run = run
        production.model_type = run.candidate_model_type
        production.model_file_path = run.candidate_model_file_path
        # ML batch 1: the run's own recorded target (was hard-coded to the
        # value-retention ratio), so production always says what it holds.
        production.prediction_target = run.prediction_target
        production.r2_score = r2_score_value
        production.mae = mae_value
        production.deployed_at = timezone.now()
        production.save()

        # Singleton-pointer bug fix - see this function's own docstring.
        MLTrainingRun.objects.filter(deployed=True).exclude(pk=run.pk).update(deployed=False)

        run.deployed = True
        run.deployed_model_type = run.candidate_model_type
        run.deploy_eligible = False
        run.save(update_fields=["deployed", "deployed_model_type", "deploy_eligible", "updated_at"])

        if actor is None and actor_id:
            actor = User.objects.filter(pk=actor_id).first()
        write_audit_log(
            actor=actor,
            ip_address=ip_address,
            action=AuditActionCategory.UPDATE,
            resource_type="ml.ProductionModel",
            resource_id="1",
            before=before,
            after={
                "model_type": run.candidate_model_type,
                "prediction_target": run.prediction_target,
                "r2_score": r2_score_value,
                "training_run_id": run.pk,
            },
        )
