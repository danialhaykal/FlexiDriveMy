"""Rewords training-run texts stored with developer wording (Run 3 fix batch 5, F-26).

The ML Model Management page shows each run's rejection reason, known-issue note
and retirement reason as stored. Rows written before this batch carry batch codes
("(ML batch 1)"), internal feature names (msrp_proxy, leave-one-out) and raw model
keys ("from gradient_boosting"). This command rewords exactly those through
apps.ml.run_texts.plain_run_text - every other word stays.

Dry run by default: prints what would change. --apply writes, in ONE transaction,
one audit row per changed run (before/after of the changed fields; no request, so
no IP; the actor is "system" unless --actor-email names an account). Idempotent: a
second run changes nothing. Figures, metrics and deploy state are never touched.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditActionCategory
from apps.audit.services import write_audit_log
from apps.ml.models import MLTrainingRun
from apps.ml.run_texts import plain_run_text

TEXT_FIELDS = ("rejection_reason", "known_issue_note", "retired_reason")
SOURCE_NOTE = "clean_ml_run_texts: plain wording on the ML page (no developer text)"


def planned_changes():
    """[(run, {field: (before, after)}), ...] for every run whose text would change."""
    changes = []
    for run in MLTrainingRun.objects.order_by("pk"):
        fields = {}
        for name in TEXT_FIELDS:
            before = getattr(run, name) or ""
            after = plain_run_text(before)
            if after != before:
                fields[name] = (before, after)
        if fields:
            changes.append((run, fields))
    return changes


class Command(BaseCommand):
    help = "Reword training-run texts stored with developer wording (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes (one transaction).")
        parser.add_argument("--actor-email", default="", metavar="EMAIL",
                            help="Attribute the audit rows to this account (default: system, no actor).")

    def handle(self, *args, **options):
        out = self.stdout.write
        apply = options["apply"]
        actor = None
        if options["actor_email"]:
            actor = get_user_model().objects.filter(email__iexact=options["actor_email"]).first()
            if actor is None:
                raise CommandError("No user with that email.")
        out(("APPLY" if apply else "DRY RUN - nothing will be changed") + "\n")

        changes = planned_changes()
        for run, fields in changes:
            for name, (before, after) in fields.items():
                out(f"- run {run.pk} {name}:\n    was: {before}\n    now: {after}")
        out(f"\n== Summary: {len(changes)} run(s) to reword ==")
        if not changes:
            out("Nothing to change.")
            return
        if not apply:
            out("\nDry run only. Re-run with --apply to make these changes.")
            return

        audit_ids = []
        with transaction.atomic():
            for run, fields in changes:
                for name, (_before, after) in fields.items():
                    setattr(run, name, after)
                run.save(update_fields=[*fields, "updated_at"])
                audit_ids.append(write_audit_log(
                    actor=actor, action=AuditActionCategory.UPDATE, resource_type="ml.MLTrainingRun",
                    resource_id=run.pk,
                    before={name: before for name, (before, _after) in fields.items()},
                    after={**{name: after for name, (_before, after) in fields.items()}, "correction": SOURCE_NOTE},
                ).pk)
        out(self.style.SUCCESS(f"\nDone: {len(changes)} run(s). Audit rows: {', '.join(f'#{i}' for i in audit_ids)}."))
