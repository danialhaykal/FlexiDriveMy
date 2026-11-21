"""Removes the dev/QA test rows left behind by live testing, before the
FYP2 demo. A one-off, explicitly-requested HARD delete of known test data -
NOT a substitute for the app's normal soft-delete (archive) path, which
every real admin action still uses.

Dry run by default: prints every target row, plus every dependent row
Django's deletion Collector would cascade to, null out, or be blocked by.
Nothing is written unless --apply is passed, and then everything happens in
one transaction.

Targets are matched on natural keys (name/trim/email/title), never on ids
alone. Safety rules:
  - A user whose deletion would touch a row that must be left alone
    (AuditLog - append-only, F013; PDFExportJob; simplejwt's token tables)
    is DEACTIVATED (is_active=False) instead of deleted. All of those FKs
    are SET_NULL, so deleting the user would rewrite those rows.
  - A target blocked by a PROTECT FK from a row that isn't itself being
    removed in this run is skipped and reported - the target list is never
    widened automatically.
  - Brands/vehicles must still be archived (and brands untiered), or
    they're skipped: this command never removes live catalog data.
"""

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import router, transaction
from django.db.models.deletion import Collector, ProtectedError, RestrictedError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.audit.models import AuditLog
from apps.exports.models import PDFExportJob
from apps.scenarios.models import SavedScenario
from apps.vehicles.models import Brand, VehicleModel, VehicleSpecDraft

TARGET_BRAND_NAMES = ["DebugBrand", "Volkswagen", "XlsxBrand"]
TARGET_VEHICLES = [("BMW", "Test Model", "Base"), ("Toyota", "QA Crash Test", "Test")]
TARGET_USER_EMAILS = [
    "qa.livetest.2026-10-05@example.com",
    "qa.tester@example.com",
    "qa.tester+duplicate-3@example.com",
]
TARGET_SCENARIO_TITLES = ["QA test - Alphard 60mo"]

# Rows this command must never delete or modify.
UNTOUCHABLE_MODELS = (AuditLog, PDFExportJob, OutstandingToken, BlacklistedToken)

# Apply order: dependants before the rows they PROTECT.
APPLY_ORDER = ["scenario", "spec draft", "user", "vehicle", "brand"]


def _label(obj):
    return f"{obj._meta.label}#{obj.pk} ({obj})"


def _collect(obj):
    """What deleting `obj` on its own would do, without doing it."""
    collector = Collector(using=router.db_for_write(type(obj)), origin=obj)
    try:
        collector.collect([obj])
    except (ProtectedError, RestrictedError) as exc:
        blockers = exc.protected_objects if isinstance(exc, ProtectedError) else exc.restricted_objects
        return {"blocked_by": list(blockers), "deletes": [], "updates": []}

    deletes = [row for model_rows in collector.data.values() for row in model_rows]
    for qs in collector.fast_deletes:
        deletes.extend(qs)
    updates = []
    for (field, value), groups in collector.field_updates.items():
        for group in groups:  # each group is a queryset or a list of instances
            updates.extend((row, field.name, value) for row in group)
    return {"blocked_by": [], "deletes": deletes, "updates": updates}


