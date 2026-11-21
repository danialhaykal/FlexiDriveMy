"""One-off catalog data corrections from the 2026-10-07 buyer-journey audit
(audit batch 1): out-of-date MSRPs, plus the new cc + powertrain fields for
rows entered before they existed. The permanent fix is the new-vehicle
contract (see the project spec); this only repairs the existing rows.

Dry run by default: prints each target's current DB values and what would
change. Nothing is written unless --apply is passed, and then everything
happens in ONE transaction. Idempotent - a second run changes nothing.

Safety rules:
  - Targets match EXACTLY on brand + name + trim. Zero or several matches ->
    skipped and reported; the match is never widened.
  - Every change writes an audit row with the same fields the API path
    writes (before/after = the API serializer's snapshot). There is no
    request here, so ip_address is empty, and the actor is "system" unless
    --actor EMAIL names an account. Existing audit rows are never touched.
  - Toyota Alphard 2.5L is NOT edited in place: it is archived through
    apps.vehicles.archiving.archive_vehicle (so its subscription plan is
    handled and saved comparisons keep their foreign key), and the 2.4
    Executive Lounge that replaced it is created as a new vehicle.
  - Any other row without a powertrain is only reported as "needs specs".

Already applied; do not re-run it. Run 2 fix batch 2 later changed the BMW 320i
Sport (MSRP RM 267,800, year 2026) and the Macan Electric (250 kW) through
apply_catalog_corrections_run2, and this table still holds the older values -
running it again would change those two cars back.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditActionCategory
from apps.audit.services import write_audit_log
from apps.vehicles import archiving
from apps.vehicles.models import BodySegment, Brand, Powertrain, VehicleModel
from apps.vehicles.serializers import VehicleModelSerializer

RESOURCE_TYPE = "vehicles.VehicleModel"
SOURCE_NOTE = "apply_catalog_corrections (audit batch 1, 2026-10-07)"

D = Decimal

# (brand, name, trim) -> fields to set. Anything not listed is left as it is
# ("keep"/"leave" in the audit table). Sources: the 2026-10-07 audit report;
# kW from paultan's hp x 0.7355 is within ~1.5% and stays editable in Fleet.
CORRECTIONS = [
    {
        "key": ("BMW", "3 Series", "320i Sport"),
        "set": {"msrp": D("265800.00"), "engine_capacity_cc": 1998, "powertrain": Powertrain.PETROL, "model_year": 2025},
    },
    {
        "key": ("Mercedes-Benz", "C-Class", "C200 Avantgarde"),
        "set": {"msrp": D("292888.00"), "engine_capacity_cc": 1496, "powertrain": Powertrain.MILD_HYBRID, "model_year": 2026},
    },
    {
        "key": ("Lexus", "ES", "250 Luxury"),
        "set": {"msrp": D("356888.00"), "engine_capacity_cc": 2487, "powertrain": Powertrain.PETROL},
    },
    {
        "key": ("Porsche", "911", "Carrera"),
        "set": {"msrp": D("1430000.00"), "engine_capacity_cc": 2981, "powertrain": Powertrain.PETROL, "engine_capacity_kw": D("290.00")},
    },
    {
        "key": ("Porsche", "Macan", "Base"),
        # paultan (17 Mar 2026): the petrol Macan returned to Malaysia at
        # RM469,000 (2.0L turbo, 265 PS, ~195 kW - matches the stored kW).
        "set": {"msrp": D("469000.00"), "engine_capacity_cc": 1984, "powertrain": Powertrain.PETROL},
    },
    {
        # The audit table calls this "Porsche Macan Electric RWD"; in the DB
        # it is name "Macan Electric" / trim "Macan RWD".
        "key": ("Porsche", "Macan Electric", "Macan RWD"),
        "set": {"engine_capacity_cc": None, "powertrain": Powertrain.BEV},
    },
    {
        "key": ("Volvo", "XC60", "B5 Core"),
        "set": {"engine_capacity_cc": 1969, "powertrain": Powertrain.MILD_HYBRID},
    },
    {
        "key": ("Volvo", "XC90", "Ultra T8"),
        "set": {"engine_capacity_cc": 1969, "powertrain": Powertrain.PHEV},
    },
]

# The 2.5L is no longer sold new in Malaysia (only the 2.4 Turbo is).
ALPHARD_OLD_KEY = ("Toyota", "Alphard", "2.5L")
ALPHARD_NEW = {
    "key": ("Toyota", "Alphard", "2.4 Executive Lounge"),
    "fields": {
        "body_segment": BodySegment.MPV,
        "msrp": D("548000.00"),
        "engine_capacity_cc": 2393,
        "powertrain": Powertrain.PETROL,
        "engine_capacity_kw": D("201.53"),
        "model_year": 2026,
    },
}

FIELD_LABELS = {
    "msrp": "msrp",
    "engine_capacity_cc": "engine_capacity_cc",
    "engine_capacity_kw": "engine_capacity_kw (power kW)",
    "powertrain": "powertrain",
    "model_year": "model_year",
}


def _find(key):
    brand, name, trim = key
    rows = list(VehicleModel.objects.select_related("brand").filter(brand__name=brand, name=name, trim=trim))
    return rows[0] if len(rows) == 1 else None, len(rows)


def _describe(vehicle):
    return (
        f"#{vehicle.pk} {vehicle.brand.name} / {vehicle.name} / {vehicle.trim}: msrp={vehicle.msrp}, "
        f"power_kw={vehicle.engine_capacity_kw}, cc={vehicle.engine_capacity_cc}, "
        f"powertrain={vehicle.powertrain or '-'}, year={vehicle.model_year or '-'}, "
        f"{'active' if vehicle.is_active else 'ARCHIVED'}"
    )


def _snapshot(vehicle):
    return dict(VehicleModelSerializer(vehicle).data)


class Command(BaseCommand):
    help = "Apply the audit batch 1 catalog corrections (dry run unless --apply)."

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

        updates, skipped, problems = [], [], []
        unchanged = 0
        touched_pks = set()

        out("== Corrections to existing vehicles ==")
        for target in CORRECTIONS:
            vehicle, count = _find(target["key"])
            label = " / ".join(target["key"])
            if vehicle is None:
                reason = "no row matches" if count == 0 else f"{count} rows match (never widened)"
                skipped.append((label, reason))
                out(f"- SKIPPED {label}: {reason}")
                continue
            touched_pks.add(vehicle.pk)
            out(f"- {_describe(vehicle)}")
            changes = {f: v for f, v in target["set"].items() if getattr(vehicle, f) != v}
            if target.get("flag"):
                out(f"    FLAG: {target['flag']}")
            if not changes:
                unchanged += 1
                out("    already up to date")
                continue
            for field_name, new_value in changes.items():
                current = getattr(vehicle, field_name)
                out(f"    {FIELD_LABELS[field_name]}: {current if current not in ('', None) else '-'} -> "
                    f"{new_value if new_value not in ('', None) else '-'}")
            candidate = VehicleModel.objects.get(pk=vehicle.pk)
            for field_name, new_value in changes.items():
                setattr(candidate, field_name, new_value)
            try:
                candidate.full_clean()
            except ValidationError as exc:
                problems.append(f"{label}: {exc.message_dict}")
                out(f"    INVALID after change: {exc.message_dict}")
                continue
            updates.append((vehicle, changes))

        out("\n== Toyota Alphard ==")
        old, old_count = _find(ALPHARD_OLD_KEY)
        archive_old = False
        if old is None:
            reason = "no row matches" if old_count == 0 else f"{old_count} rows match (never widened)"
            skipped.append((" / ".join(ALPHARD_OLD_KEY), reason))
            out(f"- SKIPPED archive of {' / '.join(ALPHARD_OLD_KEY)}: {reason}")
        else:
            touched_pks.add(old.pk)
            out(f"- {_describe(old)}")
            if old.is_active:
                archive_old = True
                plan_impact = archiving.impact(old)
                out(f"    would ARCHIVE via archiving.archive_vehicle (also archives: {plan_impact['counts']})")
            else:
                out("    already archived")

        new, new_count = _find(ALPHARD_NEW["key"])
        create_new = False
        new_label = " / ".join(ALPHARD_NEW["key"])
        if new_count > 1:
            skipped.append((new_label, f"{new_count} rows match (never widened)"))
            out(f"- SKIPPED creation of {new_label}: {new_count} rows match")
        elif new is not None:
            touched_pks.add(new.pk)
            out(f"- {_describe(new)}")
            out("    already exists")
        else:
            create_new = True
            brand = old.brand if old is not None else Brand.objects.filter(name=ALPHARD_NEW["key"][0]).first()
            if brand is None:
                create_new = False
                skipped.append((new_label, "brand Toyota not found"))
                out(f"- SKIPPED creation of {new_label}: brand not found")
            else:
                candidate = VehicleModel(
                    brand=brand, name=ALPHARD_NEW["key"][1], trim=ALPHARD_NEW["key"][2], **ALPHARD_NEW["fields"]
                )
                try:
                    candidate.full_clean()
                except ValidationError as exc:
                    create_new = False
                    problems.append(f"{new_label}: {exc.message_dict}")
                    out(f"- INVALID new vehicle {new_label}: {exc.message_dict}")
                else:
                    fields = ", ".join(f"{k}={v}" for k, v in ALPHARD_NEW["fields"].items())
                    out(f"- would CREATE {new_label} ({fields})")
                    out("    no subscription plan yet (Batch 4) - expected")

        out("\n== Other vehicles that still need specs (reported only, left alone) ==")
        needs = [
            v for v in VehicleModel.objects.select_related("brand").order_by("brand__name", "name", "trim")
            if not v.spec_complete and v.pk not in touched_pks
        ]
        for vehicle in needs:
            out(f"- {_describe(vehicle)}")
        if not needs:
            out("- none")

        will_change = len(updates) + int(archive_old) + int(create_new)
        out(f"\n== Summary: {will_change} change(s) ({len(updates)} update(s), "
            f"{int(archive_old)} archive, {int(create_new)} create); {unchanged} already up to date; "
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

        with transaction.atomic():
            for vehicle, changes in updates:
                before = _snapshot(vehicle)
                for field_name, new_value in changes.items():
                    setattr(vehicle, field_name, new_value)
                vehicle.save(update_fields=[*changes, "updated_at"])
                after = _snapshot(vehicle)
                after["correction"] = SOURCE_NOTE
                write_audit_log(
                    actor=actor, action=AuditActionCategory.UPDATE, resource_type=RESOURCE_TYPE,
                    resource_id=vehicle.pk, before=before, after=after,
                )
            if archive_old:
                archiving.archive_vehicle(old, actor=actor, request=None)
            if create_new:
                created = VehicleModel(
                    brand=brand, name=ALPHARD_NEW["key"][1], trim=ALPHARD_NEW["key"][2], **ALPHARD_NEW["fields"]
                )
                created.save()
                after = _snapshot(created)
                after["correction"] = SOURCE_NOTE
                write_audit_log(
                    actor=actor, action=AuditActionCategory.CREATE, resource_type=RESOURCE_TYPE,
                    resource_id=created.pk, before=None, after=after,
                )
        out(self.style.SUCCESS(f"\nDone: {will_change} change(s) applied."))
