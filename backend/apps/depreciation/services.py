"""F006 - orchestrates F010/F011 lookups, F005's HP formula, F012's
deployed model (via inference.py), and this app's own TCO/crossover
formulas into one UC006 report."""

from decimal import ROUND_HALF_UP, Decimal

from apps.comparisons import formulas as comparison_formulas
from apps.comparisons.formulas import calculate_gfv_balloon
from apps.comparisons.services import (
    ComparisonConfigError,
    build_comparison,
    get_active_interest_rate,
    gfv_residual_ratio_user_message,
)
from apps.policy.contract_rules import get_contract_rules
from apps.policy import mileage
from apps.policy.residuals import ResidualConfigError, resolve_residual_ratio
# OperatingCostConfigError is re-exported here: the views and Arena import it
# from this module.
from apps.policy.operating_costs import OperatingCostConfigError, estimate_operating_costs  # noqa: F401
from apps.scoring.formulas import (
    MAINTENANCE_PROTECTION_SCORE,
    OWNERSHIP_EQUITY_SCORE,
    PATHWAYS,
    score_upfront_cash_preservation,
)

from . import formulas, resale_notes
from .explanation import round_explanation
from .inference import (
    MILEAGE_CAP_NOTE,
    explain_resale_prediction,
    forecast_source,
    mileage_cap_applies,
    predict_resale_curve,
)

RISK_RADAR_SCORE_PLACES = Decimal("0.0001")

# Sprint 12's Total-Loss Sandbox: which pathways carry a real ownership
# stake (an outstanding balance that can be netted against an insurance
# payout) vs. Subscription's rental/service contract, which has none.
# Same "static, never computed" pattern as
# apps.scoring.formulas.CCRIS_REPORTABLE_PATHWAYS - the semantics differ
# (ownership exposure, not CCRIS reporting) so this is its own sibling
# constant rather than reusing that one.
HAS_OWNERSHIP_EXPOSURE = {
    "hire_purchase": True,
    "gfv_leasing": True,
    "subscription": False,
}

# The representative annual mileage per band (the ML feature) is no longer a
# constant here: Run 3 fix batch 6 moved it to the one band definition,
# apps.policy.mileage.representative_km (midpoint rule on the policy's band limits).


def _build_risk_radar(*, comparison, price):
    """Batch 6C / UC006 step 7's 3-axis risk comparison radar - the same
    three UNWEIGHTED per-pathway scores UC007's suitability scoring
    already computes (apps.scoring.formulas), reused directly rather than
    a new, separately-invented figure. Unweighted: UC006 has no notion of
    a user's own priority ratings, unlike UC007's quiz - weighting by
    priorities the user hasn't declared here would be fabricating input
    that doesn't exist. Only pathways `comparison` actually returned (not
    None) are scored; the rest are named in radar_unavailable instead,
    same graceful-degradation contract as build_comparison itself.
    """
    available_pathways = [pathway for pathway in PATHWAYS if comparison[pathway] is not None]
    upfront_cash_by_pathway = {
        pathway: comparison[pathway]["upfront_cash"] for pathway in available_pathways
    }
    cash_scores = score_upfront_cash_preservation(upfront_cash_by_pathway, price)

    radar = {
        pathway: {
            "upfront_cash_preservation": cash_scores[pathway].quantize(
                RISK_RADAR_SCORE_PLACES, rounding=ROUND_HALF_UP
            ),
            "maintenance_protection": MAINTENANCE_PROTECTION_SCORE[pathway],
            "ownership_equity": OWNERSHIP_EQUITY_SCORE[pathway],
        }
        for pathway in available_pathways
    }
    return radar, comparison["unavailable"]


