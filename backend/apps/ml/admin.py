from django.contrib import admin

from apps.audit.admin_mixins import NoHardDeleteAdminMixin

from .models import MLTrainingRun, ProductionModel


def _fixed(value, places):
    """Display-only rounding - the stored float is never touched."""
    return "-" if value is None else f"{value:.{places}f}"


@admin.register(MLTrainingRun)
class MLTrainingRunAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    # Run 3 fix batch 4 (F-32): a run is never deleted - the production pointer, the
    # ML page's history and the audit trail refer to it (retire it instead).
    list_display = [
        "id", "status", "dataset_filename", "row_count", "rf_r2_display", "gb_r2_display", "deployed", "created_at"
    ]
    list_filter = ["status", "deployed"]
    readonly_fields = [f.name for f in MLTrainingRun._meta.fields]

    def has_add_permission(self, request):
        return False

    @admin.display(description="RF R²", ordering="rf_r2")
    def rf_r2_display(self, obj):
        return _fixed(obj.rf_r2, 4)

    @admin.display(description="GB R²", ordering="gb_r2")
    def gb_r2_display(self, obj):
        return _fixed(obj.gb_r2, 4)


@admin.register(ProductionModel)
class ProductionModelAdmin(admin.ModelAdmin):
    """QA audit H3: this row must only ever change via apps.ml.tasks._deploy
    - the one path that enforces the R2 >= 0.80 deployment gate (see
    apps/ml/training.py). Letting a staff user freely retarget
    model_file_path to an arbitrary file here would mean apps/depreciation's
    inference.py then unpickles whatever that path points to on the next
    request - arbitrary code execution, and it skips the gate entirely.
    Fully read-only (not just that one field): this screen exists to let
    an admin SEE which model is currently deployed, never to edit it.
    """

    list_display = ["model_type", "r2_score_display", "mae_display", "deployed_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="R² score", ordering="r2_score")
    def r2_score_display(self, obj):
        return _fixed(obj.r2_score, 4)

    @admin.display(description="MAE", ordering="mae")
    def mae_display(self, obj):
        return _fixed(obj.mae, 2)
