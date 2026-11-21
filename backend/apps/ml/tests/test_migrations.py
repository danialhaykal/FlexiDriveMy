"""QA audit C8 correction: confirms migration 0006 actually backfills
prediction_target=raw_resale_price on a ProductionModel row that already
had a real, deployed model_file_path before this migration ran - the
literal situation this project's own dev database is in right now (a
model deployed under the pre-ratio-target convention, with nothing new
having cleared the deployment gate since). Runs the real migration
machinery (MigrationExecutor), not just the post-migration model class
directly, since the whole point is proving the migration's own
RunPython does the backfill - a test against the current model alone
would pass even if the migration itself did nothing.
"""

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

APP = "ml"
BEFORE = [(APP, "0005_productionmodel_prediction_target")]
AFTER = [(APP, "0006_backfill_legacy_prediction_target")]


@pytest.fixture(autouse=True)
def _return_to_latest():
    """Every other test in this suite expects the real, fully-migrated
    schema - roll forward again after this file's own backward/forward
    migration dance, regardless of pass/fail."""
    yield
    call_command("migrate", verbosity=0)


def test_backfills_raw_resale_price_on_a_row_with_an_existing_deployed_model():
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)

    old_apps = executor.loader.project_state(BEFORE).apps
    OldProductionModel = old_apps.get_model(APP, "ProductionModel")
    OldProductionModel.objects.create(
        pk=1,
        model_type="random_forest",
        model_file_path="/existing/pre_c8_model.joblib",
        prediction_target="",
        r2_score=0.89,
    )

    executor = MigrationExecutor(connection)
    executor.migrate(AFTER)

    new_apps = executor.loader.project_state(AFTER).apps
    NewProductionModel = new_apps.get_model(APP, "ProductionModel")
    production = NewProductionModel.objects.get(pk=1)
    assert production.prediction_target == "raw_resale_price"
    # Nothing else about the row was touched.
    assert production.model_file_path == "/existing/pre_c8_model.joblib"
    assert production.r2_score == 0.89


def test_a_row_with_no_deployed_model_is_left_blank():
    """A fresh/never-deployed singleton (model_file_path="") must stay
    blank - there's no deployed model to retroactively label as legacy."""
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)

    old_apps = executor.loader.project_state(BEFORE).apps
    OldProductionModel = old_apps.get_model(APP, "ProductionModel")
    OldProductionModel.objects.create(pk=1, model_type="", model_file_path="", prediction_target="")

    executor = MigrationExecutor(connection)
    executor.migrate(AFTER)

    new_apps = executor.loader.project_state(AFTER).apps
    NewProductionModel = new_apps.get_model(APP, "ProductionModel")
    production = NewProductionModel.objects.get(pk=1)
    assert production.prediction_target == ""


# --- ML batch 1: 0009 gives every existing run its own prediction_target ---------------------

BEFORE_0009 = [(APP, "0008_mltrainingrun_prediction_target_and_more")]
AFTER_0009 = [(APP, "0009_backfill_training_run_prediction_target")]


def test_0009_backfills_each_runs_target_by_the_explicit_rules():
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE_0009)
    Run = executor.loader.project_state(BEFORE_0009).apps.get_model(APP, "MLTrainingRun")
    ids = {
        "raw": Run.objects.create(status="succeeded", rf_mae=1271.43, gb_mae=1386.54).pk,
        "ratio": Run.objects.create(status="succeeded", rf_mae=0.0998, gb_mae=0.0952).pk,
        "ratio_one_mae": Run.objects.create(status="succeeded", rf_mae=0.0998, gb_mae=None).pk,
        "mixed": Run.objects.create(status="succeeded", rf_mae=0.09, gb_mae=1386.54).pk,
        "boundary": Run.objects.create(status="succeeded", rf_mae=1.0, gb_mae=1.0).pk,
        "no_metrics": Run.objects.create(status="failed").pk,
        "already_set": Run.objects.create(
            status="succeeded", rf_mae=0.2, gb_mae=0.2, prediction_target="log_resale_price"
        ).pk,
    }

    executor = MigrationExecutor(connection)
    executor.migrate(AFTER_0009)

    Run = executor.loader.project_state(AFTER_0009).apps.get_model(APP, "MLTrainingRun")
    targets = {name: Run.objects.get(pk=pk).prediction_target for name, pk in ids.items()}
    assert targets == {
        "raw": "raw_resale_price",
        "ratio": "value_retention_ratio",
        "ratio_one_mae": "value_retention_ratio",
        "mixed": "raw_resale_price",
        "boundary": "value_retention_ratio",
        "no_metrics": "",
        "already_set": "log_resale_price",  # never relabelled
    }
