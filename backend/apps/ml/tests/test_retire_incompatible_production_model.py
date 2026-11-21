"""retire_incompatible_production_model (ML batch 1): dry run by default, one
transaction on --apply, clears a production model whose target is not the log
resale price (the file stays on disk), un-deploys and retires every run still
flagged deployed, one audit row per changed record, idempotent."""

from datetime import datetime, timezone as dt_timezone
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditActionCategory, AuditLog
from apps.ml.models import MLTrainingRun, ModelType, PredictionTarget, ProductionModel

pytestmark = pytest.mark.django_db

# Run 3 fix batch 5 (F-26): plain words on the ML page (was "... from msrp_proxy; replaced by the
# resale-price model (ML batch 1).").
RUN5_REASON = (
    "Retired: it predicts raw prices from a used-price stand-in for the new price; replaced by the resale-price model."
)
STALE_REASON = "Retired: stale deployed flag from before single-deploy was enforced."


@pytest.fixture
def dev_state(tmp_path, create_user):
    """The dev database's shape: runs 1, 4 and 5 all say deployed; production
    points at run 5, a raw-price random forest at R² 0.892."""
    create_user(email="admin@flexidrivemy.local", role="admin")
    model_file = tmp_path / "run5.joblib"
    model_file.write_bytes(b"model")
    runs = {
        n: MLTrainingRun.objects.create(
            status="succeeded", rf_r2=0.89, gb_r2=0.88, prediction_target=PredictionTarget.RAW_RESALE_PRICE,
            deployed=n in (1, 4, 5), deployed_model_type=ModelType.RANDOM_FOREST if n in (1, 4, 5) else "",
        )
        for n in (1, 2, 3, 4, 5, 6)
    }
    ProductionModel.objects.update_or_create(pk=1, defaults={
        "training_run": runs[5], "model_type": ModelType.RANDOM_FOREST, "model_file_path": str(model_file),
        "prediction_target": PredictionTarget.RAW_RESALE_PRICE, "r2_score": 0.892, "mae": 15881.93,
        "deployed_at": datetime(2026, 9, 4, tzinfo=dt_timezone.utc),
    })
    return {"runs": runs, "model_file": model_file}


def run(*args):
    out = StringIO()
    call_command("retire_incompatible_production_model", *args, stdout=out)
    return out.getvalue()


def state():
    return {
        "runs": list(MLTrainingRun.objects.order_by("pk").values()),
        "production": list(ProductionModel.objects.values()),
        "audit": AuditLog.objects.count(),
    }


def test_the_dry_run_is_the_default_and_writes_nothing(dev_state):
    before = state()

    output = run()

    assert state() == before
    assert output.startswith("DRY RUN - nothing will be changed")
    assert "4 change(s): production cleared; 3 run(s) retired" in output
    assert "Dry run only. Re-run with --apply" in output


def test_apply_clears_production_but_keeps_the_model_file(dev_state):
    run("--apply", "--actor-email", "admin@flexidrivemy.local")

    production = ProductionModel.objects.get(pk=1)
    assert (production.training_run_id, production.model_type, production.model_file_path) == (None, "", "")
    assert (production.prediction_target, production.r2_score, production.mae, production.deployed_at) == (
        "", None, None, None)
    assert dev_state["model_file"].exists()


def test_apply_retires_runs_1_4_and_5_with_their_reasons_and_keeps_them(dev_state):
    runs = dev_state["runs"]

    run("--apply")

    assert MLTrainingRun.objects.count() == 6
    assert not MLTrainingRun.objects.filter(deployed=True).exists()
    for n in (1, 2, 3, 4, 5, 6):
        runs[n].refresh_from_db()
    assert runs[5].retired_reason == RUN5_REASON
    assert runs[1].retired_reason == runs[4].retired_reason == STALE_REASON
    assert all(runs[n].retired_at is not None for n in (1, 4, 5))
    assert all(runs[n].retired_at is None and runs[n].retired_reason == "" for n in (2, 3, 6))
    assert runs[5].rf_r2 == 0.89  # history untouched


def test_apply_writes_one_audit_row_per_changed_record(dev_state):
    runs = dev_state["runs"]
    existing = list(AuditLog.objects.values())

    output = run("--apply", "--actor-email", "admin@flexidrivemy.local")

    new_rows = AuditLog.objects.exclude(pk__in=[row["id"] for row in existing]).order_by("pk")
    assert new_rows.count() == 4
    assert {row.action for row in new_rows} == {AuditActionCategory.UPDATE}
    assert {row.actor_email for row in new_rows} == {"admin@flexidrivemy.local"}
    assert [(row.resource_type, row.resource_id) for row in new_rows] == [
        ("ml.ProductionModel", "1"),
        ("ml.MLTrainingRun", str(runs[1].pk)),
        ("ml.MLTrainingRun", str(runs[4].pk)),
        ("ml.MLTrainingRun", str(runs[5].pk)),
    ]
    production_row = new_rows[0]
    assert production_row.before_data["prediction_target"] == "raw_resale_price"
    assert production_row.before_data["r2_score"] == 0.892
    assert production_row.after_data["model_file_path"] == ""
    assert "retire_incompatible_production_model" in production_row.after_data["correction"]
    assert new_rows[3].before_data["deployed"] is True and new_rows[3].after_data["deployed"] is False
    assert new_rows[3].after_data["retired_reason"] == RUN5_REASON
    assert f"Audit rows: #{new_rows[0].pk}, #{new_rows[1].pk}, #{new_rows[2].pk}, #{new_rows[3].pk}." in output
    assert list(AuditLog.objects.filter(pk__in=[row["id"] for row in existing]).values()) == existing


