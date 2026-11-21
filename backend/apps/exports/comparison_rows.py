"""Converts a build_comparison() result into everything
rendering.build_report_html needs to show a genuinely meaningful report.
QA audit C4: the PDF's pathway figures previously came straight from the
request body - any client could submit fabricated numbers ("RM 1.00
(bank-approved)") under an official-looking exported header. These rows
must always be built from the server's own authoritative
apps.comparisons.services.build_comparison result, the same single
source of truth every other endpoint uses - never from client input.

QA audit M16: build_pathway_report_rows() used to emit only label/
monthly_instalment/upfront_cash/total_contract_outlay - no tenure, no
downpayment, no mileage band, no date, no interest rate, no residual %,
no balloon, and no "RM" unit anywhere in the row values, making the
exported PDF almost meaningless as a standalone document (the one thing
a user might actually keep or hand to a bank). build_export_context()
below is the real entry point now - it returns both the enriched
per-pathway rows AND the comparison-level metadata (tenure/downpayment/
mileage band/generated-at) the template needs.
"""

from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.depreciation.formulas import HORIZON_MONTHS
from apps.policy.mileage import mileage_band_label
from apps.scoring.formulas import PATHWAY_LABELS, PATHWAYS

UNAVAILABLE_VALUE = "Not available"

# Run 2 fix batch 1: "Generated on" is a Malaysian buyer's document, so it is
# printed in Malaysia time (UTC+8, no daylight saving), labelled MYT.
REPORT_TIME_ZONE = ZoneInfo("Asia/Kuala_Lumpur")


def format_generated_at(moment=None):
    """'19 October 2026, 13:13 MYT' for an aware datetime (default: now)."""
    moment = moment or timezone.now()
    return moment.astimezone(REPORT_TIME_ZONE).strftime("%d %B %Y, %H:%M MYT")


def _format_flat_rate(value):
    """'2.80%' - the dealer's flat rate to 2 dp half-up, like the screen
    (the stored rate has 4 dp: 2.8000)."""
    return f"{Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"

# Same wording the Financing Pathways table shows on screen.
RATES_NOTE = (
    "Rates are shown as flat rates, the way dealers quote them. The effective rate is the "
    "reducing-balance equivalent a bank would disclose. Under the Hire-Purchase (Amendment) Act 2026, "
    "lenders move to effective-rate disclosure by 31 March 2027, so your final offer may be quoted "
    "that way."
)
ISLAMIC_NOTE = "Indicative: Islamic financing is not priced separately in this app."


def _format_money(value):
    return f"RM {value:,.2f}"


def _format_effective_rate(value):
    """'≈ 5.31%' (2 dp, half-up) - or None when there is no effective rate
    (an older figure, or no positive rate exists), so the row is skipped."""
    if value is None:
        return None
    rounded = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"≈ {rounded}%"


def build_pathway_report_rows(comparison, prefers_islamic_financing=False):
    """[{"label", "monthly_instalment", "upfront_cash",
    "total_contract_outlay", "extra": [{"label", "value"}, ...]}, ...] -
    `extra` carries whatever additional fields are specific to that one
    pathway (HP's interest rate; GFV's residual ratio and balloon
    payment) as label/value pairs, so the template can render a variable
    number of extra rows per pathway without needing to know their names.
    """
    rows = []
    for key in PATHWAYS:
        pathway = comparison[key]
        if pathway is None:
            rows.append(
                {
                    "label": PATHWAY_LABELS[key],
                    "monthly_instalment": UNAVAILABLE_VALUE,
                    "upfront_cash": UNAVAILABLE_VALUE,
                    "total_contract_outlay": UNAVAILABLE_VALUE,
                    "extra": [],
                    # Run 1 fix batch 5 (A12): the comparison's own buyer-facing
                    # reason, printed across the row instead of blank cells.
                    "unavailable_reason": comparison["unavailable"].get(key) or UNAVAILABLE_VALUE,
                }
            )
            continue

        extra = []
        if key == "hire_purchase":
            # The dealer's FLAT rate - what the instalment is built from. An
            # Islamic-financing preference only changes the wording (profit
            # rate, not interest); no figure changes.
            rate_label = "Profit rate (flat, p.a.)" if prefers_islamic_financing else "Flat rate (p.a.)"
            extra.append({"label": rate_label, "value": _format_flat_rate(pathway["interest_rate_percent"])})
            effective = _format_effective_rate(pathway.get("effective_rate_percent"))
            if effective:
                extra.append({"label": "Effective rate (p.a.)", "value": effective})
        elif key == "subscription":
            # Audit batch 5 keys are absent from a frozen older snapshot, so
            # each row is only added when its figure is present.
            if pathway.get("fee_source"):
                source = "Provider quote" if pathway["fee_source"] == "quote" else "Estimate"
                extra.append({"label": "Fee source", "value": source})
            if pathway.get("fee_basis"):
                extra.append({"label": "Fee basis", "value": pathway["fee_basis"]})
            if pathway.get("refundable_deposit") is not None:
                extra.append({
                    "label": "Refundable deposit (in upfront cash, returned at term end)",
                    "value": _format_money(pathway["refundable_deposit"]),
                })
            if pathway.get("mileage_note"):
                extra.append({"label": "Included mileage", "value": pathway["mileage_note"]})
        elif key == "gfv_leasing":
            extra.append(
                {
                    "label": "Residual value",
                    "value": f"{pathway['residual_value_ratio'] * 100:.2f}%",
                }
            )
            if pathway.get("residual_basis"):
                extra.append({"label": "Residual basis", "value": pathway["residual_basis"]})
            extra.append({"label": "Balloon payment (due at term end)", "value": _format_money(pathway["balloon_payment"])})
            effective = _format_effective_rate(pathway.get("effective_rate_percent"))
            if effective:
                extra.append({"label": "Effective rate (p.a.)", "value": effective})
            # Run 1 fix batch 4: the same end-of-term sentence as the screen.
            if pathway.get("end_of_term_note"):
                extra.append({"label": "At the end of the term", "value": pathway["end_of_term_note"]})

        rows.append(
            {
                "label": PATHWAY_LABELS[key],
                "monthly_instalment": _format_money(pathway["monthly_instalment"]),
                "upfront_cash": _format_money(pathway["upfront_cash"]),
                "total_contract_outlay": _format_money(pathway["total_contract_outlay"]),
                "extra": extra,
            }
        )
    return rows


