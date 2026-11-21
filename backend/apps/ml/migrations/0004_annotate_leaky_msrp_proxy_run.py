"""Sprint 13 addendum - annotate the one confirmed pre-fix, leaky msrp_proxy
retrain with a human-confirmed known_issue_note. See
apps/ml/data_fixes.py for the matching logic and the full reasoning
(kept there, not here, so it stays directly unit-testable - a migration
module's filename starts with a digit and so can't be imported normally).
"""

from django.db import migrations

from apps.ml.data_fixes import KNOWN_ISSUE_NOTE_LEAKY_MSRP_PROXY_RUN, leaky_msrp_proxy_run_queryset


def annotate_leaky_run(apps, schema_editor):
    MLTrainingRun = apps.get_model("ml", "MLTrainingRun")
    run = leaky_msrp_proxy_run_queryset(MLTrainingRun).first()
    if run is None:
        # Nothing to annotate in this environment (e.g. a fresh install or
        # a test database with no seeded ML training history) - this
        # documents one specific, already-confirmed incident in this
        # project's own dev history, not something every environment
        # necessarily has.
        return
    run.known_issue_note = KNOWN_ISSUE_NOTE_LEAKY_MSRP_PROXY_RUN
    run.save(update_fields=["known_issue_note"])


def clear_known_issue_note(apps, schema_editor):
    MLTrainingRun = apps.get_model("ml", "MLTrainingRun")
    leaky_msrp_proxy_run_queryset(MLTrainingRun).update(known_issue_note="")


class Migration(migrations.Migration):

    dependencies = [
        ("ml", "0003_known_issue_note"),
    ]

    operations = [
        migrations.RunPython(annotate_leaky_run, reverse_code=clear_known_issue_note),
    ]