def test_a_second_run_changes_nothing(dev_state):
    run("--apply", "--actor-email", "admin@flexidrivemy.local")
    after_first = state()

    output = run("--apply", "--actor-email", "admin@flexidrivemy.local")
    dry = run()

    assert state() == after_first
    assert "0 change(s): production unchanged; 0 run(s) retired" in output
    assert "Nothing to change." in output and "0 change(s)" in dry


def test_a_compatible_production_model_is_left_alone_and_only_stale_flags_go(dev_state):
    runs = dev_state["runs"]
    ProductionModel.objects.filter(pk=1).update(prediction_target=PredictionTarget.LOG_RESALE_PRICE)

    run("--apply")

    production = ProductionModel.objects.get(pk=1)
    assert production.training_run_id == runs[5].pk and production.r2_score == 0.892
    runs[5].refresh_from_db()
    runs[1].refresh_from_db()
    assert runs[5].deployed is True and runs[5].retired_at is None
    assert runs[1].deployed is False and runs[1].retired_reason == STALE_REASON


def test_after_apply_the_forecast_reads_as_switched_off_and_the_serving_note_is_gone(dev_state, admin_user):
    from rest_framework.test import APIClient

    from apps.depreciation import inference

    run("--apply")

    assert inference.forecast_is_switched_off() is True
    client = APIClient()
    client.force_authenticate(user=admin_user)
    rows = client.get("/api/ml/training-runs/").data["results"]
    assert all(row["serving_note"] is None for row in rows)
    retired = {row["id"]: row for row in rows if row["retired_at"]}
    assert set(retired) == {dev_state["runs"][n].pk for n in (1, 4, 5)}


def test_without_an_actor_the_audit_rows_are_attributed_to_the_system(dev_state):
    run("--apply")

    rows = AuditLog.objects.filter(resource_type__in=["ml.ProductionModel", "ml.MLTrainingRun"])
    assert rows.count() == 4
    assert all(row.actor is None and row.actor_email == "" for row in rows)


# --- ML batch 2: --run <id> --reason retires one undeployed run -------------------------------

RUN9_REASON = (
    "Retired: trained on mis-aged data (one reference year for 2022 and 2026 listings); superseded by the "
    "listing-year rebuild (ML batch 2)."
)


@pytest.fixture
def eligible_run():
    return MLTrainingRun.objects.create(
        status="succeeded", prediction_target=PredictionTarget.LOG_RESALE_PRICE, gb_r2=0.8789,
        deploy_eligible=True, candidate_model_type=ModelType.GRADIENT_BOOSTING,
        candidate_model_file_path="C:/models/model_9_gradient_boosting.joblib",
    )


def test_run_mode_dry_run_writes_nothing(dev_state, eligible_run):
    before = state()

    output = run("--run", str(eligible_run.pk), "--reason", RUN9_REASON)

    assert state() == before
    assert f"RETIRE   run {eligible_run.pk} (deploy_eligible=True)" in output
    assert "Dry run only." in output


def test_run_mode_retires_just_that_run_audited_and_a_rerun_changes_nothing(dev_state, eligible_run):
    production_before = list(ProductionModel.objects.values())

    output = run("--run", str(eligible_run.pk), "--reason", RUN9_REASON, "--apply",
                 "--actor-email", "admin@flexidrivemy.local")

    eligible_run.refresh_from_db()
    assert eligible_run.retired_at is not None and eligible_run.retired_reason == RUN9_REASON
    assert eligible_run.deploy_eligible is False
    assert eligible_run.candidate_model_file_path  # history kept, file untouched
    assert list(ProductionModel.objects.values()) == production_before  # nothing else touched
    assert MLTrainingRun.objects.filter(retired_at__isnull=False).count() == 1
    row = AuditLog.objects.get(resource_type="ml.MLTrainingRun", resource_id=str(eligible_run.pk))
    assert row.actor_email == "admin@flexidrivemy.local"
    assert row.before_data["deploy_eligible"] is True and row.after_data["deploy_eligible"] is False
    assert row.after_data["retired_reason"] == RUN9_REASON
    assert f"Audit rows: #{row.pk}." in output

    after_first = state()
    again = run("--run", str(eligible_run.pk), "--reason", RUN9_REASON, "--apply")
    assert state() == after_first
    assert "0 change(s)" in again and "Nothing to change." in again


def test_run_mode_refuses_a_deployed_run_an_unknown_run_and_a_missing_reason(dev_state, eligible_run):
    before = state()
    deployed = dev_state["runs"][5]

    with pytest.raises(CommandError, match="is deployed"):
        run("--run", str(deployed.pk), "--reason", "x", "--apply")
    with pytest.raises(CommandError, match="No training run"):
        run("--run", "999999", "--reason", "x", "--apply")
    with pytest.raises(CommandError, match="needs --reason"):
        run("--run", str(eligible_run.pk), "--apply")
    with pytest.raises(CommandError, match="only used with --run"):
        run("--reason", "x")

    assert state() == before


def test_a_run_retired_this_way_can_never_be_deployed(dev_state, eligible_run, admin_user):
    from rest_framework.test import APIClient

    run("--run", str(eligible_run.pk), "--reason", RUN9_REASON, "--apply")
    client = APIClient()
    client.force_authenticate(user=admin_user)

    response = client.post(f"/api/ml/training-runs/{eligible_run.pk}/deploy/")

    assert response.status_code == 400
    assert response.data["detail"] == "This run has been retired."


def test_an_unknown_actor_is_refused_before_anything_is_written(dev_state):
    before = state()

    with pytest.raises(CommandError):
        run("--apply", "--actor-email", "nobody@example.com")

    assert state() == before
