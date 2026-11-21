from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel

R2_DEPLOYMENT_THRESHOLD = 0.80


class ModelType(models.TextChoices):
    RANDOM_FOREST = "random_forest", "Random Forest"
    GRADIENT_BOOSTING = "gradient_boosting", "Gradient Boosting"
    # ML batch 2: the third candidate (apps/ml/log_linear.py).
    LOG_LINEAR = "log_linear", "Log-linear (hedonic)"


class PredictionTarget(models.TextChoices):
    """QA audit C8 correction: WHICH quantity a deployed model's raw
    predict() output actually represents - apps/ml/training.py's
    train_and_evaluate now always fits a value-retention ratio
    (RATIO_TARGET_COLUMN), but a model deployed before that change exists
    was fit on raw resale_price, an absolute RM figure. The two are not
    interchangeable: feeding an old raw_resale_price model's output
    through the new ratio*msrp scaling in apps/depreciation/inference.py
    produces a nonsense figure in the hundreds of billions, which the
    sanity clamp then silently collapses to a flat line at msrp for every
    month, with model_degraded never set - exactly the live bug this
    correction fixes."""

    RAW_RESALE_PRICE = "raw_resale_price", "Raw resale price (legacy, pre-C8)"
    VALUE_RETENTION_RATIO = "value_retention_ratio", "Value-retention ratio (C8)"
    # ML batch 1: the current target - log of the resale price, from attribute
    # features only (see apps/ml/training.py). The only target inference uses.
    LOG_RESALE_PRICE = "log_resale_price", "Resale price (log scale)"


# What train_and_evaluate fits today; the only target the forecast accepts.
CURRENT_PREDICTION_TARGET = PredictionTarget.LOG_RESALE_PRICE


class TrainingRunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class MLTrainingRun(TimeStampedModel):
    """F012 - one CSV upload + retrain attempt (UC012).

    Both candidate models (RandomForestRegressor, GradientBoostingRegressor)
    are always trained and their metrics recorded here; `deployed` records
    whether this run's winning model actually replaced the production
    model (R^2 >= 0.80 gate - see apps/ml/training.py).
    """

    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ml_training_runs"
    )
    status = models.CharField(max_length=20, choices=TrainingRunStatus.choices, default=TrainingRunStatus.PENDING)
    dataset_filename = models.CharField(max_length=255, blank=True)
    dataset_path = models.CharField(max_length=500, blank=True)
    row_count = models.PositiveIntegerField(null=True, blank=True)

    rf_r2 = models.FloatField(null=True, blank=True)
    rf_mae = models.FloatField(null=True, blank=True)
    rf_best_params = models.JSONField(null=True, blank=True)
    gb_r2 = models.FloatField(null=True, blank=True)
    gb_mae = models.FloatField(null=True, blank=True)
    gb_best_params = models.JSONField(null=True, blank=True)
    # ML batch 2: the log-linear (hedonic) candidate. best_params = {"alpha": ...}.
    ll_r2 = models.FloatField(null=True, blank=True)
    ll_mae = models.FloatField(null=True, blank=True)
    ll_best_params = models.JSONField(null=True, blank=True)
    ll_within_model_r2 = models.FloatField(null=True, blank=True)
    # ML batch 2: the winner's curve check (apps/ml/curve_check.py) - a deploy
    # rule next to the R² gates. Null = not run (older runs).
    curve_check_passed = models.BooleanField(null=True, blank=True)
    curve_check_report = models.JSONField(default=list, blank=True)

    deployed = models.BooleanField(default=False)
    deployed_model_type = models.CharField(max_length=20, choices=ModelType.choices, blank=True)
    # Batch 6B / UC012 steps 7-8: clearing both deployment gates (see
    # apps.ml.training.pick_best_and_decide_deployment) no longer deploys
    # immediately - it marks the run eligible for a SEPARATE, later,
    # human-gated "Deploy New Model Weights" action. The winning
    # estimator is saved to disk at training time regardless (so it's
    # available whenever an admin gets around to deploying it, which may
    # be a different request/process) - these two fields point at it.
    # False/blank for every run that either failed a gate or has already
    # been deployed (see MLTrainingRunDeployView, which clears
    # deploy_eligible on deploy).
    deploy_eligible = models.BooleanField(default=False)
    candidate_model_type = models.CharField(max_length=20, choices=ModelType.choices, blank=True)
    candidate_model_file_path = models.CharField(max_length=500, blank=True)
    rejection_reason = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    # Manually-set annotation for a documented, human-confirmed incident on
    # this specific run (e.g. "this run's feature pipeline had a since-fixed
    # leakage bug") - never auto-detected/derived. Blank for every run
    # except the one(s) a human has actually confirmed and annotated (see
    # the Sprint 13 addendum's data migration).
    known_issue_note = models.TextField(blank=True, default="")
    # ML batch 1: what this run's estimators predict (and so the unit of its
    # MAE). Blank = unknown (a run with no metrics).
    prediction_target = models.CharField(max_length=30, choices=PredictionTarget.choices, blank=True)
    # Depreciation-shape R²: R² of the held-out predictions after removing each
    # car model's own mean (see training.within_model_r2). Null when the run
    # had no model_key column or too few rows qualified.
    rf_within_model_r2 = models.FloatField(null=True, blank=True)
    gb_within_model_r2 = models.FloatField(null=True, blank=True)
    # A retired run stays in the history but can never be deployed.
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Training run #{self.pk} ({self.status})"


class ProductionModel(TimeStampedModel):
    """F012 - singleton (pk=1) pointer to the currently deployed model
    file. 'Hot-swapping' means atomically repointing this row at a new
    file, never overwriting a fixed filename in place."""

    training_run = models.ForeignKey(
        MLTrainingRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    model_type = models.CharField(max_length=20, choices=ModelType.choices, blank=True)
    model_file_path = models.CharField(max_length=500, blank=True)
    # QA audit C8 correction: blank means "unknown/legacy" and is treated
    # as INCOMPATIBLE with the current ratio-target inference code, the
    # same as an explicit RAW_RESALE_PRICE - see apps/depreciation/
    # inference.py's _load_production_model and PredictionTarget's own
    # docstring. Never defaults to VALUE_RETENTION_RATIO: a blank/unknown
    # convention must degrade, not be assumed compatible.
    prediction_target = models.CharField(max_length=30, choices=PredictionTarget.choices, blank=True)
    r2_score = models.FloatField(null=True, blank=True)
    mae = models.FloatField(null=True, blank=True)
    deployed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Production model: {self.model_type or 'none deployed'}"

    @classmethod
    def get_singleton(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
