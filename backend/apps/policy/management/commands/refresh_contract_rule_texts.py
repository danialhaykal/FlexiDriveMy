"""Tidies the brand contract rules' wear-and-tear texts: removes stale ringgit
fee amounts (run 1, finding B7) and rewords a sentence that names one model (run
2 fix batch 3, finding B7).

Several brand rules end with frozen sentences such as "...the fee is 6 x this
app's BMW 320i subscription fee (RM6,145), copying the KINTO rule." or "the
fee shown is 6 x RM7,355.00". The app now computes every fee from the rule's
numbers for the request on screen, so these amounts are stale and contradict
the card. For every ACTIVE rule this removes each clause that holds a ringgit
amount (not a per-km rate) AND talks about a fee or an early exit - see
apps.policy.rule_text for the exact rule - and keeps everything else word for
word, including source citations and the mileage/condition wording.

A brand's rule applies to every car of that brand, so "RM0.50 (top of range) is
used here for the Alphard" / "... for the ES 250" is reworded to "... is used
here as the estimate for this brand's cars" when what follows "for the" names
one of the brand's own models (apps.policy.rule_text.reword_model_specific_
estimate). The rest of the text is unchanged.

Dry run by default: prints each rule's text before and after. Nothing is
written unless --apply is passed, and then everything happens in ONE
transaction. Idempotent - a second run changes nothing. One audit row per
changed rule (same fields the API writes), no request so the IP is empty, the
actor is "system" unless --actor EMAIL names an account; existing audit rows
are never touched.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.models import AuditActionCategory
from apps.audit.services import write_audit_log
from apps.policy.models import ContractPenaltyRule
from apps.policy.rule_text import model_name_candidates, reword_model_specific_estimate, strip_stale_fee_amounts
from apps.policy.serializers import ContractPenaltyRuleSerializer
from apps.vehicles.models import VehicleModel

RESOURCE_TYPE = "policy.ContractPenaltyRule"
STALE_FEE_NOTE = "refresh_contract_rule_texts (run 1 fix batch 1, 2026-10-13)"
MODEL_NAME_NOTE = "refresh_contract_rule_texts: no model named in a brand rule (run 2 fix batch 3, 2026-10-20)"


def refreshed_text(rule):
    """(new text, what changed) for one rule: the stale ringgit fee clauses removed,
    then a sentence that names one of the brand's models reworded for the brand's
    cars. A brand-less (default) rule has no models to name."""
    before = rule.wear_tear_tolerance_description
    notes = []
    text = strip_stale_fee_amounts(before)
    if text != before:
        notes.append(STALE_FEE_NOTE)
    if rule.brand_id:
        names = model_name_candidates(VehicleModel.objects.filter(brand_id=rule.brand_id).values_list("name", "trim"))
        reworded = reword_model_specific_estimate(text, names)
        if reworded != text:
            notes.append(MODEL_NAME_NOTE)
            text = reworded
    return text, notes


def _label(rule):
    return f"#{rule.pk} {rule.brand.name if rule.brand_id else 'Default rule'}"


class Command(BaseCommand):
    help = "Remove stale ringgit fee amounts from contract rule texts (dry run unless --apply)."

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

        rules = list(ContractPenaltyRule.objects.filter(is_active=True).select_related("brand").order_by("pk"))
        changes = []
        out("== Active contract rules ==")
        for rule in rules:
            before = rule.wear_tear_tolerance_description
            after, notes = refreshed_text(rule)
            if after == before:
                out(f"- OK      {_label(rule)}: no ringgit fee amount and no model name in the text")
                continue
            changes.append((rule, before, after, notes))
            out(f"- CHANGE  {_label(rule)}")
            out(f"    BEFORE: {before}")
            out(f"    AFTER:  {after}")
        if not rules:
            out("- none")

        out(f"\n== Summary: {len(changes)} to change; {len(rules) - len(changes)} already clean; "
            f"{len(rules)} active rule(s) in total ==")
        if not changes:
            out("Nothing to change.")
        if not apply:
            out("\nDry run only. Re-run with --apply to make these changes.")
            return
        if not changes:
            return

        with transaction.atomic():
            for rule, _, after, notes in changes:
                snapshot_before = dict(ContractPenaltyRuleSerializer(rule).data)
                rule.wear_tear_tolerance_description = after
                rule.save(update_fields=["wear_tear_tolerance_description", "updated_at"])
                snapshot_after = dict(ContractPenaltyRuleSerializer(rule).data)
                snapshot_after["correction"] = "; ".join(notes)
                write_audit_log(
                    actor=actor, action=AuditActionCategory.UPDATE, resource_type=RESOURCE_TYPE,
                    resource_id=rule.pk, before=snapshot_before, after=snapshot_after,
                )
        out(self.style.SUCCESS(f"\nDone: {len(changes)} rule(s) updated."))