def _build_risk_alerts(*, crossover_month, mileage_band, declared_mileage_band):
    """Batch 6C / UC006 step 9's risk alerts - built only from data that
    already genuinely exists (the negative-equity crossover this report
    already computes, and the user's own saved UC003 baseline), never a
    new invented "plan mileage cap" field."""
    alerts = []

    if crossover_month is not None:
        # Deliberately duplicates, by design, the chart-level banner
        # NegativeEquityChart.tsx already renders inline on its own chart
        # (left exactly as-is - see that component) - UC006 step 9
        # separately calls for a dedicated "Risk Alerts" surface, not a
        # replacement for the chart's own annotation.
        alerts.append(
            {
                "code": "negative_equity_within_horizon",
                "severity": "warning",
                "message": (
                    f"Predicted resale value falls below the outstanding loan balance starting "
                    f"month {crossover_month} - you would owe more than the car is worth if sold "
                    f"at that point."
                ),
            }
        )

    if declared_mileage_band is not None and declared_mileage_band != mileage_band:
        # Run 3 fix batch 6: the labels (with their km ranges) from the one band definition.
        selected_label = mileage.mileage_band_label(mileage_band)
        declared_label = mileage.mileage_band_label(declared_mileage_band)
        alerts.append(
            {
                "code": "declared_mileage_mismatch",
                "severity": "info",
                "message": (
                    f"This estimate uses the '{selected_label}' mileage band, but your saved "
                    f"profile declares '{declared_label}' as your actual annual mileage. Your "
                    f"real operating costs and excess-mileage exposure may differ from this "
                    f"estimate."
                ),
            }
        )

    return alerts


def build_early_settlement(*, principal, exact_hp_monthly, tenure_months):
    """What it costs to settle the HP loan early, by the reducing-balance
    method the Hire-Purchase (Amendment) Act 2026 requires for new loans:
    the outstanding balance at the effective rate, with NO early-settlement
    penalty (the Rule of 78 is abolished). Two reference points from the
    same settlement_balance the chart and TCO use: after 12 months (null if
    the loan is 12 months or shorter) and at half term (floor(t/2))."""
    half_term_month = tenure_months // 2
    after_12, at_half = comparison_formulas.settlement_balances(
        principal, exact_hp_monthly, tenure_months, [12, half_term_month]
    )
    return {
        "method": "reducing_balance",
        "after_12_months": after_12 if tenure_months > 12 else None,
        "at_half_term": at_half,
        "half_term_month": half_term_month,
        "penalty": "none",
    }


def build_contract_checklist(*, brand, early_settlement, subscription_fee):
    """Batch 6C / UC006 step 8, reworked in audit batch 4 and run 1: the
    brand's own ContractPenaltyRule if it has one, else the single default
    rule (brand = null), so a new brand gets sensible terms with nothing
    keyed. None only if neither exists - this supplementary section must
    never 400 the whole report.

    Two different early exits, never mixed up:
      - Settling the HIRE PURCHASE loan early: `early_settlement` (see
        build_early_settlement) - the reducing-balance amount to settle, no
        penalty.
      - Returning a SUBSCRIPTION car early: the rule's early_termination_months
        is now N months of the subscription fee (KINTO ONE's published rule:
        N months' fee, or the fees left, whichever is lower). The fee is N x
        the Subscription fee of THIS request (`subscription_fee`), null when
        Subscription isn't available for it (e.g. 48 or 60 months).
    A brand rule may leave its months empty, inheriting the default's
    (early_termination_months_source says which). Every ringgit figure is
    computed here, never stored. Wear and tear is checklist text only;
    normal wear is already priced into the resale value.
    """
    brand_rule, default_rule = get_contract_rules(brand)
    rule = brand_rule or default_rule
    if rule is None:
        return None

    months, months_source = None, None
    if brand_rule is not None and brand_rule.early_termination_months is not None:
        months, months_source = brand_rule.early_termination_months, "brand"
    elif default_rule is not None and default_rule.early_termination_months is not None:
        months, months_source = default_rule.early_termination_months, "default"

    early_return_fee = (
        formulas.round_currency(months * subscription_fee)
        if months is not None and subscription_fee is not None
        else None
    )
    return {
        "excess_mileage_charge_per_km": rule.excess_mileage_charge_per_km,
        "early_settlement": early_settlement,
        "subscription_early_return_months": months,
        "subscription_early_return_fee": early_return_fee,
        # Kept for older clients: the same months, now meaning months of the
        # SUBSCRIPTION fee (early_termination_amount is no longer sent).
        "early_termination_months": months,
        "early_termination_months_source": months_source,
        "wear_tear_tolerance_description": rule.wear_tear_tolerance_description,
        "rule_source": "brand" if brand_rule is not None else "default",
    }


