"""Ringgit amounts typed into a contract rule's wear-and-tear text (run 1,
finding B7).

The app works out every fee from the rule's numbers (early_termination_months
x the subscription fee of the request on screen), so a fee amount typed into
the free text goes stale the moment a price changes - and then contradicts the
screen ("the fee shown is 6 x RM7,355.00" while the card shows another
figure). This module finds such amounts so refresh_contract_rule_texts can
remove them, and so the model / serializer / Django admin refuse new ones.

What counts as a stale fee amount: a clause (a sentence, or a part of one after
"; " or ", and ") that contains a ringgit amount ("RM5,000", "MYR 5,000",
"5,000 ringgit") which is NOT a per-km rate AND talks about a fee, a charge or
leaving early (fee, penalty, charge, cost, early, exit, termination, cancel,
return... - see _FEE_WORDS). Per-km mileage rates ("RM0.20-0.50/km", "RM0.50
per km", "RM0.50 (top of range) ... per km") and the mileage/condition wording
around them are kept - they are terms, not a computed fee. A damage term with
none of those words ("Wear beyond normal: RM300 per panel.") is also kept.

Imports no models, so apps.policy.models can use the validator without a cycle.
"""

import re

from django.core.exceptions import ValidationError

RINGGIT_IN_TEXT_MESSAGE = "Do not type ringgit amounts here - the app calculates fees from the rule's numbers."

_NUMBER = r"\d[\d,]*(?:\.\d+)?"
# A ringgit amount: "RM5,000", "MYR 5,000", "MYR5000" (optionally a range,
# "RM0.20-0.50") or "5,000 ringgit".
_AMOUNT = re.compile(
    rf"\b(?:RM|MYR)\s?{_NUMBER}(?:\s*-\s*{_NUMBER})?|\b{_NUMBER}\s*ringgit\b",
    re.IGNORECASE,
)
# Per-km wording: "/km", "per km", "per-km", "per kilometre/kilometer".
_PER_KM = re.compile(r"/\s*km\b|\bper[\s-]*(?:km|kilomet(?:re|er))\b", re.IGNORECASE)
# Words that make a clause about a fee or leaving the contract early (run 1 fix
# batch 2 widened the list: "Penalty of RM5,000 for returning the car" and
# "A charge of RM5,000 applies if you end the contract before term" slipped
# through the first version).
_FEE_WORDS = re.compile(
    r"\b(?:fee|fees|early|termination|terminate|return|returning|returned|penalty|penalties|charge|charges|"
    r"charged|cost|costs|exit|cancel|cancellation)\b",
    re.IGNORECASE,
)
# Sentence ends: ". " (or ! ?) followed by a capital - so "kinto-my.com/faqs"
# and "RM8,747.50" are not split.
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_CLAUSE_SEPARATORS = re.compile(r"(;\s+|,\s+and\s+)")


def _is_per_km_rate(clause, match, next_start):
    """A per-km rate: per-km wording after the amount and before the next
    amount in the same clause - right after it ("RM0.50/km", "RM0.50 per km")
    or later ("RM0.50 (top of range) is charged per km")."""
    return bool(_PER_KM.search(clause, match.end(), next_start))


def is_stale_fee_clause(clause):
    matches = list(_AMOUNT.finditer(clause))
    next_starts = [m.start() for m in matches[1:]] + [len(clause)]
    has_fee_amount = any(
        not _is_per_km_rate(clause, match, next_start) for match, next_start in zip(matches, next_starts)
    )
    return has_fee_amount and bool(_FEE_WORDS.search(clause))


def _clean_sentence(sentence):
    """(sentence with its stale fee clauses removed, whether any were)."""
    parts = _CLAUSE_SEPARATORS.split(sentence)
    clauses, separators = parts[0::2], parts[1::2]
    kept = []
    for index, clause in enumerate(clauses):
        if is_stale_fee_clause(clause):
            continue
        separator = separators[index - 1] if index > 0 and kept else ""
        kept.append(separator + clause)
    if len(kept) == len(clauses):
        return sentence, False
    if not kept:
        return "", True
    text = "".join(kept).rstrip()
    if text[-1] not in ".!?":
        text = text.rstrip(",;:") + "."  # the removed clause carried the full stop
    return text, True


def strip_stale_fee_amounts(text):
    """The text with every stale fee clause removed (everything else, word for
    word); unchanged when there is none. Idempotent: running it on its own
    output changes nothing."""
    sentences = _SENTENCES.split(text.strip())
    cleaned = [_clean_sentence(sentence) for sentence in sentences]
    if not any(removed for _, removed in cleaned):
        return text
    return " ".join(sentence for sentence, _ in cleaned if sentence)


def has_stale_fee_amounts(text):
    return strip_stale_fee_amounts(text) != text


# --- run 2 fix batch 3 (B7): a brand's rule text must not name one model -------------------------------------
#
# A brand's contract rule applies to EVERY car of that brand, so "RM0.50 (top of range) is used here for the
# Alphard" shows Toyota buyers of any other model text about a different car. The wording is reworded to apply
# to the brand's cars; every other fact in the text stays word for word.

ESTIMATE_FOR_BRAND_CARS = "is used here as the estimate for this brand's cars"
_USED_HERE_FOR = re.compile(r"\bis used here for the ([^.;]+)")


def model_name_candidates(vehicles):
    """The strings that name one of a brand's models: each model's name ("ES",
    "Alphard") and its name with the first word of the trim ("ES 250"). `vehicles`
    is an iterable of (name, trim)."""
    names = set()
    for name, trim in vehicles:
        name = (name or "").strip()
        if not name:
            continue
        names.add(name)
        trim_words = (trim or "").split()
        if trim_words:
            names.add(f"{name} {trim_words[0]}")
    return sorted(names)


def model_names_in_text(text, names, *, ignore_case=False):
    """The names from `names` that appear in `text` as whole words (so the model
    "ES" is not found inside "licences" or "yes"). Case-sensitive unless
    `ignore_case` - the write-path guard below ignores case ("alphard" is still
    the Alphard)."""
    flags = re.IGNORECASE if ignore_case else 0
    return [
        name for name in names
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text, flags)
    ]


# Run 3 fix batch 4 (F-16): the write paths (API and Django admin) refuse a brand rule
# text that names one of that brand's models, with the same check as above.
MODEL_NAME_IN_TEXT_MESSAGE = (
    "Do not name a model here - this rule applies to every car of the brand (found: {names})."
)


def model_name_in_text_message(text, names):
    """The refusal message when `text` names one of `names` (any case), else None."""
    found = model_names_in_text(text or "", names, ignore_case=True)
    if not found:
        return None
    return MODEL_NAME_IN_TEXT_MESSAGE.format(names=", ".join(found))


def reword_model_specific_estimate(text, names):
    """'... is used here for the Alphard.' -> '... is used here as the estimate for
    this brand's cars.' when what follows 'for the' names one of the brand's models
    (`names`, from model_name_candidates). Everything else is unchanged; text
    without that phrase, and an already reworded text, come back as they were."""

    def swap(match):
        return ESTIMATE_FOR_BRAND_CARS if model_names_in_text(match.group(1), names) else match.group(0)

    return _USED_HERE_FOR.sub(swap, text)


def validate_no_ringgit_fee_amounts(value):
    """Model field validator (so the Django admin form, the API serializer and
    any bulk path all apply it): refuse a fee amount typed into the text."""
    if value and has_stale_fee_amounts(value):
        raise ValidationError(RINGGIT_IN_TEXT_MESSAGE)
