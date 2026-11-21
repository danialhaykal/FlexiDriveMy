"""One-off command: actually retrains F012's model against
apps/ml/data/real_historical_pricing.csv (see build_real_ml_dataset and
README_real_data.md), synchronously, with no Celery worker required.

Mirrors the fields MLDatasetUploadView sets when a real upload comes in
(dataset_filename, dataset_path), then calls run_training_task directly
(not .delay()) so it runs in-process instead of being queued.
"""

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.ml.models import MLTrainingRun
from apps.ml.serializers import log_mae_as_percent_of_price
from apps.ml.tasks import run_training_task

DATASET_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "real_historical_pricing.csv"


class Command(BaseCommand):
    help = "Retrain F012's model against apps/ml/data/real_historical_pricing.csv, synchronously."

    def handle(self, *args, **options):
        if not DATASET_PATH.exists():
            raise CommandError(f"{DATASET_PATH} does not exist - run `manage.py build_real_ml_dataset` first.")

        run = MLTrainingRun.objects.create(
            dataset_filename=DATASET_PATH.name,
            dataset_path=str(DATASET_PATH),
        )

        run_training_task(run.pk)

        run.refresh_from_db()

        # ML batch 1: r2/mae are on the LOG resale-price scale (see
        # apps/ml/training.py's module docstring). A log-scale MAE is a
        # relative error: e^MAE - 1 is the typical error as a share of the
        # price. The within-model ("depreciation-shape") R² is printed beside
        # the gate's R², never instead of it.
        out = self.stdout.write
        out(f"training run: {run.pk}")
        out(f"row_count: {run.row_count}")
        out(f"prediction_target: {run.prediction_target}")
        for label, r2, mae, within, params in (
            ("Random Forest", run.rf_r2, run.rf_mae, run.rf_within_model_r2, run.rf_best_params),
            ("Gradient Boosting", run.gb_r2, run.gb_mae, run.gb_within_model_r2, run.gb_best_params),
            ("Log-linear (hedonic)", run.ll_r2, run.ll_mae, run.ll_within_model_r2, run.ll_best_params),
        ):
            out(f"{label}:")
            out(f"  R² (held-out, log price): {_four(r2)}")
            if mae is None:
                out("  MAE (log price): -")
            else:
                percent = log_mae_as_percent_of_price(mae).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                out(f"  MAE (log price): {mae:.4f} (typical error ≈ {percent}% of price)")
            out(f"  Depreciation-shape R² (within the same model): {_four(within)}")
            out(f"  best params: {params}")
        winner = max(
            (("random_forest", run.rf_r2), ("gradient_boosting", run.gb_r2), ("log_linear", run.ll_r2)),
            key=lambda item: -1 if item[1] is None else item[1],
        )[0]
        out(f"winner (highest held-out R²): {winner}")
        if run.curve_check_passed is None:
            out("curve check: not run")
        elif run.curve_check_passed:
            out("curve check (winner): PASSED")
        else:
            out(f"curve check (winner): FAILED - {len(run.curve_check_report)} problem(s):")
            for problem in run.curve_check_report:
                out(f"  - {problem}")
        out(f"deploy_eligible: {run.deploy_eligible}")
        out(f"candidate_model_type: {run.candidate_model_type!r}")
        out(f"deployed: {run.deployed} (never deployed by this command - deploy from the ML page)")
        out(f"rejection_reason: {run.rejection_reason!r}")


def _four(value):
    return "-" if value is None else f"{value:.4f}"
