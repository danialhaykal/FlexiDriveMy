"""Run 1 fix batch 2 (G6): the server builds every new saved scenario.

The browser used to send the figures it had on screen and the server stored
them as-is, so a forged "HP = RM 1.00" came back under a "Saved snapshot"
banner. Now the browser sends only the INPUTS (tenure, mileage band,
downpayment, whether the TCO tab was open, the AI Recommendation request) and
this module recomputes everything with the SAME service functions and response
serializers the live endpoints use - so a saved figure is byte-for-byte what
the screen showed for those inputs, and nothing a client sends can change one.
"""

import json

from rest_framework.renderers import JSONRenderer

from apps.comparisons.serializers import ComparisonResultSerializer
from apps.comparisons.services import ComparisonConfigError, build_comparison
from apps.depreciation.serializers import TCOResultSerializer
from apps.depreciation.services import OperatingCostConfigError, build_tco_report
from apps.profiles.models import declared_mileage_band_for, ncd_percent_for, prefers_islamic_financing
from apps.scoring.serializers import SuitabilityScoringResultSerializer
from apps.scoring.services import build_suitability_scoring

SNAPSHOT_VERSION = 2


def _as_sent(serializer_data):
    """Exactly the JSON the live endpoint puts on the wire (DRF's own
    renderer), so the stored snapshot and the live response compare equal."""
    return json.loads(JSONRenderer().render(serializer_data))


def _inputs_record(inputs, ncd_percent):
    """The validated inputs, JSON-safe (Decimals as their 2 dp strings), plus
    the No-Claim Discount read from the profile at save time."""
    scoring = inputs.get("scoring")
    return {
        "tenure_months": inputs["tenure_months"],
        "mileage_band": inputs["mileage_band"],
        "downpayment": str(inputs["downpayment"]),
        "include_tco": inputs["include_tco"],
        "ncd_percent": str(ncd_percent),
        "scoring": None if scoring is None else {
            "upfront_cash_preservation": scoring["upfront_cash_preservation"],
            "maintenance_protection": scoring["maintenance_protection"],
            "ownership_equity": scoring["ownership_equity"],
            "monthly_income": str(scoring["monthly_income"]),
            "max_dsr_percent": str(scoring["max_dsr_percent"]),
        },
    }


def build_scenario_snapshot(*, user, vehicle, inputs):
    """The payload dict for a new saved scenario, from validated `inputs`
    ({tenure_months, mileage_band, downpayment, include_tco, scoring}).

    Same keys and casing as the snapshots the browser used to build, so the
    saved page renders old and new rows alike; plus snapshotVersion, builtBy
    and the inputs themselves. Never raises for missing pricing config: a
    comparison reports unavailable pathways itself, and a TCO that can't be
    built is stored as null with the buyer's reason beside it.
    """
    # The NCD comes from the user's own profile at save time (like the
    # Islamic-wording flag), never from the request - and is recorded in inputs.
    ncd_percent = ncd_percent_for(user)
    common = {
        "vehicle": vehicle,
        "tenure_months": inputs["tenure_months"],
        "mileage_band": inputs["mileage_band"],
        "downpayment": inputs["downpayment"],
        "ncd_percent": ncd_percent,
    }

    comparison = _as_sent(ComparisonResultSerializer(build_comparison(**common)).data)

    tco = None
    tco_unavailable_reason = None
    if inputs["include_tco"]:
        try:
            report = build_tco_report(**common, declared_mileage_band=declared_mileage_band_for(user))
        except (ComparisonConfigError, OperatingCostConfigError) as exc:
            tco_unavailable_reason = str(exc)  # the buyer wording, as the live TCO 400 shows it
        else:
            tco = _as_sent(TCOResultSerializer(report).data)

    scoring = None
    scoring_inputs = inputs.get("scoring")
    if scoring_inputs is not None:
        result = build_suitability_scoring(
            **common,
            priority_ratings={
                "upfront_cash_preservation": scoring_inputs["upfront_cash_preservation"],
                "maintenance_protection": scoring_inputs["maintenance_protection"],
                "ownership_equity": scoring_inputs["ownership_equity"],
            },
            monthly_income=scoring_inputs["monthly_income"],
            max_dsr_percent=scoring_inputs["max_dsr_percent"],
        )
        scoring = _as_sent(SuitabilityScoringResultSerializer(result).data)

    payload = {
        "snapshotVersion": SNAPSHOT_VERSION,
        "builtBy": "server",
        "tenureMonths": inputs["tenure_months"],
        "mileageBand": inputs["mileage_band"],
        "downpayment": str(inputs["downpayment"]),
        "comparison": comparison,
        "tco": tco,
        "scoring": scoring,
        "inputs": _inputs_record(inputs, ncd_percent),
    }
    if tco_unavailable_reason is not None:
        payload["tcoUnavailableReason"] = tco_unavailable_reason
    if prefers_islamic_financing(user):
        payload["prefersIslamicFinancing"] = True
    return payload
