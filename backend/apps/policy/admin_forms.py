"""Run 3 fix batch 5 (F-14): Django admin never shows a raw database-constraint
name. A save the database would refuse used to read 'Constraint
"subscription_policy_min_lte_max_tenure" is violated.'; every policy admin form
now says it in plain words instead.

PlainConstraintMessagesForm rewrites Django's default constraint sentence after
the model validation has run, using CONSTRAINT_MESSAGES (one plain sentence per
constraint on the policy tables), with a plain fallback for any constraint added
later, and drops a sentence the form's own clean() already gave. The save is
still refused exactly as before - only the words change.
"""

import re

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError

from . import mileage
from .models import BAND_KM_ASCENDING_MESSAGE

SHORTEST_LONGER_THAN_LONGEST = "The shortest plan cannot be longer than the longest plan."
ARCHIVE_FIRST = "Archive it first, then add the replacement."

CONSTRAINT_MESSAGES = {
    "subscription_policy_min_lte_max_tenure": SHORTEST_LONGER_THAN_LONGEST,
    "subscription_policy_band_km_ascending": BAND_KM_ASCENDING_MESSAGE,
    "unique_active_subscription_policy": f"There is already an active subscription policy. {ARCHIVE_FIRST}",
    "road_tax_cc_band_min_lte_max": "The lowest cc cannot be above the highest cc.",
    "unique_active_road_tax_cc_band_per_class_min": (
        f"There is already an active band starting at this cc for this registration class. {ARCHIVE_FIRST}"),
    "unique_active_ev_road_tax_group_label": f"There is already an active group with this label. {ARCHIVE_FIRST}",
    "unique_active_operating_cost_rate_per_powertrain": (
        f"There is already an active rate for this powertrain. {ARCHIVE_FIRST}"),
    "residual_adjustment_exactly_one_of_brand_or_powertrain": "Choose either a brand or a powertrain - one of the two.",
    "unique_active_residual_adjustment_per_brand": f"There is already an active adjustment for this brand. {ARCHIVE_FIRST}",
    "unique_active_residual_adjustment_per_powertrain": (
        f"There is already an active adjustment for this powertrain. {ARCHIVE_FIRST}"),
    "unique_active_residual_baseline_per_tenure_band": (
        f"There is already an active baseline for this tenure and mileage band. {ARCHIVE_FIRST}"),
    "unique_active_interest_rate_per_brand": f"This brand already has an active interest rate. {ARCHIVE_FIRST}",
    "unique_active_residual_ratio_per_brand_tenure_band": (
        f"This brand already has an active override for this tenure and mileage band. {ARCHIVE_FIRST}"),
    "unique_active_subscription_plan_per_vehicle": f"This car already has an active provider quote. {ARCHIVE_FIRST}",
    "unique_active_contract_penalty_rule_per_brand": f"This brand already has an active contract rule. {ARCHIVE_FIRST}",
    "unique_active_default_contract_penalty_rule": f"There is already an active default contract rule. {ARCHIVE_FIRST}",
}
GENERIC_CONSTRAINT_MESSAGE = "This would clash with another active record or break a rule for this table."

_RAW = re.compile(r"^Constraint [“\"](?P<name>[^”\"]+)[”\"] is violated\.$")


def plain_constraint_message(message):
    """Django's 'Constraint "name" is violated.' -> the plain sentence; anything else unchanged."""
    match = _RAW.match(str(message))
    if not match:
        return str(message)
    return CONSTRAINT_MESSAGES.get(match.group("name"), GENERIC_CONSTRAINT_MESSAGE)


class PlainConstraintMessagesForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Run 3 fix batch 6: the mileage-band help text is generated from the one band
        # definition (apps.policy.mileage), never typed, so it always shows today's ranges.
        if "mileage_band" in self.fields:
            self.fields["mileage_band"].help_text = f"Bands: {mileage.bands_help_text()}"
        for band, field in mileage.CAP_FIELDS.items():
            if field in self.fields:
                current = mileage.band_definition(band).label
                self.fields[field].help_text = (
                    f"{self.fields[field].help_text} Today: {current}. Bands: {mileage.bands_help_text()}"
                )

    def _post_clean(self):
        super()._post_clean()
        for field, errors in list(self._errors.items()):
            plain, seen = [], set()
            for message in errors:
                text = plain_constraint_message(message)
                if text not in seen:
                    seen.add(text)
                    plain.append(text)
            if plain != [str(m) for m in errors]:
                self._errors[field] = self.error_class(plain, renderer=self.renderer)


def shortest_longer_than_longest_error(cleaned):
    """For the subscription policy form's clean(): the one plain sentence, or None."""
    shortest, longest = cleaned.get("min_tenure_months"), cleaned.get("max_tenure_months")
    if shortest is not None and longest is not None and shortest > longest:
        return ValidationError({NON_FIELD_ERRORS: [SHORTEST_LONGER_THAN_LONGEST]})
    return None