PATHWAY_TCO_KEYS = ("hire_purchase", "gfv_retain", "gfv_return", "subscription")
_ZERO = Decimal("0.00")

# Run 3 fix batch 4 (F-10): GFV is only offered above 60 months when an admin keys an
# override for that tenure, and the GFV entries need the resale value at month t (the
# guarantee) - which the 61-point curve does not have. Said plainly, never a 500.
GFV_TCO_BEYOND_FORECAST_MESSAGE = (
    f"The resale forecast covers {formulas.HORIZON_MONTHS} months, so the total cost of this pathway cannot be "
    "worked out for a longer term."
)


def _unavailable_pathway_tco(reason, horizon_months):
    return {
        "available": False,
        "unavailable_reason": reason,
        "horizon_months": horizon_months,
        **{
            field: None
            for field in (
                "upfront_cash", "payments_total", "balloon_paid", "running_costs_total", "resale_credit",
                "settlement_debit", "deposit_refund", "gross", "net", "amount_back", "net_per_month",
            )
        },
    }


def _pathway_tco_entry(*, horizon_months, upfront_cash, payments_total, running_costs_total, gross, net,
                       balloon_paid=_ZERO, resale_credit=_ZERO, settlement_debit=_ZERO, deposit_refund=_ZERO,
                       **extra):
    return {
        "available": True,
        "unavailable_reason": None,
        "horizon_months": horizon_months,
        "upfront_cash": upfront_cash,
        "payments_total": payments_total,
        "balloon_paid": balloon_paid,
        "running_costs_total": running_costs_total,
        "resale_credit": resale_credit,
        "settlement_debit": settlement_debit,
        "deposit_refund": deposit_refund,
        "gross": gross,
        "net": net,
        # "What you get back": resale less any settlement for an owner, the
        # deposit for a subscriber, nothing for a GFV return.
        "amount_back": formulas.round_currency(gross - net),
        # The fair cross-pathway figure: an owner keeps the car 60 months, a
        # returner or subscriber only t ("net cost per month of use").
        "net_per_month": formulas.round_currency(net / Decimal(horizon_months)),
        **extra,
    }


