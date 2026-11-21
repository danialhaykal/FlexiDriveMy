"""Retires the formula-priced Subscription plans (audit batch 5).

The dev seed filled every SubscriptionPlan with MSRP / 40 (exactly 2.5% of
price): a formula, not provider data. apps.policy.subscription_pricing now
estimates every car's fee from its residual, running costs and the
SubscriptionPolicy, and a plan is only an optional provider-quote OVERRIDE that
wins over the estimate - so the formula plans must go, or they would keep
shadowing it (and would price the same car identically at 12 and 36 months).

This archives (soft-deletes, never deletes) every ACTIVE plan whose fee
EXACTLY equals round(msrp / 40, 2). Because the seed wrote each fee when the
car had its OLD price (the catalog corrections later changed several MSRPs, so
the plan no longer equals msrp/40 of today's price), a plan is also treated as
formula-priced when its fee equals msrp/40 at a price the vehicle PROVABLY had
before - read from the append-only audit log's before/after snapshots, never
guessed. A plan matching neither is a real quote: it is left alone and
reported.

Dry run by default: prints every active plan and what would happen. Nothing is
written unless --apply is passed, and then everything happens in ONE
transaction. Idempotent - a second run changes nothing. Same safety pattern as
retire_flat_residual_seed: one audit row per change (same fields the API path
writes), no request so the IP is empty, the actor is "system" unless --actor
EMAIL names an account, and existing audit rows are never touched.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditActionCategory, AuditLog
from apps.audit.services import write_audit_log
from apps.policy.models import SubscriptionPlan
from apps.policy.serializers import SubscriptionPlanSerializer

RESOURCE_TYPE = "policy.SubscriptionPlan"
SOURCE_NOTE = "retire_formula_subscription_plans (audit batch 5, 2026-10-07)"
TWO_PLACES = Decimal("0.01")


def formula_fee(msrp):
    """The old seed formula: round(msrp / 40, 2)."""
    return (Decimal(msrp) / Decimal(40)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def earlier_prices(vehicle):
    """{msrp: audit_log_id} for every MSRP the audit log shows this vehicle
    having had (from both the before and after snapshots)."""
    prices = {}
    for row in AuditLog.objects.filter(resource_type="vehicles.VehicleModel", resource_id=str(vehicle.pk)).order_by("id"):
        for snapshot in (row.before_data, row.after_data):
            if isinstance(snapshot, dict) and snapshot.get("msrp") is not None:
                try:
                    prices.setdefault(Decimal(str(snapshot["msrp"])), row.pk)
                except InvalidOperation:
                    continue
    return prices


def classify(plan):
    """("archive" | "keep", reason)."""
    vehicle = plan.vehicle
    if plan.fee_monthly == formula_fee(vehicle.msrp):
        return "archive", f"equals msrp/40 (RM {vehicle.msrp:,.2f} / 40)"
    for price, audit_id in earlier_prices(vehicle).items():
        if price != vehicle.msrp and plan.fee_monthly == formula_fee(price):
            return "archive", (
                f"equals msrp/40 at the vehicle's earlier price RM {price:,.2f} (audit log row #{audit_id}); "
                f"its price is now RM {vehicle.msrp:,.2f}"
            )
    return "keep", f"fee differs from msrp/40 (RM {formula_fee(vehicle.msrp):,.2f}): treated as a real provider quote"


def _describe(plan):
    return f"#{plan.pk} {plan.vehicle} (vehicle #{plan.vehicle_id}): fee RM {plan.fee_monthly:,.2f}"


class Command(BaseCommand):
    help = "Archive the Subscription plans priced by the old msrp/40 seed formula (dry run unless --apply)."

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

        plans = list(
            SubscriptionPlan.objects.filter(is_active=True).select_related("vehicle__brand").order_by("vehicle_id", "id")
        )
        to_archive, quotes = [], []
        out("== Active subscription plans ==")
        for plan in plans:
            decision, reason = classify(plan)
            if decision == "archive":
                to_archive.append(plan)
                out(f"- ARCHIVE  {_describe(plan)} - {reason}")
            else:
                quotes.append(plan)
                out(f"- KEEP     {_describe(plan)} - {reason}")
        if not plans:
            out("- none")

        out(f"\n== Summary: {len(to_archive)} to archive; {len(quotes)} kept as provider quotes; "
            f"{len(plans)} active plan(s) in total ==")
        if not to_archive:
            out("Nothing to change.")
        if not apply:
            out("\nDry run only. Re-run with --apply to make these changes.")
            return
        if not to_archive:
            return

        with transaction.atomic():
            for plan in to_archive:
                before = dict(SubscriptionPlanSerializer(plan).data)
                plan.is_active = False
                plan.archived_by_parent = False
                plan.save(update_fields=["is_active", "archived_by_parent", "updated_at"])
                after = dict(SubscriptionPlanSerializer(plan).data)
                after["correction"] = SOURCE_NOTE
                write_audit_log(
                    actor=actor, action=AuditActionCategory.ARCHIVE, resource_type=RESOURCE_TYPE,
                    resource_id=plan.pk, before=before, after=after,
                )
        out(self.style.SUCCESS(f"\nDone: {len(to_archive)} plan(s) archived."))
