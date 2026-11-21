"""F008 - builds the HTML string WeasyPrint compiles (UC008 Rule 1: must
explicitly include the decision-support disclaimer)."""

from django.template.loader import render_to_string

from . import comparison_rows
from .svg_sanitizer import sanitize_chart_svg

DISCLAIMER_TEXT = (
    "The figures presented in this report are estimates generated for decision-support "
    "purposes only and do not constitute a financial offer, guarantee, or binding "
    "quotation. Actual financing terms are subject to lender approval, prevailing "
    "interest rates, and vehicle valuation at the time of application."
)


def build_report_html(
    *, vehicle_label, pathways, tenure_months, downpayment, mileage_band_label, generated_at, chart_svg="", notes=(),
    pathway_tco_rows=(), pathway_tco_note=None, tco_unavailable_reason=None, tco_sections=None,
):
    """`pathways` is a list of dicts: [{"label", "monthly_instalment",
    "upfront_cash", "total_contract_outlay", "extra"}, ...] -
    `tenure_months`/`downpayment`/`mileage_band_label`/`generated_at` are
    the comparison-level context a standalone PDF needs to actually mean
    something (QA audit M16) - all built server-side from
    apps.comparisons.services.build_comparison via
    apps.exports.comparison_rows.build_export_context, never from client
    input (see also QA audit C4).

    `chart_svg`, if given, is real SVG markup embedded verbatim (never
    rasterized, per the project spec) - but first sanitized to an inert,
    allowlisted subset (see apps.exports.svg_sanitizer) before being
    rendered with Django's |safe filter, since it's still fundamentally
    client-supplied markup (a Recharts chart rendered in the browser).

    Run 2 fix batch 1: with a chart, the page also prints its title, the
    one-line explanation, a legend built here (not part of the captured SVG)
    and the settlement disclaimer. `tco_sections` is
    comparison_rows.build_tco_sections' output (the rest of the TCO tab), or
    None when the TCO could not be built.
    """
    chart_svg = sanitize_chart_svg(chart_svg)
    return render_to_string(
        "exports/comparison_report.html",
        {
            "vehicle_label": vehicle_label,
            "pathways": pathways,
            "tenure_months": tenure_months,
            "downpayment": downpayment,
            "mileage_band_label": mileage_band_label,
            "generated_at": generated_at,
            "notes": list(notes),
            # Run 1 fix batch 4: TCO for every pathway (pre-formatted rows).
            "pathway_tco_rows": list(pathway_tco_rows),
            "pathway_tco_note": pathway_tco_note,
            "tco_unavailable_reason": tco_unavailable_reason,
            "tco_sections": tco_sections,
            "checklist_intro": comparison_rows.CHECKLIST_INTRO,
            "checklist_not_configured": comparison_rows.CHECKLIST_NOT_CONFIGURED,
            "chart_svg": chart_svg,
            "chart": {
                "title": comparison_rows.CHART_TITLE,
                "intro": comparison_rows.chart_intro(tenure_months),
                "settlement_note": comparison_rows.CHART_SETTLEMENT_NOTE,
                "resale_color": comparison_rows.CHART_RESALE_COLOR,
                "balance_color": comparison_rows.CHART_BALANCE_COLOR,
            },
            "disclaimer_text": DISCLAIMER_TEXT,
        },
    )