def build_pathway_tco(
    *, comparison, downpayment, tenure_months, exact_hp_monthly, running_annual, resale_values, hp_tco,
    hp_balance_month_60,
):
    """Run 1 fix batch 4 (UC006 step 6): TCO for every pathway, "crediting the
    predicted retained asset value for pathways ending in ownership".

    One source per figure: every payment, balloon, deposit and outlay is the
    comparison's own; running costs are the owner's (buyer's NCD) from the
    one estimate_operating_costs call build_tco_report already made; resale is
    the same depreciation curve; the HP entry is exactly tco_gross / tco_net.

      hire_purchase  60 months  gross = tco_gross            net = tco_net
      gfv_retain     60 months  gross = D + GFV payments + balloon + running x 5
                                net   = gross - resale(60)
      gfv_return     t months   gross = D + GFV payments + running x t/12
                                net   = gross (car handed back, no balloon, no resale)
      subscription   t months   gross = deposit + fees (the comparison's outlay)
                                net   = gross - deposit refund (fees; running costs bundled)

    gfv_guarantee_value = max(0, balloon - resale(t)): what GFV's buy-back
    guarantee is worth on this forecast. An unavailable pathway keeps the
    comparison's own buyer-facing reason; a GFV offered above the forecast
    horizon (an admin override above 60 months) is unavailable here with
    GFV_TCO_BEYOND_FORECAST_MESSAGE.
    """
    horizon = formulas.HORIZON_MONTHS
    unavailable = comparison["unavailable"]
    hp, gfv, subscription = comparison["hire_purchase"], comparison["gfv_leasing"], comparison["subscription"]
    running_over = lambda months: formulas.round_currency(running_annual * Decimal(months) / Decimal(12))  # noqa: E731
    result = {}

    if hp is None:
        result["hire_purchase"] = _unavailable_pathway_tco(unavailable.get("hire_purchase"), horizon)
    else:
        result["hire_purchase"] = _pathway_tco_entry(
            horizon_months=horizon,
            upfront_cash=downpayment,
            payments_total=comparison_formulas.true_up_payments_through_month(
                exact_monthly=exact_hp_monthly, tenure_months=tenure_months, month=min(tenure_months, horizon)
            ),
            running_costs_total=running_over(horizon),
            resale_credit=resale_values[horizon],
            settlement_debit=hp_balance_month_60,
            gross=hp_tco["gross"],
            net=hp_tco["net"],
        )

    if gfv is None or tenure_months > horizon:
        # A GFV offered above the forecast horizon (an admin override) has no
        # resale value at month t to price against: unavailable, with a reason.
        reason = unavailable.get("gfv_leasing") if gfv is None else GFV_TCO_BEYOND_FORECAST_MESSAGE
        result["gfv_retain"] = _unavailable_pathway_tco(reason, horizon)
        result["gfv_return"] = _unavailable_pathway_tco(reason, tenure_months)
    else:
        balloon = gfv["balloon_payment"]
        gfv_payments = gfv["total_contract_outlay"] - gfv["upfront_cash"] - balloon
        guarantee = max(_ZERO, formulas.round_currency(balloon - resale_values[tenure_months]))
        retain_gross = formulas.round_currency(gfv["upfront_cash"] + gfv_payments + balloon + running_over(horizon))
        result["gfv_retain"] = _pathway_tco_entry(
            horizon_months=horizon,
            upfront_cash=gfv["upfront_cash"],
            payments_total=gfv_payments,
            balloon_paid=balloon,
            running_costs_total=running_over(horizon),
            resale_credit=resale_values[horizon],
            gross=retain_gross,
            net=formulas.round_currency(retain_gross - resale_values[horizon]),
            gfv_guarantee_value=guarantee,
        )
        return_gross = formulas.round_currency(gfv["upfront_cash"] + gfv_payments + running_over(tenure_months))
        result["gfv_return"] = _pathway_tco_entry(
            horizon_months=tenure_months,
            upfront_cash=gfv["upfront_cash"],
            payments_total=gfv_payments,
            running_costs_total=running_over(tenure_months),
            gross=return_gross,
            net=return_gross,
            gfv_guarantee_value=guarantee,
        )

    if subscription is None:
        result["subscription"] = _unavailable_pathway_tco(unavailable.get("subscription"), tenure_months)
    else:
        deposit = subscription["refundable_deposit"]
        fees = subscription["total_contract_outlay"]
        result["subscription"] = _pathway_tco_entry(
            horizon_months=tenure_months,
            upfront_cash=deposit,
            payments_total=fees,
            running_costs_total=_ZERO,  # bundled in the fee
            deposit_refund=deposit,
            gross=formulas.round_currency(deposit + fees),
            net=fees,
        )

    return result


