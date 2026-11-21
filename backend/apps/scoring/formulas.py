"""F007 - pure MCDA scoring functions (UC007), framework-free like
apps/comparisons/formulas.py and apps/depreciation/formulas.py.

the project spec specifies the aggregation formula exactly:
    Score_i = Sum(w_j * s_ij) across j in {upfront cash preservation,
              maintenance protection, ownership equity}
    w_j = user's normalized priority weights (Sum w_j = 1)
    Hard constraint: if a pathway's M_payment exceeds the user's max
    declared DSR threshold, force Score_i = 0 regardless of weighted score.

It does NOT specify how each pathway's per-criterion score s_ij is
derived - that's a genuine gap this module fills, flagged here rather than
silently assumed:

- upfront_cash_preservation: continuous, scored against the vehicle's own
  price (1 - upfront_cash / price) - see score_upfront_cash_preservation's
  own docstring for why a min-max normalization across pathways (the
  original approach) doesn't work here (QA audit M4).
- maintenance_protection: categorical - Subscription bundles maintenance
  cost into its fee (the offset in NetCost comes from the single
  operating-cost engine, apps.policy.operating_costs); HP/GFV leave the owner
  to pay it separately (the same engine feeds F006's TCO). Subscription=1.0,
  HP/GFV=0.0.
- ownership_equity: categorical - HP gives full ownership (1.0), GFV gives
  conditional/partial ownership via the balloon option (0.5), Subscription
  gives none (0.0) - consistent with the project spec's own TCO note that
  V_residual applies to "HP/GFV-Retain paths" and is RM0 for Subscription.
"""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")
HUNDRED = Decimal("100")

PATHWAYS = ("hire_purchase", "gfv_leasing", "subscription")

OWNERSHIP_EQUITY_SCORE = {
    "hire_purchase": Decimal("1.0"),
    "gfv_leasing": Decimal("0.5"),
    "subscription": Decimal("0.0"),
}

MAINTENANCE_PROTECTION_SCORE = {
    "hire_purchase": Decimal("0.0"),
    "gfv_leasing": Decimal("0.0"),
    "subscription": Decimal("1.0"),
}

PATHWAY_LABELS = {
    "hire_purchase": "Hire Purchase",
    "gfv_leasing": "GFV Leasing",
    "subscription": "Subscription",
}

CRITERION_LABELS = {
    "upfront_cash_preservation": "preserving upfront cash",
    "maintenance_protection": "maintenance cost protection",
    "ownership_equity": "building ownership equity",
}

INCOMPLETE_QUIZ_MESSAGE = "Please rate all three priorities to receive a recommendation."


def normalize_priority_weights(
    *, upfront_cash_preservation, maintenance_protection, ownership_equity
):
    """UC007 step 3: normalize raw priority ratings so w_j sums to 1.

    Ratings arrive as plain ints from the request serializer's
    IntegerField - coerced to Decimal here so the division below can't
    silently produce float results (int/int or int/Decimal division in
    Python yields float, not Decimal).
    """
    upfront_cash_preservation = Decimal(upfront_cash_preservation)
    maintenance_protection = Decimal(maintenance_protection)
    ownership_equity = Decimal(ownership_equity)
    total = upfront_cash_preservation + maintenance_protection + ownership_equity
    if total <= 0:
        raise ValueError("At least one priority rating must be greater than zero.")
    return {
        "upfront_cash_preservation": upfront_cash_preservation / total,
        "maintenance_protection": maintenance_protection / total,
        "ownership_equity": ownership_equity / total,
    }


def score_upfront_cash_preservation(upfront_cash_by_pathway, price):
    """QA audit M4: the original approach (min-max normalized across only
    the pathways in THIS comparison) is scale-invariant by construction
    and never actually responds to the real amount of cash committed.
    HP's and GFV's upfront_cash are always identical to each other (both
    are just `downpayment`), and Subscription's is always 0 - so
    spread = downpayment - 0 = downpayment, and HP's score is always
    exactly (downpayment - 0) / downpayment = 1, regardless of whether
    downpayment is RM 1 or RM 200,000.

    Deliberate modelling choice (the project spec doesn't specify this scoring
    internals exactly - see this module's own docstring): score against
    the vehicle's own price instead, which isn't itself proportional to
    the downpayment on every pathway: 1 - (upfront_cash / price).
    Subscription still scores a perfect 1.0 (zero upfront cash), but
    HP/GFV's own score now genuinely falls as the downpayment grows
    relative to the car's price - the actual real-world tradeoff this
    criterion is supposed to capture.
    """
    return {
        pathway: Decimal("1.0") - (upfront_cash / price)
        for pathway, upfront_cash in upfront_cash_by_pathway.items()
    }


def calculate_pathway_scores(*, upfront_cash_by_pathway, weights, dsr_by_pathway, max_dsr, price):
    """the project spec: Score_i = Sum(w_j * s_ij), with the hard DSR override
    (UC007 Rule 1): force Score_i = 0 if the pathway's DSR exceeds
    max_dsr, regardless of the weighted score - this overrides everything
    else, so it's applied *after* the weighted sum, unconditionally.
    """
    cash_scores = score_upfront_cash_preservation(upfront_cash_by_pathway, price)

    results = {}
    for pathway in upfront_cash_by_pathway:
        weighted_score = (
            weights["upfront_cash_preservation"] * cash_scores[pathway]
            + weights["maintenance_protection"] * MAINTENANCE_PROTECTION_SCORE[pathway]
            + weights["ownership_equity"] * OWNERSHIP_EQUITY_SCORE[pathway]
        )
        exceeds_dsr = dsr_by_pathway[pathway] > max_dsr
        final_score = Decimal("0") if exceeds_dsr else weighted_score
        results[pathway] = {
            "raw_score": weighted_score,
            "final_score": final_score,
            "exceeds_dsr": exceeds_dsr,
            # QA audit L6: explicit ROUND_HALF_UP - a bare .quantize() uses
            # Python's default banker's rounding (ROUND_HALF_EVEN), which
            # is inconsistent with every other currency/percentage figure
            # in this codebase.
            "suitability_percent": (final_score * HUNDRED).quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
        }
    return results


