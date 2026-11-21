"""Rewrites stored Financial Profile mileage values to the current bands
(audit batch 6, F6).

The profile used to store a literal-km value ("10000" / "20000" / "30000");
it now stores the same four named bands as the compare screens (low /
standard / high / very_high). The API already maps an old value on read, so
nothing breaks while a legacy row exists - this just tidies the stored data so
no reader has to rely on the mapping. Mapping (each legacy value is the LOWER
edge of exactly one band, the mapping every reader already used):

    "10000" -> standard     "20000" -> high     "30000" -> very_high

Dry run by default: lists each profile and what would change. Nothing is
written unless --apply is passed, and then everything happens in ONE
transaction. Idempotent - a second run changes nothing. One audit row per
change (no request, so the IP is empty; the actor is "system" unless --actor
EMAIL names an account); existing audit rows are never touched.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditActionCategory
from apps.audit.services import write_audit_log
from apps.profiles.models import FinancialProfile, normalize_mileage_band
from apps.policy.models import MileageBand

RESOURCE_TYPE = "profiles.FinancialProfile"
SOURCE_NOTE = "normalize_profile_mileage_bands (audit batch 6, 2026-10-07)"


class Command(BaseCommand):
    help = "Rewrite legacy profile mileage values to the four current bands (dry run unless --apply)."

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

        profiles = list(FinancialProfile.objects.select_related("user").order_by("pk"))
        to_change, current, unknown = [], 0, []
        out("== Financial profiles ==")
        for profile in profiles:
            stored = profile.annual_mileage_band
            if stored in MileageBand.values:
                current += 1
                out(f"- OK       #{profile.pk} {profile.user.email}: {stored!r} (already a current band)")
                continue
            target = normalize_mileage_band(stored)
            if target is None:
                unknown.append(profile)
                out(f"- UNKNOWN  #{profile.pk} {profile.user.email}: {stored!r} maps to no band - left alone")
                continue
            to_change.append((profile, stored, target))
            out(f"- CHANGE   #{profile.pk} {profile.user.email}: {stored!r} -> {target!r}")
        if not profiles:
            out("- none")

        out(f"\n== Summary: {len(to_change)} to change; {current} already current; "
            f"{len(unknown)} unknown (left alone); {len(profiles)} profile(s) in total ==")
        if not to_change:
            out("Nothing to change.")
        if not apply:
            out("\nDry run only. Re-run with --apply to make these changes.")
            return
        if not to_change:
            return

        with transaction.atomic():
            for profile, stored, target in to_change:
                profile.annual_mileage_band = target
                profile.save(update_fields=["annual_mileage_band", "updated_at"])
                write_audit_log(
                    actor=actor, action=AuditActionCategory.UPDATE, resource_type=RESOURCE_TYPE,
                    resource_id=profile.pk,
                    before={"id": profile.pk, "annual_mileage_band": stored},
                    after={"id": profile.pk, "annual_mileage_band": target, "correction": SOURCE_NOTE},
                )
        out(self.style.SUCCESS(f"\nDone: {len(to_change)} profile(s) updated."))