def build_tco_report(
    *, vehicle, tenure_months, mileage_band, downpayment, declared_mileage_band=None, ncd_percent=Decimal("0")
):
    """Raises ComparisonConfigError (missing interest rate) or
    OperatingCostConfigError (the vehicle can't be costed: incomplete specs,
    or no rate row covers it) - both mapped to 400 by the view. Road tax,
    insurance and maintenance come from the single engine,
    apps.policy.operating_costs.estimate_operating_costs. ML inference
    itself never raises - see predict_resale_curve.

    `declared_mileage_band` (Batch 6C / UC006 step 9) is the caller's own
    policy.MileageBand-mapped version of the requesting user's saved
    FinancialProfile.annual_mileage_band, if any - None when the user has
    no saved profile. Passed in rather than looked up here so this
    function stays about ONE vehicle/tenure/mileage-band/downpayment
    combination, with no implicit per-request user dependency of its own
    (the view does that lookup - see TCOView.get).

    `ncd_percent` (run 1 fix batch 3) is the buyer's No-Claim Discount, from
    their own profile (apps.profiles.models.ncd_percent_for), applied to the
    owner's insurance here and in the Subscription offset; 0 = before NCD.
    """
    brand = vehicle.brand
    interest_rate_row = get_active_interest_rate(brand)
    annual_rate = interest_rate_row.rate_percent / Decimal(100)

    operating_costs = estimate_operating_costs(vehicle, ncd_percent=ncd_percent)
    annual_mileage_km = mileage.representative_km(mileage_band)

    resale_values, degraded, degraded_reason = predict_resale_curve(
        vehicle=vehicle, annual_mileage_km=annual_mileage_km
    )

    # F012 explainability add-on: explain the resale value at the end of
    # the user's own selected contract term (not a fixed reference point)
    # - the number actually relevant to what they're deciding. Skipped
    # entirely when degraded (no real deployed model to explain anyway);
    # explain_resale_prediction's own internal degrade-to-None covers
    # every other failure mode, so this is never allowed to break the
    # response - see apps/depreciation/inference.py.
    resale_value_explanation = None
    if not degraded:
        # Run 2 fix batch 3: whole sen, fixed factor order, parts adding up exactly
        # (see apps/depreciation/explanation.py); None stays None.
        resale_value_explanation = round_explanation(
            explain_resale_prediction(vehicle=vehicle, annual_mileage_km=annual_mileage_km, month=tenure_months)
        )

    exact_hp_monthly = comparison_formulas.exact_hp_monthly(vehicle.msrp, downpayment, tenure_months, annual_rate)
    hp_monthly = comparison_formulas.round_currency(exact_hp_monthly)

    # The estimated amount to settle the loan each month, reducing-balance
    # method at the effective rate (comparison_formulas.settlement_balance) -
    # the same figure the crossover, the >60-month TCO equity and the
    # contract checklist read. The rate is solved once for all 61 months.
    outstanding_balances = formulas.hp_settlement_schedule(
        vehicle.msrp, downpayment, tenure_months, annual_rate, range(formulas.HORIZON_MONTHS + 1)
    )

    crossover_month, shortfall_amount = formulas.find_negative_equity_crossover(
        resale_values, outstanding_balances
    )

    tco = formulas.calculate_tco(
        downpayment=downpayment,
        exact_hp_monthly=exact_hp_monthly,
        tenure_months=tenure_months,
        road_tax_annual=operating_costs.road_tax_annual,
        insurance_annual=operating_costs.insurance_annual,
        maintenance_annual=operating_costs.maintenance_annual,
        residual_value_month_60=resale_values[-1],
        # QA audit H10: credit net equity at month 60, not the raw resale
        # value - already computed above (0.00 whenever tenure_months <=
        # 60, the loan's already repaid by then).
        hp_outstanding_balance_month_60=outstanding_balances[-1],
    )

    monthly_forecast = [
        {
            "month": month,
            "predicted_resale_value": resale_values[month],
            "hp_outstanding_balance": outstanding_balances[month],
        }
        for month in range(formulas.HORIZON_MONTHS + 1)
    ]

    # Batch 6C / UC006 step 7: the same call apps.scoring.services.
    # build_suitability_scoring already makes on top of its own needs -
    # reused here for the risk radar's per-pathway scores. Never raises
    # (see build_comparison's own docstring); a pathway missing its own
    # config is simply absent from `comparison`, surfaced via
    # radar_unavailable instead.
    comparison = build_comparison(
        vehicle=vehicle, tenure_months=tenure_months, mileage_band=mileage_band, downpayment=downpayment,
        ncd_percent=ncd_percent,
    )
    risk_radar, radar_unavailable = _build_risk_radar(comparison=comparison, price=vehicle.msrp)

    pathway_tco = build_pathway_tco(
        comparison=comparison,
        downpayment=downpayment,
        tenure_months=tenure_months,
        exact_hp_monthly=exact_hp_monthly,
        running_annual=(
            operating_costs.road_tax_annual + operating_costs.insurance_annual + operating_costs.maintenance_annual
        ),
        resale_values=resale_values,
        hp_tco=tco,
        hp_balance_month_60=outstanding_balances[-1],
    )

    cumulative_cash_flow = formulas.build_cumulative_cash_flow(
        downpayment=downpayment,
        exact_hp_monthly=exact_hp_monthly,
        tenure_months=tenure_months,
        road_tax_annual=operating_costs.road_tax_annual,
        insurance_annual=operating_costs.insurance_annual,
        maintenance_annual=operating_costs.maintenance_annual,
    )

    subscription = comparison["subscription"]
    contract_checklist = build_contract_checklist(
        brand=brand,
        early_settlement=build_early_settlement(
            principal=vehicle.msrp - downpayment, exact_hp_monthly=exact_hp_monthly, tenure_months=tenure_months
        ),
        subscription_fee=subscription["monthly_instalment"] if subscription is not None else None,
    )

    risk_alerts = _build_risk_alerts(
        crossover_month=crossover_month,
        mileage_band=mileage_band,
        declared_mileage_band=declared_mileage_band,
    )

    # Run 2 fix batch 2: words only (see apps/depreciation/resale_notes.py) -
    # what the two resale figures are, from numbers this report already holds.
    resale_views_note = resale_notes.build_resale_views_note(
        tenure_months=tenure_months,
        gfv=comparison["gfv_leasing"],
        predicted_value=resale_values[tenure_months] if tenure_months <= formulas.HORIZON_MONTHS else None,
        price=vehicle.msrp,
        degraded=degraded,
    )
    resale_forecast_note = resale_notes.build_resale_forecast_note(degraded=degraded)
    # Run 3 fix batch 6: said only when the machine-learning curve is used AND the
    # mileage cap changed it (a very high band near the end of the forecast).
    forecast_cap_note = MILEAGE_CAP_NOTE if not degraded and mileage_cap_applies(annual_mileage_km) else None

    return {
        "vehicle_id": vehicle.id,
        "tenure_months": tenure_months,
        "mileage_band": mileage_band,
        "downpayment": downpayment,
        "hp_monthly": hp_monthly,
        "model_degraded": degraded,
        "degraded_reason": degraded_reason,
        # Run 2 fix batch 3: where the curve comes from - "ml_model", "model_unavailable"
        # (amber "Degraded") or "estimated_curve_unsupported" (this car is outside what
        # the model covers; a neutral "Estimated curve"). One eligibility check.
        "forecast_source": forecast_source(vehicle, degraded),
        "monthly_forecast": monthly_forecast,
        # Kept as the HIRE PURCHASE figures (older clients, saved snapshots);
        # pathway_tco["hire_purchase"] carries the same two numbers.
        "tco_gross": tco["gross"],
        "tco_net": tco["net"],
        "pathway_tco": pathway_tco,
        "road_tax_annual": operating_costs.road_tax_annual,
        "insurance_annual": operating_costs.insurance_annual,
        "maintenance_annual": operating_costs.maintenance_annual,
        # The NCD behind insurance_annual ("0.00" = before NCD).
        "ncd_percent": Decimal(str(ncd_percent)),
        # Plain-English basis for each figure (e.g. "1,998 cc petrol, saloon - JPJ cc schedule").
        "operating_cost_basis": operating_costs.basis,
        # FX-3: the policy value behind the maintenance figure (null = no cap).
        "operating_cost_policy": {"maintenance_cap_annual": operating_costs.maintenance_cap_annual},
        "negative_equity_crossover_month": crossover_month,
        "negative_equity_shortfall_amount": shortfall_amount,
        "resale_value_explanation": resale_value_explanation,
        "risk_radar": risk_radar,
        "radar_unavailable": radar_unavailable,
        "cumulative_cash_flow": cumulative_cash_flow,
        "contract_checklist": contract_checklist,
        "risk_alerts": risk_alerts,
        "resale_views_note": resale_views_note,
        "resale_forecast_note": resale_forecast_note,
        "forecast_cap_note": forecast_cap_note,
    }