def gfv_end_of_term_note(balloon_payment, tenure_months):
    """Run 1 fix batch 4 (B4): what a GFV recommendation must also say - the
    balloon is real money at the end, or the car goes back. Built from the
    comparison's own balloon figure, never recomputed."""
    return f"This includes a balloon payment of RM {balloon_payment:,.2f} at month {tenure_months}, or you can return the car."


def _priority_reason(weights):
    """Run 3 fix batch 5 (F-24): the rationale's closing words. With one top
    priority it names it; when two share the highest rating it names both; when
    all three are equal it says so - it never claims the buyer put extra weight on
    whichever criterion happens to come first."""
    top = max(weights.values())
    tied = [criterion for criterion in CRITERION_LABELS if weights[criterion] == top]
    if len(tied) == len(CRITERION_LABELS):
        return "reflecting that you rated your priorities equally"
    if len(tied) == 2:
        return f"reflecting the equal weight you placed on {CRITERION_LABELS[tied[0]]} and {CRITERION_LABELS[tied[1]]}"
    return f"reflecting the weight you placed on {CRITERION_LABELS[tied[0]]}"


def build_rationale(recommended_pathway, weights, scores, *, gfv_balloon=None, tenure_months=None):
    pct = scores[recommended_pathway]["suitability_percent"]
    rationale = (
        f"{PATHWAY_LABELS[recommended_pathway]} best matches your priorities, scoring {pct}% "
        f"suitability - {_priority_reason(weights)}."
    )
    if recommended_pathway == "gfv_leasing" and gfv_balloon is not None:
        rationale += " " + gfv_end_of_term_note(gfv_balloon, tenure_months)
    return rationale


# --- Sprint 11: Affordability / DSR Simulator (standalone tool) -------------
#
# Separate from calculate_pathway_scores's own DSR check above, which stays
# exactly as the project spec/UC007 specify it (untouched by this sprint): that
# check only divides the new pathway's own instalment by income, which is
# correct for UC007's narrow purpose (a relative comparison between three
# pathways for the same person) but understates real underwriting DSR,
# which counts a person's total existing debt load too. This section adds
# a more complete, opt-in calculation for a standalone tool - it does not
# retrofit F007.

# Which pathways are real credit agreements reported to Bank Negara
# Malaysia's CCRIS ledger, vs. a service contract with no credit facility
# behind it. This is a structural fact about the contract type (HP and
# GFV Leasing are both hire-purchase-style credit agreements; Subscription
# is a rental/service contract) - a static label, not a computed number,
# and not itself a claim about any specific bank's policy.
CCRIS_REPORTABLE_PATHWAYS = {
    "hire_purchase": True,
    "gfv_leasing": True,
    "subscription": False,
}


def dsr_just_over_note(dsr_ratio, max_dsr_percent):
    """Run 3 fix batch 5 (F-23): words for a DSR that is over the limit but shows
    as the limit (or below it) at 2 dp - e.g. 50.00003% on a 50% limit reads
    "50.00%" next to "Exceeds DSR". Returns "Just over your 50% limit (50.00003%)."
    with as few extra decimals as show the difference (cut, never rounded up),
    or just "Just over your 50% limit." if 8 places still do not show it; None
    when the 2-dp figure already reads as over, or when it is not over at all.
    Display only: dsr_percent and exceeds_dsr are unchanged."""
    percent = dsr_ratio * HUNDRED
    if percent <= max_dsr_percent or percent.quantize(TWO_PLACES, rounding=ROUND_HALF_UP) > max_dsr_percent:
        return None
    limit = f"{Decimal(max_dsr_percent).normalize():f}"
    for places in range(3, 9):
        shown = percent.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)
        if shown > max_dsr_percent:
            return f"Just over your {limit}% limit ({shown}%)."
    return f"Just over your {limit}% limit."


def calculate_total_dsr_percent(*, monthly_instalment, existing_monthly_commitments, monthly_income):
    """(existing_monthly_commitments + monthly_instalment) / monthly_income, as a
    percent (2dp). Deliberately separate from calculate_pathway_scores's own
    DSR check above (which stays exactly as the project spec/UC007 specify it,
    untouched by this sprint) - this is a more complete affordability figure
    for the standalone DSR Simulator tool, including whatever other debt the
    user has already declared, not just the pathway being newly considered.

    Uses the same quantize(TWO_PLACES) call (default rounding, no explicit
    ROUND_HALF_UP) as build_suitability_scoring's own dsr_percent - when
    existing_monthly_commitments is 0 this must reproduce F007's own
    dsr_percent bit-for-bit, since "total DSR" and "this pathway's own DSR"
    are then the same number.
    """
    total_dsr = (existing_monthly_commitments + monthly_instalment) / monthly_income
    # QA audit L6: explicit ROUND_HALF_UP - see calculate_pathway_scores's
    # own quantize call above for why.
    return (total_dsr * HUNDRED).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
