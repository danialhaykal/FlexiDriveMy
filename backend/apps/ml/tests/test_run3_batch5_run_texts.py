"""Run 3 fix batch 5 (F-26): the ML Model Management page shows each run's
rejection reason, known-issue note and retirement reason as stored, so they carry
no developer text. New runs are written plainly; rows stored before are reworded by
the audited, idempotent command clean_ml_run_texts. Figures are never touched."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.audit.models import AuditLog
from apps.ml import training
from apps.ml.data_fixes import KNOWN_ISSUE_NOTE_LEAKY_MSRP_PROXY_RUN
from apps.ml.models import MLTrainingRun
from apps.ml.run_texts import DEVELOPER_TEXT, model_type_label, plain_run_text

pytestmark = pytest.mark.django_db

# The texts stored on the dev database's runs 2/3/6/8, 4, 5 and 9 before this batch.
OLD = {
    "rejection": "Best validation R² (0.6136 from gradient_boosting) is below the required 0.80 threshold; keeping "
                 "the current production model.",
    "note": "This run's msrp_proxy feature was computed without leave-one-out exclusion, allowing rows' own resale "
            "price to leak into their own prediction feature and inflating R². The bug was fixed before the next "
            "run; this run's R² should not be cited as a valid result.",
    "run5": "Retired: it predicts raw prices from msrp_proxy; replaced by the resale-price model (ML batch 1).",
    "run9": "Retired: trained on mis-aged data (one reference year for 2022 and 2026 listings); superseded by the "
            "listing-year rebuild (ML batch 2).",
}
NEW = {
    "rejection": "Best validation R² (0.6136 from Gradient Boosting) is below the required 0.80 threshold; keeping "
                 "the current production model.",
    "note": KNOWN_ISSUE_NOTE_LEAKY_MSRP_PROXY_RUN,
    "run5": "Retired: it predicts raw prices from a used-price stand-in for the new price; replaced by the "
            "resale-price model.",
    "run9": "Retired: trained on mis-aged data (one reference year for 2022 and 2026 listings); superseded by the "
            "listing-year rebuild.",
}


@pytest.mark.parametrize("key", sorted(OLD))
def test_each_stored_text_gets_its_plain_version_and_stays_put(key):
    assert plain_run_text(OLD[key]) == NEW[key]
    assert plain_run_text(NEW[key]) == NEW[key]  # idempotent
    assert not DEVELOPER_TEXT.search(NEW[key])


def test_a_plain_text_and_an_empty_one_are_untouched():
    text = "Curve check failed: BMW 3 Series 320i Sport: keeps 96.1% after 12 months (limit 95%)"
    assert plain_run_text(text) == text
    assert plain_run_text("") == ""


def test_a_model_file_name_is_not_rewritten():
    assert plain_run_text("model_10_log_linear_642b0bf2.joblib") == "model_10_log_linear_642b0bf2.joblib"


def test_model_labels():
    assert [model_type_label(k) for k in ("random_forest", "gradient_boosting", "log_linear", "other")] == [
        "Random Forest", "Gradient Boosting", "Log-linear (hedonic)", "other"]


def test_a_new_rejection_reason_names_the_model():
    results = {"random_forest": {"r2": 0.61}, "gradient_boosting": {"r2": 0.6136}}

    _best, _result, should_deploy, reason = training.pick_best_and_decide_deployment(results)

    assert should_deploy is False
    assert reason == NEW["rejection"]


# --- the command ------------------------------------------------------------------------------------------------------


@pytest.fixture
def runs():
    return {
        "rejection": MLTrainingRun.objects.create(rejection_reason=OLD["rejection"], rf_r2=0.6, gb_r2=0.6136),
        "note": MLTrainingRun.objects.create(known_issue_note=OLD["note"], rf_r2=0.9335),
        "run5": MLTrainingRun.objects.create(retired_reason=OLD["run5"]),
        "run9": MLTrainingRun.objects.create(retired_reason=OLD["run9"]),
        "plain": MLTrainingRun.objects.create(rejection_reason="Curve check failed: X: keeps 96.1% after 12 months"),
    }


FIELD = {"rejection": "rejection_reason", "note": "known_issue_note", "run5": "retired_reason", "run9": "retired_reason"}


def run_command(*args):
    out = StringIO()
    call_command("clean_ml_run_texts", *args, stdout=out)
    return out.getvalue()


def test_a_dry_run_changes_nothing(runs):
    audit_before = AuditLog.objects.count()

    output = run_command()

    assert "4 run(s) to reword" in output and "Dry run only" in output
    for key, field in FIELD.items():
        runs[key].refresh_from_db()
        assert getattr(runs[key], field) == OLD[key]
    assert AuditLog.objects.count() == audit_before


def test_apply_rewords_with_one_audit_row_each_and_a_rerun_changes_nothing(runs):
    audit_before = AuditLog.objects.count()

    run_command("--apply")

    for key, field in FIELD.items():
        runs[key].refresh_from_db()
        assert getattr(runs[key], field) == NEW[key]
    runs["plain"].refresh_from_db()
    assert runs["plain"].rejection_reason == "Curve check failed: X: keeps 96.1% after 12 months"
    rows = AuditLog.objects.filter(pk__gt=0).order_by("-pk")[:4]
    assert AuditLog.objects.count() == audit_before + 4
    assert {r.resource_type for r in rows} == {"ml.MLTrainingRun"}
    note_row = next(r for r in rows if r.resource_id == str(runs["note"].pk))
    assert note_row.before_data == {"known_issue_note": OLD["note"]}
    assert note_row.after_data["known_issue_note"] == NEW["note"]

    output = run_command("--apply")
    assert "Nothing to change." in output
    assert AuditLog.objects.count() == audit_before + 4


def test_figures_and_deploy_state_are_untouched(runs):
    run_command("--apply")

    runs["rejection"].refresh_from_db()
    runs["note"].refresh_from_db()
    assert (runs["rejection"].rf_r2, runs["rejection"].gb_r2, runs["note"].rf_r2) == (0.6, 0.6136, 0.9335)
