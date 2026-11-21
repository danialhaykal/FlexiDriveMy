"""F007 - orchestrates F005's HP/GFV/Subscription comparison into the MCDA
suitability scoring result (UC007)."""

from decimal import ROUND_HALF_UP, Decimal

from apps.comparisons.services import build_comparison

from . import formulas


def build_suitability_scoring(
    *,
    vehicle,
    tenure_months,
    mileage_band,
    downpayment,
    priority_ratings,
    monthly_income,
    max_dsr_percent,
    ncd_percent=Decimal("0"),
):
    """UC007 step 3: "scores each available pathway" - a pathway missing
    its own F010/F011 config (or, per Sprint-13-QA's C5/C6 fixes, a
    below-minimum downpayment or a GFV that would go negative) is listed
    in `unavailable` with its reason, exactly as build_comparison()
    already reports it; the remaining pathways are still scored and
    ranked. Never raises ComparisonConfigError - a vehicle with every
    pathway unavailable still returns 200 with an empty ranking and
    recommended_pathway=None, same "always 200 once the request is
    valid" contract as F005's own endpoint.

    `ncd_percent` (the buyer's No-Claim Discount, from their profile) is only
    passed on to build_comparison so its comparison matches the screen's;
    scores read instalments and upfront cash, which no NCD changes.
    """
    comparison = build_comparison(
        vehicle=vehicle, tenure_months=tenure_months, mileage_band=mileage_band, downpayment=downpayment,
        ncd_percent=ncd_percent,
    )
    weights = formulas.normalize_priority_weights(**priority_ratings)

    available_pathways = [pathway for pathway in formulas.PATHWAYS if comparison[pathway] is not None]

    upfront_cash_by_pathway = {
        pathway: comparison[pathway]["upfront_cash"] for pathway in available_pathways
    }
    monthly_by_pathway = {
        pathway: comparison[pathway]["monthly_instalment"] for pathway in available_pathways
    }

    max_dsr = max_dsr_percent / Decimal(100)
    dsr_by_pathway = {
        pathway: monthly / monthly_income for pathway, monthly in monthly_by_pathway.items()
    }

    # formulas.score_upfront_cash_preservation's min-max normalisation and
    # calculate_pathway_scores's DSR force-to-0 rule both already operate
    # generically over however many pathways are in these dicts - a
    # single remaining pathway hits that function's own existing
    # all-tied branch (ties score 1.0, nothing to compare against), not a
    # new code path added here.
    scores = (
        formulas.calculate_pathway_scores(
            upfront_cash_by_pathway=upfront_cash_by_pathway,
            weights=weights,
            dsr_by_pathway=dsr_by_pathway,
            max_dsr=max_dsr,
            # QA audit M4: the vehicle's own price is the scoring anchor
            # now, not a min-max spread across pathways - see
            # formulas.score_upfront_cash_preservation's own docstring.
            price=vehicle.msrp,
        )
        if available_pathways
        else {}
    )

    ranking = sorted(scores, key=lambda pathway: scores[pathway]["final_score"], reverse=True)
    all_exceed_dsr = bool(scores) and all(scores[pathway]["exceeds_dsr"] for pathway in scores)
    recommended_pathway = ranking[0] if scores and not all_exceed_dsr else None
    if recommended_pathway:
        gfv = comparison["gfv_leasing"]
        rationale = formulas.build_rationale(
            recommended_pathway, weights, scores,
            gfv_balloon=gfv["balloon_payment"] if gfv is not None else None,
            tenure_months=tenure_months,
        )
    elif not scores:
        rationale = "No pathways are available to score for this vehicle, tenure and mileage band."
    else:
        rationale = "None of the available pathways fit within your declared DSR limit."

    return {
        "vehicle_id": vehicle.id,
        "weights": weights,
        "monthly_income": monthly_income,
        "max_dsr_percent": max_dsr_percent,
        "pathways": {
            pathway: {
                "monthly_instalment": monthly_by_pathway[pathway],
                "upfront_cash": upfront_cash_by_pathway[pathway],
                # QA audit L6: explicit ROUND_HALF_UP, not Python's
                # default banker's rounding.
                "dsr_percent": (dsr_by_pathway[pathway] * Decimal(100)).quantize(
                    formulas.TWO_PLACES, rounding=ROUND_HALF_UP
                ),
                "exceeds_dsr": scores[pathway]["exceeds_dsr"],
                # Run 3 fix batch 5 (F-23): words when the 2-dp figure hides why it is over.
                "dsr_note": formulas.dsr_just_over_note(dsr_by_pathway[pathway], max_dsr_percent),
                "suitability_score": scores[pathway]["suitability_percent"],
            }
            for pathway in scores
        },
        "ranking": ranking,
        "recommended_pathway": recommended_pathway,
        "unavailable": comparison["unavailable"],
        "rationale": rationale,
    }


def build_dsr_simulation(
    *,
    vehicle,
    tenure_months,
    mileage_band,
    downpayment,
    monthly_income,
    existing_monthly_commitments,
    max_dsr_percent,
    ncd_percent=Decimal("0"),
):
    """Sprint 11 - standalone Affordability / DSR Simulator. Reuses
    build_comparison() for the three pathways' real monthly instalments -
    no new financing math. Simulates only the pathways build_comparison()
    actually returned (same "score/report only what's available"
    contract as build_suitability_scoring above, per the Sprint-13 QA
    fix) - an unavailable pathway is listed in `unavailable` with its
    reason instead, never raised as a whole-request failure.

    A separate calculation from build_suitability_scoring's own DSR check
    above (untouched by this sprint): this one folds in whatever other
    debt the user has already declared via existing_monthly_commitments,
    and compares the raw (unrounded) ratio against max_dsr for exceeds_dsr
    - the same way calculate_pathway_scores compares dsr_by_pathway
    against max_dsr - so that with existing_monthly_commitments=0 this
    produces identical dsr_percent/exceeds_dsr to F007's own endpoint for
    whichever pathways both endpoints have available.
    """
    comparison = build_comparison(
        vehicle=vehicle, tenure_months=tenure_months, mileage_band=mileage_band, downpayment=downpayment,
        ncd_percent=ncd_percent,
    )
    max_dsr = max_dsr_percent / Decimal(100)

    pathways = {}
    for pathway in formulas.PATHWAYS:
        if comparison[pathway] is None:
            continue
        monthly_instalment = comparison[pathway]["monthly_instalment"]
        total_dsr_ratio = (existing_monthly_commitments + monthly_instalment) / monthly_income
        pathways[pathway] = {
            "monthly_instalment": monthly_instalment,
            "existing_monthly_commitments": existing_monthly_commitments,
            "dsr_percent": formulas.calculate_total_dsr_percent(
                monthly_instalment=monthly_instalment,
                existing_monthly_commitments=existing_monthly_commitments,
                monthly_income=monthly_income,
            ),
            "exceeds_dsr": total_dsr_ratio > max_dsr,
            "dsr_note": formulas.dsr_just_over_note(total_dsr_ratio, max_dsr_percent),
            "is_ccris_reportable": formulas.CCRIS_REPORTABLE_PATHWAYS[pathway],
        }

    return {
        "vehicle_id": vehicle.id,
        "monthly_income": monthly_income,
        "max_dsr_percent": max_dsr_percent,
        "pathways": pathways,
        "unavailable": comparison["unavailable"],
    }