class Command(BaseCommand):
    help = "Remove known dev/QA test data (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Actually delete/deactivate (one transaction).")

    def handle(self, *args, **options):
        apply = options["apply"]
        out = self.stdout.write
        out(("APPLY" if apply else "DRY RUN - nothing will be changed") + "\n")

        targets, deactivations, skipped, not_found, no_action = self._resolve()
        plans = {id(obj): _collect(obj) for _kind, obj in targets}

        # A PROTECT blocker is fine only if that blocking row is itself
        # removed earlier in this same run. Re-check until stable, since
        # skipping one target can strand another that relied on it.
        while True:
            removed = {
                (type(row), row.pk)
                for _kind, obj in targets
                for row in plans[id(obj)]["deletes"]
            }
            newly_skipped = []
            for kind, obj in targets:
                outside = [
                    b for b in plans[id(obj)]["blocked_by"] if (type(b), b.pk) not in removed
                ]
                if outside:
                    newly_skipped.append((kind, obj, outside))
            if not newly_skipped:
                break
            for kind, obj, outside in newly_skipped:
                targets.remove((kind, obj))
                skipped.append(
                    (kind, obj, "blocked (PROTECT) by rows outside the target list: "
                     + "; ".join(_label(b) for b in outside))
                )

        self._report(targets, plans, deactivations, skipped, not_found, no_action, "Will" if apply else "Would")

        if not apply:
            out("\nDry run only. Re-run with --apply to make these changes.")
            return

        with transaction.atomic():
            for user, _reasons in deactivations:
                user.is_active = False
                user.save(update_fields=["is_active"])
            for kind in APPLY_ORDER:
                for target_kind, obj in targets:
                    if target_kind == kind:
                        type(obj).objects.filter(pk=obj.pk).delete()
        out(self.style.SUCCESS(
            f"\nDone: deleted {len(targets)} target row(s), deactivated {len(deactivations)} user(s)."
        ))

    # ------------------------------------------------------------- resolution

    def _resolve(self):
        targets, deactivations, skipped, not_found, no_action = [], [], [], [], []

        for title in TARGET_SCENARIO_TITLES:
            matches = list(SavedScenario.objects.filter(title=title).select_related("user"))
            if not matches:
                not_found.append(f"scenario titled {title!r}")
            targets.extend(("scenario", s) for s in matches)

        targets.extend(
            ("spec draft", d) for d in VehicleSpecDraft.objects.filter(approved_vehicle__isnull=True).order_by("pk")
        )

        User = get_user_model()
        for email in TARGET_USER_EMAILS:
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                not_found.append(f"user {email}")
                continue
            reasons = [
                f"{model._meta.label} x{count}"
                for model, count in self._untouchable_refs(user).items()
            ]
            if reasons:
                if user.is_active:
                    deactivations.append((user, reasons))
                else:
                    no_action.append(f"{_label(user)}: already inactive, kept (deleting would modify "
                                     + ", ".join(reasons) + ")")
            else:
                targets.append(("user", user))

        for brand_name, name, trim in TARGET_VEHICLES:
            vehicle = VehicleModel.objects.filter(brand__name=brand_name, name=name, trim=trim).first()
            if vehicle is None:
                not_found.append(f"vehicle {brand_name} {name!r} / {trim!r}")
            elif vehicle.is_active:
                skipped.append(("vehicle", vehicle, "still active (only archived test vehicles are removed)"))
            else:
                targets.append(("vehicle", vehicle))

        for brand_name in TARGET_BRAND_NAMES:
            brand = Brand.objects.filter(name=brand_name).first()
            if brand is None:
                not_found.append(f"brand {brand_name}")
            elif brand.is_active or brand.tier_code:
                skipped.append(("brand", brand, "not an archived, untiered brand"))
            else:
                targets.append(("brand", brand))

        return targets, deactivations, skipped, not_found, no_action

    @staticmethod
    def _untouchable_refs(user):
        counts = {
            AuditLog: AuditLog.objects.filter(actor=user).count(),
            PDFExportJob: PDFExportJob.objects.filter(user=user).count(),
            OutstandingToken: OutstandingToken.objects.filter(user=user).count(),
            BlacklistedToken: BlacklistedToken.objects.filter(token__user=user).count(),
        }
        return {model: count for model, count in counts.items() if count}

    # ---------------------------------------------------------------- report

    def _report(self, targets, plans, deactivations, skipped, not_found, no_action, verb):
        out = self.stdout.write
        by_kind = defaultdict(list)
        for kind, obj in targets:
            by_kind[kind].append(obj)

        out(f"== {verb} delete {len(targets)} target row(s) ==")
        for kind in APPLY_ORDER:
            for obj in by_kind[kind]:
                plan = plans[id(obj)]
                detail = ""
                if isinstance(obj, VehicleSpecDraft):
                    detail = f" created {obj.created_at:%Y-%m-%d %H:%M} by {obj.requested_by or 'unknown'}"
                out(f"- [{kind}] {_label(obj)}{detail}")
                for row in plan["deletes"]:
                    if row.pk == obj.pk and type(row) is type(obj):
                        continue
                    out(f"    cascades to delete: {_label(row)}")
                for row, field_name, value in plan["updates"]:
                    out(f"    sets {field_name}={value!r} on: {_label(row)}")
                for row in plan["blocked_by"]:
                    out(f"    blocked by (removed earlier in this run): {_label(row)}")
                touched = [
                    r for r in plan["deletes"] + [u[0] for u in plan["updates"]]
                    if isinstance(r, UNTOUCHABLE_MODELS)
                ]
                if touched:  # resolution should make this impossible - fail loudly if not
                    raise RuntimeError(f"{_label(obj)} would touch protected rows: {touched}")

        out(f"\n== {verb} deactivate {len(deactivations)} user(s) instead of deleting ==")
        for user, reasons in deactivations:
            out(f"- {_label(user)}: deleting would modify {', '.join(reasons)} (SET_NULL) -> is_active=False")

        out(f"\n== Skipped {len(skipped)} target(s) ==")
        for kind, obj, reason in skipped:
            out(f"- [{kind}] {_label(obj)}: {reason}")

        out(f"\n== Not found {len(not_found)} ==")
        for item in not_found:
            out(f"- {item}")

        out(f"\n== Nothing to do {len(no_action)} ==")
        for item in no_action:
            out(f"- {item}")
