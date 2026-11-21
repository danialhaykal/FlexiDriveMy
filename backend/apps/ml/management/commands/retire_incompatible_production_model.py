"""Retires a production model the forecast cannot use, and stale deployed flags
(ML batch 1).

The forecast now uses only the resale-price model (log scale,
PredictionTarget.LOG_RESALE_PRICE). A ProductionModel row holding any other
target (run 5 on the dev database: a raw-price model built on msrp_proxy) is
never served - inference refuses it - but it still blocked new models through
the "must beat production's R²" gate and showed as deployed. This command:

- clears ProductionModel's pointer fields (training_run, model_type,
  model_file_path, prediction_target, r2_score, mae, deployed_at) when its
  target is not the current one. The model file itself is NOT deleted;
- sets deployed=False on every run that still says deployed (only one model
  can ever be live, so the others are stale flags from before single-deploy
  was enforced), and marks each retired (retired_at + retired_reason) so it
  stays in the history but can never be deployed again.

Dry run by default: prints what would change. Nothing is written unless
--apply is passed, and then everything happens in ONE transaction, with one
audit row per changed record (no request, so the IP is empty; the actor is
"system" unless --actor-email names an account). Idempotent - a second run
changes nothing.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditActionCategory
from apps.audit.services import write_audit_log
from apps.ml.models import CURRENT_PREDICTION_TARGET, MLTrainingRun, PredictionTarget, ProductionModel
from apps.ml.run_texts import RATIO_RETIRED_REASON, RAW_PRICE_RETIRED_REASON, UNKNOWN_TARGET_RETIRED_REASON

SOURCE_NOTE = "retire_incompatible_production_model (ML batch 1, 2026-10-15)"
SOURCE_NOTE_RUN = "retire_incompatible_production_model --run (ML batch 2)"
PRODUCTION_FIELDS = (
    "training_run_id", "model_type", "model_file_path", "prediction_target", "r2_score", "mae", "deployed_at",
)
STALE_FLAG_REASON = "Retired: stale deployed flag from before single-deploy was enforced."
# Run 3 fix batch 5 (F-26): the reasons are shown on the ML page - plain words, no
# internal feature names or batch codes (apps/ml/run_texts.py).
_PRODUCTION_REASON_BY_TARGET = {
    PredictionTarget.RAW_RESALE_PRICE: RAW_PRICE_RETIRED_REASON,
    PredictionTarget.VALUE_RETENTION_RATIO: RATIO_RETIRED_REASON,
}
_UNKNOWN_TARGET_REASON = UNKNOWN_TARGET_RETIRED_REASON


def production_snapshot(production):
    data = {field: getattr(production, field) for field in PRODUCTION_FIELDS}
    if data["deployed_at"] is not None:
        data["deployed_at"] = data["deployed_at"].isoformat()
    return data


def run_snapshot(run):
    return {
        "deployed": run.deployed,
        "deploy_eligible": run.deploy_eligible,
        "retired_at": run.retired_at.isoformat() if run.retired_at else None,
        "retired_reason": run.retired_reason,
    }


def production_needs_clearing(production):
    """True when production holds anything and its target is not the current one."""
    holds_something = any(
        getattr(production, field) not in (None, "") for field in PRODUCTION_FIELDS if field != "prediction_target"
    )
    return holds_something and production.prediction_target != CURRENT_PREDICTION_TARGET


def plan(production):
    """(clear_production, [(run, reason), ...]) - what --apply would do."""
    clear = production is not None and production_needs_clearing(production)
    production_run_id = production.training_run_id if clear else None
    production_reason = (
        _PRODUCTION_REASON_BY_TARGET.get(production.prediction_target, _UNKNOWN_TARGET_REASON) if clear else None
    )

    retire = []
    candidates = MLTrainingRun.objects.filter(deployed=True)
    if production_run_id is not None:
        candidates = candidates | MLTrainingRun.objects.filter(pk=production_run_id, retired_at__isnull=True)
    for run in candidates.distinct().order_by("pk"):
        if run.pk == production_run_id:
            retire.append((run, production_reason))
        elif production is not None and run.pk == production.training_run_id:
            continue  # the compatible, live production run keeps its flag
        else:
            retire.append((run, STALE_FLAG_REASON))
    return clear, retire


class Command(BaseCommand):
    help = (
        "Clear a production model the forecast cannot use and retire stale deployed runs "
        "(dry run unless --apply)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes (one transaction).")
        parser.add_argument(
            "--actor-email", default="", metavar="EMAIL",
            help="Attribute the audit rows to this account (default: system, no actor).",
        )
        parser.add_argument(
            "--run", type=int, default=None, metavar="ID",
            help="ML batch 2: retire just this one undeployed run instead (needs --reason).",
        )
        parser.add_argument("--reason", default="", help="With --run: the retired_reason to record.")

    def handle(self, *args, **options):
        apply = options["apply"]
        actor = None
        if options["actor_email"]:
            actor = get_user_model().objects.filter(email__iexact=options["actor_email"]).first()
            if actor is None:
                raise CommandError(f"No user with email {options['actor_email']!r}.")
        if options["run"] is not None:
            return self.retire_one_run(options["run"], options["reason"].strip(), apply, actor)
        if options["reason"]:
            raise CommandError("--reason is only used with --run.")
        out = self.stdout.write
        out(("APPLY" if apply else "DRY RUN - nothing will be changed") + "\n")

        production = ProductionModel.objects.filter(pk=1).first()
        clear, retire = plan(production)

        out("== Production model ==")
        if production is None:
            out("- no production row")
        else:
            out(
                f"- run {production.training_run_id}, {production.model_type or 'no model'}, target "
                f"{production.prediction_target or '(blank)'}, R² {production.r2_score}"
            )
            if clear:
                out(f"- CLEAR    target is not {CURRENT_PREDICTION_TARGET}; the model file is kept on disk "
                    f"({production.model_file_path})")
            else:
                out("- KEEP     nothing to clear")

        out("\n== Runs to retire ==")
        for run, reason in retire:
            out(f"- RETIRE   run {run.pk} (deployed={run.deployed}): {reason}")
        if not retire:
            out("- none")

        changes = int(clear) + len(retire)
        out(f"\n== Summary: {changes} change(s): production {'cleared' if clear else 'unchanged'}; "
            f"{len(retire)} run(s) retired ==")
        if not changes:
            out("Nothing to change.")
        if not apply:
            out("\nDry run only. Re-run with --apply to make these changes.")
            return
        if not changes:
            return

        audit_ids = []
        with transaction.atomic():
            now = timezone.now()
            if clear:
                before = production_snapshot(production)
                production.training_run = None
                production.model_type = ""
                production.model_file_path = ""
                production.prediction_target = ""
                production.r2_score = None
                production.mae = None
                production.deployed_at = None
                production.save()
                after = production_snapshot(production)
                after["correction"] = SOURCE_NOTE
                audit_ids.append(write_audit_log(
                    actor=actor, action=AuditActionCategory.UPDATE, resource_type="ml.ProductionModel",
                    resource_id=production.pk, before=before, after=after,
                ).pk)
            for run, reason in retire:
                before = run_snapshot(run)
                run.deployed = False
                run.retired_at = now
                run.retired_reason = reason
                run.save(update_fields=["deployed", "retired_at", "retired_reason", "updated_at"])
                after = run_snapshot(run)
                after["correction"] = SOURCE_NOTE
                audit_ids.append(write_audit_log(
                    actor=actor, action=AuditActionCategory.UPDATE, resource_type="ml.MLTrainingRun",
                    resource_id=run.pk, before=before, after=after,
                ).pk)
        out(self.style.SUCCESS(f"\nDone: {changes} change(s). Audit rows: {', '.join(f'#{i}' for i in audit_ids)}."))

    def retire_one_run(self, run_id, reason, apply, actor):
        """--run ID --reason TEXT: retire one undeployed run (it stays in the
        history, can never be deployed, and is no longer deploy-eligible).
        Refuses a deployed run - that is the production path above. A run
        already retired is left alone (0 changes)."""
        out = self.stdout.write
        if not reason:
            raise CommandError("--run needs --reason.")
        run = MLTrainingRun.objects.filter(pk=run_id).first()
        if run is None:
            raise CommandError(f"No training run {run_id}.")
        if run.deployed:
            raise CommandError(f"Run {run_id} is deployed; retire it with the production path, not --run.")
        out(("APPLY" if apply else "DRY RUN - nothing will be changed") + "\n")
        out("== Run to retire ==")
        if run.retired_at is not None:
            out(f"- KEEP     run {run.pk} is already retired ({run.retired_reason})")
            out("\n== Summary: 0 change(s) ==")
            out("Nothing to change.")
            if not apply:
                out("\nDry run only. Re-run with --apply to make these changes.")
            return
        out(f"- RETIRE   run {run.pk} (deploy_eligible={run.deploy_eligible}): {reason}")
        out("\n== Summary: 1 change(s) ==")
        if not apply:
            out("\nDry run only. Re-run with --apply to make these changes.")
            return
        with transaction.atomic():
            before = run_snapshot(run)
            run.retired_at = timezone.now()
            run.retired_reason = reason
            run.deploy_eligible = False
            run.save(update_fields=["retired_at", "retired_reason", "deploy_eligible", "updated_at"])
            after = run_snapshot(run)
            after["correction"] = SOURCE_NOTE_RUN
            audit = write_audit_log(
                actor=actor, action=AuditActionCategory.UPDATE, resource_type="ml.MLTrainingRun",
                resource_id=run.pk, before=before, after=after,
            )
        out(self.style.SUCCESS(f"\nDone: 1 change(s). Audit rows: #{audit.pk}."))
