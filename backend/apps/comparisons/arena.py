"""F005+F006 - multi-vehicle "Arena" comparison (Sprint 10). Pure
orchestration: runs the already-tested build_comparison() and
build_tco_report() once per vehicle and assembles the results side by
side, plus a thin layer of derived winner badges computed by min() over
numbers that are already correct and already tested. No new financial
formula, no new ML feature, no new data source - if the underlying math
were wrong, F005/F006's own test suites would already have caught it.

Lives in its own module, not apps/comparisons/services.py: this module
imports apps.depreciation.services (build_tco_report), but
apps.depreciation.services already imports FROM
apps.comparisons.services (get_active_interest_rate,
apps.comparisons.formulas.calculate_hp_monthly). Importing
apps.depreciation.services into apps.comparisons.services itself would
create a circular import - comparisons.services -> depreciation.services
-> comparisons.services. This module sits above both instead:
arena -> comparisons.services, arena -> depreciation.services, and
neither of those two imports arena or each other in a cycle.
"""

from decimal import Decimal

from apps.common.constants import minimum_downpayment_message
from apps.depreciation.services import OperatingCostConfigError, build_tco_report

from .services import ComparisonConfigError, build_comparison

ARENA_DOWNPAYMENT_MESSAGE = "Downpayment must be less than the vehicle's price."

# Run 3 fix batch 4 (F-21): the Status row's wording, built here and shown as-is.
STATUS_AVAILABLE = "Available"
STATUS_NOT_AT_THIS_DOWNPAYMENT = "Not available at this downpayment"
STATUS_NOT_AVAILABLE = "Not available"
PATHWAYS = ("hire_purchase", "gfv_leasing", "subscription")


def _empty_entry(vehicle_id, error):
    return {
        "vehicle_id": vehicle_id,
        "ok": False,
        "error": error,
        "comparison": None,
        "tco_net": None,
        "model_degraded": None,
        "forecast_source": None,
        "tco_unavailable_reason": None,
        "status_label": None,
    }


def _status_label(comparison, vehicle):
    """'Available' when at least one pathway is offered; otherwise say why in
    plain words - 'at this downpayment' only when the shared downpayment is the
    reason (below this car's 10% minimum), so the wording is never wrong."""
    if any(comparison[pathway] is not None for pathway in PATHWAYS):
        return STATUS_AVAILABLE
    if comparison["unavailable"].get("hire_purchase") == minimum_downpayment_message(vehicle.msrp):
        return STATUS_NOT_AT_THIS_DOWNPAYMENT
    return STATUS_NOT_AVAILABLE


def build_arena(*, vehicles, tenure_months, mileage_band, downpayment, ncd_percent=Decimal("0")):
    """Runs build_comparison() and build_tco_report() once per vehicle.
    A config problem for ONE vehicle (this shared downpayment being >=
    that vehicle's own MSRP) does not fail the whole arena - it's
    recorded as that vehicle's own error entry, same graceful-degradation
    philosophy as ComparisonConfigError/OperatingCostConfigError
    elsewhere in this codebase. A below-minimum-downpayment or missing
    interest-rate/residual-ratio/subscription-plan gap is handled one
    level down, inside build_comparison() itself (it never raises - see
    that function's own docstring), so it shows up as that specific
    pathway being null within an otherwise "ok": True entry, not a
    whole-vehicle failure.

    build_tco_report() has its own independent config dependencies
    (interest rate, operating cost band) and can still raise even when
    build_comparison() fully succeeds - that must not throw away a
    comparison that was already computed, so a TCO-specific failure
    keeps the vehicle "ok": True with its real comparison, just
    tco_net: None and tco_unavailable_reason set.

    Returns a list of per-vehicle dicts, each either {"vehicle_id",
    "ok": True, "comparison": {...}, "tco_net", "model_degraded",
    "tco_unavailable_reason"} or {"vehicle_id", "ok": False,
    "error": "..."} (with comparison/tco_net/model_degraded/
    tco_unavailable_reason set to None on the error entry, so every
    entry has the same keys regardless of outcome).

    Only the compact TCO summary (tco_net + model_degraded) is included
    per vehicle, not the full 61-month monthly_forecast/SHAP breakdown -
    those already exist in the single-vehicle TCO tab; keeping them out
    here is what keeps the response size sane for 3 vehicles at once.
    """
    results = []

    for vehicle in vehicles:
        # build_comparison() doesn't validate this itself (the
        # single-vehicle ComparisonRequestSerializer does, for the
        # one-vehicle case) - the arena needs its own explicit per-vehicle
        # check before calling it, since a shared downpayment that's fine
        # for one vehicle can exceed a cheaper one's own MSRP entirely
        # (not just fall short of its 10% minimum, which build_comparison
        # already handles gracefully on its own).
        if downpayment >= vehicle.msrp:
            results.append(_empty_entry(vehicle.id, ARENA_DOWNPAYMENT_MESSAGE))
            continue

        comparison = build_comparison(
            vehicle=vehicle,
            tenure_months=tenure_months,
            mileage_band=mileage_band,
            downpayment=downpayment,
            ncd_percent=ncd_percent,
        )
        status_label = _status_label(comparison, vehicle)

        # Run 3 fix batch 4 (F-21): the TCO row is the Hire Purchase TCO, so a
        # car whose Hire Purchase is not offered (e.g. the shared downpayment
        # is below its 10% minimum) has no TCO to show - it carries the
        # comparison's own reason and sits out of the lowest-TCO race. Before,
        # build_tco_report priced HP anyway (RM 1,128,685.40 for a 911 at
        # RM 100,000 down) and that figure decided the 'Best' badge.
        if comparison["hire_purchase"] is None:
            results.append(
                {
                    "vehicle_id": vehicle.id,
                    "ok": True,
                    "error": None,
                    "comparison": comparison,
                    "tco_net": None,
                    "model_degraded": None,
                    "forecast_source": None,
                    "tco_unavailable_reason": comparison["unavailable"]["hire_purchase"],
                    "status_label": status_label,
                }
            )
            continue

        try:
            tco = build_tco_report(
                vehicle=vehicle,
                tenure_months=tenure_months,
                mileage_band=mileage_band,
                downpayment=downpayment,
                ncd_percent=ncd_percent,
            )
        except (ComparisonConfigError, OperatingCostConfigError) as exc:
            results.append(
                {
                    "vehicle_id": vehicle.id,
                    "ok": True,
                    "error": None,
                    "comparison": comparison,
                    "tco_net": None,
                    "model_degraded": None,
                    "forecast_source": None,
                    "tco_unavailable_reason": str(exc),
                    "status_label": status_label,
                }
            )
            continue

        results.append(
            {
                "vehicle_id": vehicle.id,
                "ok": True,
                "error": None,
                "comparison": comparison,
                "tco_net": tco["tco_net"],
                "model_degraded": tco["model_degraded"],
                # Run 2 fix batch 3: why the curve is an estimate, when it is (the race
                # below still keys on model_degraded, unchanged).
                "forecast_source": tco["forecast_source"],
                "tco_unavailable_reason": None,
                "status_label": status_label,
            }
        )

    return results