def build_total_loss_sandbox(
    *, vehicle, tenure_months, mileage_band, downpayment, loss_month, excess_amount
):
    """Sprint 12 - standalone "what if this vehicle were written off in
    month M" sandbox, across all three pathways. Illustrative only (see
    the frontend disclaimer) - reuses predict_resale_curve() (F012's real
    deployed model, same degrade-to-fallback behaviour as build_tco_report:
    a degraded/fallback valuation is still shown, just flagged, never
    blocked) and hp_outstanding_balance() - no new ML, no new HP math.
    Adds formulas.gfv_outstanding_balance() for GFV. Subscription has no
    ownership stake, so its outstanding_balance/net_position are always
    None - not computed as zero, genuinely not applicable.

    HP and GFV are computed independently, same per-pathway graceful-
    degradation philosophy as apps.comparisons.services.build_comparison:
    a missing interest rate disables both (they share that dependency); a
    missing residual ratio disables only GFV. Never raises
    ComparisonConfigError itself - the unavailable pathway is `None` with
    its reason in `unavailable`, Subscription (independent of both) still
    computes. This sandbox never touches operating costs (road tax/
    insurance/maintenance), so OperatingCostConfigError can't occur here,
    unlike build_tco_report.

    `loss_month <= tenure_months` and the 10% minimum downpayment are
    both enforced by the serializer, not here (same division of
    responsibility as ComparisonRequestSerializer's own checks).

    Run 3 fix batch 4 (F-19): whether Hire Purchase and GFV are OFFERED at
    all is the comparison's decision, read from build_comparison itself
    (never a copy of its rules), with the comparison's own reason. Before,
    the sandbox only checked the interest rate and the residual, so a
    downpayment above GFV's financed amount (BMW 320i, 12 months, 50% down:
    "Your downpayment exceeds the amount financed under GFV ...") still got a
    GFV card whose "amount to settle" rose above the amount financed. When a
    pathway is offered its figures are computed exactly as before.
    """
    brand = vehicle.brand
    unavailable = {}

    comparison = build_comparison(
        vehicle=vehicle, tenure_months=tenure_months, mileage_band=mileage_band, downpayment=downpayment
    )
    for pathway in ("hire_purchase", "gfv_leasing"):
        if comparison[pathway] is None:
            unavailable[pathway] = comparison["unavailable"][pathway]

    interest_rate_row = None
    if "hire_purchase" not in unavailable:
        try:
            interest_rate_row = get_active_interest_rate(brand)
        except ComparisonConfigError as exc:  # the comparison checked it; kept so this never 500s
            unavailable["hire_purchase"] = unavailable["gfv_leasing"] = str(exc)

    annual_mileage_km = mileage.representative_km(mileage_band)
    resale_values, degraded, degraded_reason = predict_resale_curve(
        vehicle=vehicle, annual_mileage_km=annual_mileage_km
    )

    # predict_resale_curve only covers months 0-HORIZON_MONTHS (60), but a
    # contract's tenure_months (and therefore a legal loss_month) can run
    # up to MAX_TENURE_MONTHS (108, see apps/common/constants.py) - well
    # past what the model (or its estimated fallback curve, which ends at
    # its month-60 residual anchor) was ever asked to predict.
    # Rather than index past the end of the list (an unhandled 500) or
    # invent a new extrapolation past month 60, this reuses month 60's
    # value.
    # Flagged judgment call, not something the project spec specifies.
    #
    # QA audit L8: this reuse was previously silent - resale_value_is_plateaued
    # flags exactly when it kicked in, so the frontend can caveat the
    # insurance_payout figure instead of presenting it as if it were a
    # genuine month-80 (say) prediction.
    resale_value_is_plateaued = loss_month > formulas.HORIZON_MONTHS
    resale_value_at_loss_month = resale_values[min(loss_month, formulas.HORIZON_MONTHS)]

    insurance_payout = formulas.round_currency(
        max(resale_value_at_loss_month - excess_amount, Decimal("0"))
    )

    hire_purchase = None
    gfv_leasing = None

    if interest_rate_row is not None:
        annual_rate = interest_rate_row.rate_percent / Decimal(100)
        # Estimated amount to settle, reducing-balance method at the effective rate.
        hp_balance = formulas.hp_outstanding_balance(
            vehicle.msrp, downpayment, tenure_months, loss_month, annual_rate
        )
        hire_purchase = {
            "insurance_payout": insurance_payout,
            "outstanding_balance": hp_balance,
            "net_position": formulas.round_currency(insurance_payout - hp_balance),
            "has_ownership_exposure": HAS_OWNERSHIP_EXPOSURE["hire_purchase"],
        }

        # GFV only where the comparison offers it (its reason is already in
        # `unavailable` otherwise).
        if "gfv_leasing" not in unavailable:
            try:
                residual = resolve_residual_ratio(vehicle, tenure_months, mileage_band)
            except ResidualConfigError as exc:
                unavailable["gfv_leasing"] = gfv_residual_ratio_user_message(
                    brand, tenure_months, mileage_band, str(exc)
                )
            else:
                residual_ratio = residual.ratio
                gfv_balloon = calculate_gfv_balloon(vehicle.msrp, residual_ratio)
                gfv_balance = formulas.gfv_outstanding_balance(
                    price=vehicle.msrp,
                    downpayment=downpayment,
                    tenure_months=tenure_months,
                    month=loss_month,
                    gfv_balloon=gfv_balloon,
                    annual_rate=annual_rate,
                )
                gfv_leasing = {
                    "insurance_payout": insurance_payout,
                    "outstanding_balance": gfv_balance,
                    "net_position": formulas.round_currency(insurance_payout - gfv_balance),
                    "has_ownership_exposure": HAS_OWNERSHIP_EXPOSURE["gfv_leasing"],
                }

    # QA audit L8: a subscriber has no ownership stake at all - there's
    # nothing for an insurer to pay THEM for (any comprehensive cover on
    # the vehicle itself is the operator/fleet owner's policy, not
    # something this subscription contract gives the subscriber a claim
    # on). Null here, consistent with its already-null outstanding_balance/
    # net_position, not the same computed figure HP/GFV get.
    subscription = {
        "insurance_payout": None,
        "outstanding_balance": None,
        "net_position": None,
        "has_ownership_exposure": HAS_OWNERSHIP_EXPOSURE["subscription"],
    }

    return {
        "vehicle_id": vehicle.id,
        "tenure_months": tenure_months,
        "mileage_band": mileage_band,
        "downpayment": downpayment,
        "loss_month": loss_month,
        "excess_amount": excess_amount,
        "model_degraded": degraded,
        "degraded_reason": degraded_reason,
        "resale_value_is_plateaued": resale_value_is_plateaued,
        "hire_purchase": hire_purchase,
        "gfv_leasing": gfv_leasing,
        "subscription": subscription,
        "unavailable": unavailable,
    }