# Run 1 fix batch 4: the TCO-for-every-pathway table (apps.depreciation.
# services.build_pathway_tco). Same labels and horizon notes as the TCO tab.
PATHWAY_TCO_LABELS = {
    "hire_purchase": "Hire Purchase",
    "gfv_retain": "GFV - pay the balloon and keep the car",
    "gfv_return": "GFV - hand the car back",
    "subscription": "Subscription",
}
PATHWAY_TCO_KEEPS_CAR = {"hire_purchase": True, "gfv_retain": True, "gfv_return": False, "subscription": False}
PATHWAY_TCO_NOTE = (
    "Net cost per month of use divides each net cost by how long you have the car: 60 months when you keep it, "
    "the contract term when it goes back - so the pathways compare fairly."
)


def pathway_tco_horizon_note(key, horizon_months):
    if PATHWAY_TCO_KEEPS_CAR[key]:
        return f"over {horizon_months} months, you keep the car"
    return f"over {horizon_months} months, car returned"


def build_pathway_tco_rows(pathway_tco):
    """[{"label", "horizon", "available", "unavailable_reason", "pay",
    "get_back", "net", "net_per_month"}, ...] - formatted strings of the
    server's own figures, in the TCO tab's order."""
    rows = []
    for key in ("hire_purchase", "gfv_retain", "gfv_return", "subscription"):
        entry = pathway_tco[key]
        row = {
            "label": PATHWAY_TCO_LABELS[key],
            "horizon": pathway_tco_horizon_note(key, entry["horizon_months"]),
            "available": entry["available"],
            "unavailable_reason": entry["unavailable_reason"] or UNAVAILABLE_VALUE,
        }
        if entry["available"]:
            # The API's 2 dp strings (they crossed the task's JSON boundary),
            # only re-formatted for print.
            row.update(
                pay=_format_money(Decimal(entry["gross"])),
                get_back=_format_money(Decimal(entry["amount_back"])),
                net=_format_money(Decimal(entry["net"])),
                net_per_month=_format_money(Decimal(entry["net_per_month"])),
            )
        rows.append(row)
    return rows


# --- Run 2 fix batch 1: the rest of the TCO tab ------------------------------------------
#
# Everything below is the TCO tab's own wording and the server's own figures
# (apps.depreciation.services.build_tco_report), formatted to strings here - the
# client sends none of it. The radar and cash-flow charts are not printed, and
# neither is the AI recommendation (the export request carries no ratings).