def _cheapest_by(ok_results, value_fn):
    """min() over (vehicle_id, value) pairs, skipping any result where
    value_fn returns None (e.g. a degraded vehicle excluded from the TCO
    race). None if fewer than 2 candidates remain - a "winner" needs
    something to win against.

    QA audit L10: a tie at the winning minimum previously picked
    whichever vehicle happened to come first (min()'s own tie-breaking
    behavior on equal keys), with no indication to the user it was a
    tie at all - two vehicles priced identically would show only one
    "Best" badge, implying a clear win that didn't happen. Returns
    {"winner_id", "tied_with"} instead - tied_with lists EVERY vehicle_id
    at the minimum (including winner_id itself), so a caller can badge
    all of them by checking membership rather than equality.
    """
    candidates = []
    for result in ok_results:
        value = value_fn(result)
        if value is not None:
            candidates.append((result["vehicle_id"], value))

    if len(candidates) < 2:
        return None

    minimum_value = min(value for _, value in candidates)
    tied_with = [vehicle_id for vehicle_id, value in candidates if value == minimum_value]
    return {"winner_id": tied_with[0], "tied_with": tied_with}


def _pathway_monthly_instalment(result, pathway):
    """None when that pathway itself is unavailable for this vehicle (a
    per-vehicle config gap, e.g. no residual ratio for this tenure/
    mileage band - see apps.comparisons.services.build_comparison's
    `unavailable` map) - not just when the whole vehicle failed. Lets
    _cheapest_by correctly exclude only that specific pathway's race for
    this vehicle, the same "excluded from this specific race, still shown
    elsewhere" pattern already used for a degraded vehicle's lowest_tco."""
    pathway_data = result["comparison"][pathway]
    return pathway_data["monthly_instalment"] if pathway_data is not None else None


def compute_arena_winners(results):
    """Returns {"cheapest_hp": {"winner_id", "tied_with"}, "cheapest_gfv":
    {...}, "cheapest_subscription": {...}, "lowest_tco": {...}} - each
    None if fewer than 2 vehicles succeeded (a "winner" needs something to
    win against) or if every candidate is missing that particular figure
    (e.g. every vehicle in the arena is model_degraded, so there's no
    non-degraded TCO to compare - degraded vehicles are still shown in
    `results` with their own model_degraded flag visible, just excluded
    from the lowest_tco race here rather than silently picked as a winner;
    same reasoning for a vehicle whose own gfv_leasing/hire_purchase/
    subscription pathway is unavailable - excluded from that pathway's
    race only, still shown with its other pathways intact).
    """
    ok_results = [result for result in results if result["ok"]]

    return {
        "cheapest_hp": _cheapest_by(ok_results, lambda r: _pathway_monthly_instalment(r, "hire_purchase")),
        "cheapest_gfv": _cheapest_by(ok_results, lambda r: _pathway_monthly_instalment(r, "gfv_leasing")),
        "cheapest_subscription": _cheapest_by(
            ok_results, lambda r: _pathway_monthly_instalment(r, "subscription")
        ),
        "lowest_tco": _cheapest_by(
            ok_results, lambda r: r["tco_net"] if not r["model_degraded"] else None
        ),
    }
