import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from rest_framework import serializers

from .models import CURRENT_PREDICTION_TARGET, MLTrainingRun, ModelType, PredictionTarget, ProductionModel

# MAE is stored exactly as the run measured it, in whatever unit that run's
# target was. ML batch 1: every run records its own prediction_target (older
# runs were backfilled by migration 0009), so the unit comes from that field -
# nothing is inferred from the size of the number any more:
#   log_resale_price      -> a log-scale error, shown as "typical error ≈ 22% of price"
#   value_retention_ratio -> a fraction of the price, shown as "10.0 pts of price"
#   raw_resale_price      -> RM
MAE_UNIT_LOG_PRICE = "log_price"
MAE_UNIT_POINTS_OF_PRICE = "points_of_price"
MAE_UNIT_RM = "rm"

_MAE_UNIT_BY_TARGET = {
    PredictionTarget.LOG_RESALE_PRICE: MAE_UNIT_LOG_PRICE,
    PredictionTarget.VALUE_RETENTION_RATIO: MAE_UNIT_POINTS_OF_PRICE,
    PredictionTarget.RAW_RESALE_PRICE: MAE_UNIT_RM,
}

# How the serving note names what a refused production model predicts.
_TARGET_PHRASE = {
    PredictionTarget.RAW_RESALE_PRICE: "raw prices",
    PredictionTarget.VALUE_RETENTION_RATIO: "value-retention ratios",
}

_WHOLE = Decimal("1")
_ONE_PLACE = Decimal("0.1")
_TWO_PLACES = Decimal("0.01")


def log_mae_as_percent_of_price(value):
    """A log-scale MAE as the typical percentage error on the price:
    (e^MAE - 1) x 100, as a Decimal (unrounded)."""
    return (Decimal(str(math.exp(value))) - 1) * 100


def typical_error_percent(value):
    """A log-price MAE as the whole-number "typical error, % of price" the ML
    page shows (half-up), or None when it is too large to mean anything. The
    ONE place this rounding lives: format_mae below and the TCO tab's resale
    forecast note (apps.depreciation.resale_notes) both read it, so the two can
    never disagree."""
    try:
        return log_mae_as_percent_of_price(value).quantize(_WHOLE, rounding=ROUND_HALF_UP)
    except (OverflowError, InvalidOperation):
        return None


def format_mae(value, unit):
    """"typical error ≈ 22% of price" for a log-price MAE, "10.0 pts of price"
    for a ratio-target MAE, "RM 15,881.93" for a raw-price one, None when the
    run has no MAE or no known unit. Half-up rounding, like every other figure
    in the app."""
    if value is None or unit is None:
        return None
    if unit == MAE_UNIT_LOG_PRICE:
        percent = typical_error_percent(value)
        if percent is None:
            # A log error this large is meaningless as a percentage; show the
            # stored number rather than fail the whole run list.
            return f"log-scale error {value:.4f}"
        return f"typical error ≈ {percent:,}% of price"
    amount = Decimal(str(value))
    if unit == MAE_UNIT_POINTS_OF_PRICE:
        points = (amount * 100).quantize(_ONE_PLACE, rounding=ROUND_HALF_UP)
        return f"{points} pts of price"
    return f"RM {amount.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP):,.2f}"


def mae_unit_for(run):
    """The unit of this run's MAE, from its own prediction_target; None when
    the run recorded no MAE or no target."""
    if run.rf_mae is None and run.gb_mae is None and run.ll_mae is None:
        return None
    return _MAE_UNIT_BY_TARGET.get(run.prediction_target)


def target_label(target):
    """The human label of a prediction target; "" when unknown/blank."""
    return PredictionTarget(target).label if target in PredictionTarget.values else ""