EQUITY_NOTE = (
    "Net TCO credits your estimated equity at month 60 (predicted resale value minus the estimated amount to "
    "settle the loan, reducing-balance method) - your lender's settlement letter is the final figure."
)
# FX-2 (item 13): insurance and maintenance are not mandatory - plain wording (it read "Mandatory annual operating costs").
RUNNING_COSTS_INTRO = "Yearly running costs (road tax, insurance, maintenance):"
RUNNING_COSTS_ASSUMPTION_NOTE = (
    "Estimates for Peninsular Malaysia, private car; insurance and maintenance are planning assumptions, not quotes."
)
BEFORE_NCD_NOTE = "Insurance shown before No-Claim Discount. Add your NCD in Financial Profile."
EXPLANATION_HELP = (
    "How much each factor moved the value from the new price (worked out on a log scale and shared in proportion)."
)
EXPLANATION_FACTOR_LABELS = {
    "vehicle_age": "Age",
    "mileage": "Mileage",
    "brand_code": "Brand tier",
    "engine_litres": "Engine size",
    "body_type": "Body type",
    "recond": "Recond import",
}
CHECKLIST_INTRO = (
    "Wear-and-tear tolerances, excess mileage charges, and what leaving early costs for this brand. Wear and "
    "tear is a checklist item only, not a cost in the totals: normal wear is already priced into the car's "
    "resale value, and only excess damage at return is billed."
)
CHECKLIST_NOT_CONFIGURED = "Contract terms not yet configured for this brand"
CHART_TITLE = "Remaining loan vs. predicted car value"
CHART_SETTLEMENT_NOTE = (
    "The remaining loan balance is an estimate of the amount needed to settle the loan, using the "
    "reducing-balance method that the Hire-Purchase (Amendment) Act 2026 requires for new loans. Your "
    "lender's settlement letter is the final figure."
)
# The two lines' colours on screen (Tailwind indigo-600 / red-600, which the
# page paints through CSS variables) as plain hex for the legend swatches.
CHART_RESALE_COLOR = "#4f39f6"
CHART_BALANCE_COLOR = "#e7000b"


def chart_intro(tenure_months):
    # Run 3 fix batch 5 (F-31): the forecast (and so the chart) stops at month 60; above that
    # the caption says it covers the first 60 months. Same sentence as the TCO tab
    # (frontend TcoReportView.chartIntro).
    if tenure_months > HORIZON_MONTHS:
        return (
            "Predicted resale value against the outstanding Hire Purchase balance over the first "
            f"{HORIZON_MONTHS} months of the {tenure_months}-month term; the resale forecast does not go beyond "
            f"{HORIZON_MONTHS} months."
        )
    return f"Predicted resale value against the outstanding Hire Purchase balance over the {tenure_months}-month term."


