"""Catalog data corrections from Master Test Run 2 (Run 2 fix batch 2, findings
C1 and C2). Same safe pattern as apply_catalog_corrections (audit batch 1),
which is left exactly as it was because its table is what that batch applied:

- BMW 3 Series 320i Sport: MSRP RM 265,800 -> RM 267,800 and model year
  2025 -> 2026 (carbase.my 320i Sport 2026; paultan's 3 Series guide).
  model_year was checked first: it is display-only (never a feature of the ML
  model, never an input of any price, residual, running-cost or subscription
  calculation); it appears only in the vehicle record, the readiness warning,
  the import/research helpers and the unique key (brand, name, trim, year).
- Porsche Macan Electric RWD: power 261.1 kW -> 250.0 kW. The stored value
  treated paultan's "355 hp" (Porsche's brief launch-control output) as PS;
  Porsche's rated system output is 340 PS = 250 kW (launch control 360 PS =
  265 kW). The road tax is NOT assumed: the JPJ EV kW engine
  (apps.policy.operating_costs) computes it, and this command prints it before
  and after.
- Lexus ES 250 Luxury: deliberately NOT changed. The ES 300h at RM 366,888 is
  only an estimate on paultan (19 Oct 2026); the ES 250 stays until an official
  price exists.

Dry run by default: prints each target's current values, what would change and
the running costs before/after. Nothing is written unless --apply is passed,
and then everything happens in ONE transaction. Idempotent - a second run
changes nothing. Every change writes an audit row (the API serializer's
before/after snapshots) under --actor-email's account; existing audit rows are
never touched. Targets match EXACTLY on brand + name + trim (never widened).

Do not re-run apply_catalog_corrections (batch 1) after this: its table still
holds the old BMW price/year and 261.1 kW and would change them back.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditActionCategory
from apps.audit.services import write_audit_log
from apps.policy.operating_costs import OperatingCostConfigError, estimate_operating_costs
from apps.vehicles.management.commands.apply_catalog_corrections import FIELD_LABELS, RESOURCE_TYPE, _describe, _find, _snapshot
from apps.vehicles.models import VehicleModel

SOURCE_NOTE = "apply_catalog_corrections_run2 (Run 2 fix batch 2, 2026-10-19)"

D = Decimal

CORRECTIONS = [
    {
        "key": ("BMW", "3 Series", "320i Sport"),
        "set": {"msrp": D("267800.00"), "model_year": 2026},
    },
    {
        "key": ("Porsche", "Macan Electric", "Macan RWD"),
        "set": {"engine_capacity_kw": D("250.00")},
    },
]


def _running_costs(vehicle):
    """'road tax RM 455.00 (261.1 kW electric - JPJ EV kW schedule, group C); insurance ...' or why not."""
    try:
        costs = estimate_operating_costs(vehicle)
    except OperatingCostConfigError as exc:
        return f"cannot be costed: {exc}"
    return (
        f"road tax RM {costs.road_tax_annual:,.2f} ({costs.basis['road_tax']}); "
        f"insurance RM {costs.insurance_annual:,.2f}; maintenance RM {costs.maintenance_annual:,.2f}"
    )


class Command(BaseCommand):
    help = "Apply the Run 2 catalog corrections: BMW 320i Sport price/year, Macan Electric kW (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes (one transaction).")
        parser.add_argument(
            "--actor-email", "--actor", dest="actor_email", default="", metavar="EMAIL",
            help="Attribute the audit rows to this account (default: system, no actor).",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        actor = None
        if options["actor_email"]:
            actor = get_user_model().objects.filter(email__iexact=options["actor_email"]).first()
            if actor is None:
                raise CommandError(f"No user with email {options['actor_email']!r}.")
        out = self.stdout.write
        out(("APPLY" if apply else "DRY RUN - nothing will be changed") + "\n")

        updates, skipped, problems = [], [], []
        unchanged = 0

        out("== Corrections ==")
        for target in CORRECTIONS:
            vehicle, count = _find(target["key"])
            label = " / ".join(target["key"])
            if vehicle is None:
                reason = "no row matches" if count == 0 else f"{count} rows match (never widened)"
                skipped.append((label, reason))
                out(f"- SKIPPED {label}: {reason}")
                continue
            out(f"- {_describe(vehicle)}")
            changes = {f: v for f, v in target["set"].items() if getattr(vehicle, f) != v}
            if not changes:
                unchanged += 1
                out("    already up to date")
                continue
            for field_name, new_value in changes.items():
                current = getattr(vehicle, field_name)
                out(f"    {FIELD_LABELS[field_name]}: {current if current not in ('', None) else '-'} -> {new_value}")
            candidate = VehicleModel.objects.select_related("brand").get(pk=vehicle.pk)
            for field_name, new_value in changes.items():
                setattr(candidate, field_name, new_value)
            try:
                candidate.full_clean()
            except ValidationError as exc:
                problems.append(f"{label}: {exc.message_dict}")
                out(f"    INVALID after change: {exc.message_dict}")
                continue
            out(f"    running costs before: {_running_costs(vehicle)}")
            out(f"    running costs after : {_running_costs(candidate)}")
            updates.append((vehicle, changes))

        out("\n== Lexus ES 250 Luxury ==")
        out("- NOT changed on purpose: the ES 300h (RM 366,888) is only an estimate on paultan; keep the ES 250 "
            "until an official price exists.")

        will_change = len(updates)
        out(f"\n== Summary: {will_change} change(s); {unchanged} already up to date; "
            f"{len(skipped)} skipped; {len(problems)} invalid ==")
        if will_change == 0 and not problems:
            out("Nothing to change.")
        if problems:
            raise CommandError("Refusing to continue: " + "; ".join(problems))
        if not apply:
            out("\nDry run only. Re-run with --apply to make these changes.")
            return
        if will_change == 0:
            return

        audit_ids = []
        with transaction.atomic():
            for vehicle, changes in updates:
                before = _snapshot(vehicle)
                for field_name, new_value in changes.items():
                    setattr(vehicle, field_name, new_value)
                vehicle.save(update_fields=[*changes, "updated_at"])
                after = _snapshot(vehicle)
                after["correction"] = SOURCE_NOTE
                audit_ids.append(write_audit_log(
                    actor=actor, action=AuditActionCategory.UPDATE, resource_type=RESOURCE_TYPE,
                    resource_id=vehicle.pk, before=before, after=after,
                ).pk)
        out(self.style.SUCCESS(f"\nDone: {will_change} change(s) applied. Audit rows: {', '.join(f'#{i}' for i in audit_ids)}."))
