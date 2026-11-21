"""Retires the old flat residual seed (audit batch 4).

The dev seed used to give EVERY brand the same ResidualValueMatrix grid
(36 months / standard = 50%, 48 = 42%, 60 = 35%, ...), so a Toyota Alphard, a
Porsche 911 and an electric Macan all got a BMW's residual. The estimator
(apps.policy.residuals) now derives each car's residual from a baseline plus
brand and powertrain adjustments, and a matrix row is an optional OVERRIDE
that wins over it - so those flat rows must go, or they would keep shadowing
the estimate.

This archives (soft-deletes, never deletes) every ACTIVE row whose value
EXACTLY equals the old flat grid for its tenure/band. A row an admin has
since changed - or one for a tenure/band the flat grid never had - is a real
override: it is left alone and reported as such.

Dry run by default: prints every active row and what would happen. Nothing is
written unless --apply is passed, and then everything happens in ONE
transaction. Idempotent - a second run changes nothing. Same safety pattern as
apply_catalog_corrections: one audit row per change (same fields the API path
writes), no request so the IP is empty, the actor is "system" unless --actor
EMAIL names an account, and existing audit rows are never touched.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditActionCategory
from apps.audit.services import write_audit_log
from apps.policy.models import ResidualValueMatrix
from apps.policy.serializers import ResidualValueMatrixSerializer

RESOURCE_TYPE = "policy.ResidualValueMatrix"
SOURCE_NOTE = "retire_flat_residual_seed (audit batch 4, 2026-10-07)"

# The flat grid seed_dev_data used to write for every brand, keyed by
# (tenure_months, mileage_band). Frozen here as history - it is what the
# command compares against, so it must not follow later seed changes.
FLAT_SEED_GRID = {
    36: {"low": "0.5500", "standard": "0.5000", "high": "0.4500", "very_high": "0.4000"},
    48: {"low": "0.4700", "standard": "0.4200", "high": "0.3800", "very_high": "0.3300"},
    60: {"low": "0.4000", "standard": "0.3500", "high": "0.3100", "very_high": "0.2700"},
}


def _flat_value(row):
    value = FLAT_SEED_GRID.get(row.tenure_months, {}).get(row.mileage_band)
    return Decimal(value) if value is not None else None


def _describe(row):
    return (
        f"#{row.pk} {row.brand.name} / {row.tenure_months} months / {row.mileage_band}: "
        f"{row.residual_value_ratio}"
    )


class Command(BaseCommand):
    help = "Archive the residual rows that still equal the old flat seed grid (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes (one transaction).")
        parser.add_argument(
            "--actor", default="", metavar="EMAIL",
            help="Attribute the audit rows to this account (default: system, no actor).",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        actor = None
        if options["actor"]:
            actor = get_user_model().objects.filter(email__iexact=options["actor"]).first()
            if actor is None:
                raise CommandError(f"No user with email {options['actor']!r}.")
        out = self.stdout.write
        out(("APPLY" if apply else "DRY RUN - nothing will be changed") + "\n")

        rows = list(
            ResidualValueMatrix.objects.filter(is_active=True)
            .select_related("brand")
            .order_by("brand__name", "tenure_months", "mileage_band")
        )
        to_archive, overrides = [], []
        out("== Active residual rows ==")
        for row in rows:
            flat = _flat_value(row)
            if flat is not None and row.residual_value_ratio == flat:
                to_archive.append(row)
                out(f"- ARCHIVE  {_describe(row)} (equals the flat seed)")
            elif flat is not None:
                overrides.append(row)
                out(f"- KEEP     {_describe(row)} (flat seed was {flat}: edited, so a real override)")
            else:
                overrides.append(row)
                out(f"- KEEP     {_describe(row)} (not part of the flat seed grid: a real override)")
        if not rows:
            out("- none")

        out(f"\n== Summary: {len(to_archive)} to archive; {len(overrides)} kept as overrides; "
            f"{len(rows)} active row(s) in total ==")
        if not to_archive:
            out("Nothing to change.")
        if not apply:
            out("\nDry run only. Re-run with --apply to make these changes.")
            return
        if not to_archive:
            return

        with transaction.atomic():
            for row in to_archive:
                before = dict(ResidualValueMatrixSerializer(row).data)
                row.is_active = False
                row.archived_by_parent = False
                row.save(update_fields=["is_active", "archived_by_parent", "updated_at"])
                after = dict(ResidualValueMatrixSerializer(row).data)
                after["correction"] = SOURCE_NOTE
                write_audit_log(
                    actor=actor, action=AuditActionCategory.ARCHIVE, resource_type=RESOURCE_TYPE,
                    resource_id=row.pk, before=before, after=after,
                )
        out(self.style.SUCCESS(f"\nDone: {len(to_archive)} row(s) archived."))