def _cents(value):
    """A Decimal (or float from the explanation) at 2 dp, half-up."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _signed_money(value):
    """'-RM 107,914.03' / '+RM 2,000.00' of an already-rounded Decimal."""
    return f"{'-' if value < 0 else '+'}RM {abs(value):,.2f}"


def _trim_months(months):
    """Decimal('3.00') -> '3', Decimal('2.50') -> '2.5'."""
    return f"{Decimal(months).normalize():f}"


def _months_word(months):
    return "month" if _trim_months(months) == "1" else "months"


def build_explanation_section(report):
    """The 'Why this predicted value?' block: the new price, every factor that
    moved it (a factor that rounds to exactly 0.00 is left out), the predicted
    value - or, when the curve is the estimated fallback, the fallback reason
    instead. None when there is nothing to say (no explanation and no
    fallback)."""
    if report.get("model_degraded"):
        return {"fallback_reason": report.get("degraded_reason") or UNAVAILABLE_VALUE}
    explanation = report.get("resale_value_explanation")
    if not explanation:
        return None
    rows = []
    for factor, label in EXPLANATION_FACTOR_LABELS.items():
        if factor not in explanation["contributions"]:
            continue
        amount = _cents(explanation["contributions"][factor])
        if amount == 0:
            continue
        rows.append({"label": label, "value": _signed_money(amount)})
    section = {
        "help": EXPLANATION_HELP,
        "new_price": _format_money(_cents(explanation["base_value"])),
        "rows": rows,
        "predicted": _format_money(_cents(explanation["predicted_value"])),
    }
    # Run 2 fix batch 2 (C6, E5): what the curve is - only here, where there is an
    # explanation (the machine-learning case), and only when the report has the note.
    if report.get("resale_forecast_note"):
        section["forecast_note"] = report["resale_forecast_note"]
    # Run 3 fix batch 6: only when the mileage cap changed the forecast.
    if report.get("forecast_cap_note"):
        section["forecast_cap_note"] = report["forecast_cap_note"]
    return section


def _early_settlement_text(checklist):
    settlement = checklist["early_settlement"]
    parts = ["No penalty under the reducing-balance method."]
    at_half = f"{_format_money(settlement['at_half_term'])}."
    if settlement.get("after_12_months") is not None:
        parts.append(
            f"Estimated amount to settle after 12 months: {_format_money(settlement['after_12_months'])}; "
            f"at month {settlement['half_term_month']}: {at_half}"
        )
    else:
        parts.append(f"Estimated amount to settle at month {settlement['half_term_month']}: {at_half}")
    return " ".join(parts)


def _subscription_early_return_text(checklist):
    months = checklist.get("subscription_early_return_months") or checklist.get("early_termination_months")
    if months is None:
        return "Not configured"
    fee = checklist.get("subscription_early_return_fee")
    lead = f"Up to {_trim_months(months)} {_months_word(months)} of the subscription fee"
    if fee is None:
        return f"{lead}."
    return f"{lead} (about {_format_money(fee)}), or the fees left, whichever is lower."


def _rule_source_note(checklist):
    source = checklist.get("rule_source")
    if source == "default":
        return "Terms from the default contract rule - planning estimates; typical terms vary by provider."
    if source == "brand":
        if checklist.get("early_termination_months_source") != "default":
            return "Terms from this brand's own contract rule."
        return "Terms from this brand's own contract rule (subscription early-return months from the default rule)."
    return None


def build_checklist_section(checklist):
    """The contract return checklist as label/value rows, or None when the
    brand has no rule (the template then says it is not configured)."""
    if checklist is None:
        return None
    return {
        "rows": [
            {"label": "Excess mileage charge", "value": f"{_format_money(checklist['excess_mileage_charge_per_km'])} / km"},
            {"label": "Settling a Hire Purchase loan early", "value": _early_settlement_text(checklist)},
            {"label": "Returning a subscription car early", "value": _subscription_early_return_text(checklist)},
            {"label": "Wear & tear tolerance", "value": checklist["wear_tear_tolerance_description"]},
        ],
        "source_note": _rule_source_note(checklist),
    }


def build_tco_sections(report):
    """Everything from the TCO tab the PDF prints beyond the pathway TCO table,
    as plain strings (JSON-safe for the Celery task): the 60-month summary, the
    annual running costs with their basis, the factor explanation, the risk
    alerts and the contract return checklist. `report` is build_tco_report's own
    return value."""
    basis = report.get("operating_cost_basis") or {}
    costs = [
        ("Road tax", report["road_tax_annual"], basis.get("road_tax")),
        ("Insurance", report["insurance_annual"], basis.get("insurance")),
        ("Maintenance", report["maintenance_annual"], basis.get("maintenance")),
    ]
    ncd = report.get("ncd_percent")
    summary = {
        "hp_monthly": _format_money(report["hp_monthly"]),
        "tco_gross": _format_money(report["tco_gross"]),
        "tco_net": _format_money(report["tco_net"]),
        "equity_note": EQUITY_NOTE,
    }
    # Run 2 fix batch 2 (E3): why the GFV residual and the predicted market value
    # differ - the server's own sentence, left out when it doesn't apply.
    if report.get("resale_views_note"):
        summary["resale_views_note"] = report["resale_views_note"]
    return {
        "summary": summary,
        "running_costs": {
            "intro": RUNNING_COSTS_INTRO,
            "items": [
                {"label": label, "amount": f"{_format_money(amount)} / yr", "basis": text} for label, amount, text in costs
            ],
            "assumption_note": RUNNING_COSTS_ASSUMPTION_NOTE,
            # Only at "0.00" (no discount applied); with a discount the insurance
            # basis line itself says "less N% NCD", as on the screen.
            "ncd_note": BEFORE_NCD_NOTE if ncd is not None and Decimal(str(ncd)) == 0 else None,
        },
        "explanation": build_explanation_section(report),
        "risk_alerts": [
            {"severity": alert["severity"], "message": alert["message"]} for alert in report.get("risk_alerts") or []
        ],
        "checklist": build_checklist_section(report.get("contract_checklist")),
    }


def build_export_context(
    comparison, prefers_islamic_financing=False, pathway_tco=None, tco_unavailable_reason=None, tco_sections=None
):
    """Everything apps.exports.rendering.build_report_html needs beyond
    the vehicle label/chart - all derived from the same authoritative
    `comparison` dict (and, run 1 fix batch 4, the TCO report's
    pathway_tco; run 2 fix batch 1, build_tco_sections), never from client
    input.
    """
    return {
        "tenure_months": comparison["tenure_months"],
        "downpayment": _format_money(comparison["downpayment"]),
        # The screen's own band label (with its km range), from the
        # one band list - not the model's raw choice label.
        "mileage_band_label": mileage_band_label(comparison["mileage_band"]),
        "generated_at": format_generated_at(),
        "pathways": build_pathway_report_rows(comparison, prefers_islamic_financing),
        "notes": [RATES_NOTE, *([ISLAMIC_NOTE] if prefers_islamic_financing else [])],
        "pathway_tco_rows": build_pathway_tco_rows(pathway_tco) if pathway_tco else [],
        "pathway_tco_note": PATHWAY_TCO_NOTE if pathway_tco else None,
        "tco_unavailable_reason": tco_unavailable_reason,
        "tco_sections": tco_sections,
    }