class MLTrainingRunSerializer(serializers.ModelSerializer):
    # How to read this run's MAE: "log_price", "points_of_price" or "rm"; null
    # when the run recorded no MAE.
    mae_unit = serializers.SerializerMethodField()
    rf_mae_display = serializers.SerializerMethodField()
    gb_mae_display = serializers.SerializerMethodField()
    ll_mae_display = serializers.SerializerMethodField()
    prediction_target_label = serializers.SerializerMethodField()
    serving_note = serializers.SerializerMethodField()

    class Meta:
        model = MLTrainingRun
        fields = [
            "id",
            "status",
            "dataset_filename",
            "row_count",
            "prediction_target",
            "prediction_target_label",
            "rf_r2",
            "rf_within_model_r2",
            "rf_mae",
            "rf_mae_display",
            "rf_best_params",
            "gb_r2",
            "gb_within_model_r2",
            "gb_mae",
            "gb_mae_display",
            "gb_best_params",
            "ll_r2",
            "ll_within_model_r2",
            "ll_mae",
            "ll_mae_display",
            "ll_best_params",
            "curve_check_passed",
            "curve_check_report",
            "mae_unit",
            "deployed",
            "deployed_model_type",
            "deploy_eligible",
            "candidate_model_type",
            "rejection_reason",
            "error_message",
            "known_issue_note",
            "retired_at",
            "retired_reason",
            "serving_note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _production(self):
        # One lookup per serializer instance (a list shares one child).
        if not hasattr(self, "_production_row"):
            self._production_row = ProductionModel.objects.filter(pk=1).first()
        return self._production_row

    def get_serving_note(self, run):
        """Run 1 fix batch 5 (R1-4 flag 1): the admin's view of why the buyer
        sees the fallback curve. Set only on the run recorded as the
        production model when inference refuses it (any target other than the
        current one - see apps.depreciation.inference); null otherwise.
        Nothing about which model is deployed changes here."""
        production = self._production()
        if production is None or production.training_run_id != run.pk:
            return None
        if production.prediction_target == CURRENT_PREDICTION_TARGET:
            return None
        predicts = _TARGET_PHRASE.get(production.prediction_target, "an unknown target")
        return (
            f"Run {run.pk} is marked deployed but is not used: it predicts {predicts}, and the forecast now "
            "needs the resale-price model (log scale)."
        )

    def get_mae_unit(self, run):
        return mae_unit_for(run)

    def get_rf_mae_display(self, run):
        return format_mae(run.rf_mae, mae_unit_for(run))

    def get_gb_mae_display(self, run):
        return format_mae(run.gb_mae, mae_unit_for(run))

    def get_ll_mae_display(self, run):
        return format_mae(run.ll_mae, mae_unit_for(run))

    def get_prediction_target_label(self, run):
        return target_label(run.prediction_target)


class ProductionModelSerializer(serializers.ModelSerializer):
    """ML batch 1: the ML page's production card. Read-only; the target and
    both R² values of the model buyers are actually served (null fields when
    nothing is deployed)."""

    prediction_target_label = serializers.SerializerMethodField()
    model_type_label = serializers.SerializerMethodField()
    within_model_r2 = serializers.SerializerMethodField()
    mae_display = serializers.SerializerMethodField()
    is_serving = serializers.SerializerMethodField()

    class Meta:
        model = ProductionModel
        fields = [
            "training_run",
            "model_type",
            "model_type_label",
            "prediction_target",
            "prediction_target_label",
            "r2_score",
            "within_model_r2",
            "mae",
            "mae_display",
            "deployed_at",
            "is_serving",
        ]
        read_only_fields = fields

    def get_prediction_target_label(self, production):
        return target_label(production.prediction_target)

    def get_model_type_label(self, production):
        return ModelType(production.model_type).label if production.model_type in ModelType.values else ""

    def get_within_model_r2(self, production):
        run = production.training_run
        if run is None:
            return None
        return {
            ModelType.RANDOM_FOREST: run.rf_within_model_r2,
            ModelType.GRADIENT_BOOSTING: run.gb_within_model_r2,
            ModelType.LOG_LINEAR: run.ll_within_model_r2,
        }.get(production.model_type)

    def get_mae_display(self, production):
        return format_mae(production.mae, _MAE_UNIT_BY_TARGET.get(production.prediction_target))

    def get_is_serving(self, production):
        """True only when buyers actually get this model's forecast."""
        return bool(production.model_file_path) and production.prediction_target == CURRENT_PREDICTION_TARGET
