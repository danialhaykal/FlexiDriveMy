"""Run 3 fix batch 5 (F-26): the texts the ML Model Management page shows for a
training run - the rejection reason, the known-issue note and the retirement
reason - in plain words, with no developer text: no batch codes ("ML batch 1"),
no internal names (`msrp_proxy`, "leave-one-out") and no raw model keys
("gradient_boosting" -> "Gradient Boosting").

New runs are written this way by the code (apps/ml/training.py,
retire_incompatible_production_model, data_fixes); runs stored before are
reworded by the audited command clean_ml_run_texts, which uses plain_run_text.
"""

import re

from .data_fixes import KNOWN_ISSUE_NOTE_LEAKY_MSRP_PROXY_RUN as LEAKY_RUN_NOTE
from .models import ModelType

# The wording now written for the cases stored with internal names.
RAW_PRICE_RETIRED_REASON = (
    "Retired: it predicts raw prices from a used-price stand-in for the new price; replaced by the resale-price model."
)
RATIO_RETIRED_REASON = (
    "Retired: it predicts value-retention ratios from a used-price stand-in for the new price; replaced by the "
    "resale-price model."
)
UNKNOWN_TARGET_RETIRED_REASON = "Retired: its prediction target is not recorded; replaced by the resale-price model."

# Exact earlier texts -> their plain versions (the earlier wording is known word for word).
_REWORDED = {
    (
        "This run's msrp_proxy feature was computed without leave-one-out exclusion, allowing rows' own resale price "
        "to leak into their own prediction feature and inflating R². The bug was fixed before the next run; this "
        "run's R² should not be cited as a valid result."
    ): LEAKY_RUN_NOTE,
    "Retired: it predicts raw prices from msrp_proxy; replaced by the resale-price model (ML batch 1).":
        RAW_PRICE_RETIRED_REASON,
    (
        "Retired: it predicts value-retention ratios from msrp_proxy; replaced by the resale-price model "
        "(ML batch 1)."
    ): RATIO_RETIRED_REASON,
    "Retired: its prediction target is not recorded; replaced by the resale-price model (ML batch 1).":
        UNKNOWN_TARGET_RETIRED_REASON,
}
_MODEL_KEY = re.compile(r"\b(" + "|".join(re.escape(value) for value in ModelType.values) + r")\b")
_BATCH_NOTE = re.compile(r"\s*\((?:ML|Run \d+ fix|audit) batch \d+[^)]*\)", re.IGNORECASE)


def model_type_label(model_type):
    """'gradient_boosting' -> 'Gradient Boosting'; an unknown key is returned as it is."""
    try:
        return ModelType(model_type).label
    except ValueError:
        return model_type


def plain_run_text(text):
    """`text` with developer wording replaced; unchanged when there is none.
    Idempotent: running it on its own output changes nothing."""
    if not text:
        return text
    text = _REWORDED.get(text, text)
    text = _MODEL_KEY.sub(lambda match: model_type_label(match.group(1)), text)
    return _BATCH_NOTE.sub("", text)


DEVELOPER_TEXT = re.compile(
    r"(?i)\bbatch \d|msrp_proxy|leave-one-out|\bsprint\b|CLAUDE|\bUC0\d\d\b|\bF0\d\d\b|QA audit|"
    + "|".join(re.escape(value) for value in ModelType.values)
)
