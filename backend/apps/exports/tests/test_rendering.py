"""Tests the HTML WeasyPrint would compile, without needing WeasyPrint
itself to actually be importable in this environment (see pdf.py's
module docstring on why the weasyprint import is deferred)."""

from apps.exports.rendering import DISCLAIMER_TEXT, build_report_html

# QA audit M16: the real shape apps.exports.comparison_rows now builds -
# "RM"-prefixed, thousands-separated currency strings, and an `extra`
# list of pathway-specific label/value pairs (interest rate; residual
# value + balloon payment).
SAMPLE_PATHWAYS = [
    {
        "label": "Hire Purchase",
        "monthly_instalment": "RM 10,900.00",
        "upfront_cash": "RM 40,000.00",
        "total_contract_outlay": "RM 432,400.00",
        "extra": [{"label": "Interest rate (p.a.)", "value": "3.0000%"}],
    },
    {
        "label": "GFV Leasing",
        "monthly_instalment": "RM 5,344.44",
        "upfront_cash": "RM 40,000.00",
        "total_contract_outlay": "RM 432,400.00",
        "extra": [
            {"label": "Residual value", "value": "50.00%"},
            {"label": "Balloon payment (due at term end)", "value": "RM 200,000.00"},
        ],
    },
    {
        "label": "Subscription",
        "monthly_instalment": "RM 2,000.00",
        "upfront_cash": "RM 0.00",
        "total_contract_outlay": "RM 72,000.00",
        "extra": [],
    },
]

SAMPLE_CONTEXT = dict(
    vehicle_label="Honda City V",
    pathways=SAMPLE_PATHWAYS,
    tenure_months=36,
    downpayment="RM 40,000.00",
    mileage_band_label="Standard (10,000-19,999 km/year)",
    generated_at="03 October 2026, 14:30",
)


def test_report_html_includes_the_legal_disclaimer():
    html = build_report_html(**SAMPLE_CONTEXT)
    assert DISCLAIMER_TEXT in html
    assert "estimates" in html.lower()
    assert "decision-support" in html.lower()


def test_report_html_includes_vehicle_label_and_pathway_data():
    html = build_report_html(**SAMPLE_CONTEXT)

    assert "Honda City V" in html
    for pathway in SAMPLE_PATHWAYS:
        assert pathway["label"] in html
        assert pathway["monthly_instalment"] in html
        assert pathway["upfront_cash"] in html
        assert pathway["total_contract_outlay"] in html
        for item in pathway["extra"]:
            assert item["label"] in html
            assert item["value"] in html


def test_report_html_includes_comparison_level_metadata():
    """QA audit M16: tenure/downpayment/mileage band/generated-at - the
    PDF previously carried none of this, making it nearly meaningless as
    a standalone document.
    """
    html = build_report_html(**SAMPLE_CONTEXT)

    assert "36 months" in html
    assert "RM 40,000.00" in html
    assert "Standard (10,000-19,999 km/year)" in html
    assert "03 October 2026, 14:30" in html


def test_report_html_embeds_a_safe_chart_svg_unescaped():
    """QA audit C4: chart_svg is sanitized (see test_svg_sanitizer.py for
    the exhaustive allowlist tests) before it reaches the template - this
    just confirms a SAFE, simple chart still survives that round trip and
    is embedded as real markup (not HTML-escaped, not rasterized to an
    <img>), not that the original string passes through byte-for-byte.
    """
    chart_svg = '<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" /></svg>'

    html = build_report_html(**SAMPLE_CONTEXT, chart_svg=chart_svg)

    assert "<circle" in html
    assert 'cx="50"' in html
    assert 'cy="50"' in html
    assert 'r="40"' in html
    assert "&lt;svg" not in html
    assert "<img" not in html


def test_report_html_omits_chart_section_when_no_svg_given():
    html = build_report_html(**SAMPLE_CONTEXT)
    assert '<div class="chart">' not in html


def test_report_html_omits_chart_section_when_svg_is_unsafe():
    """A malicious chart_svg (e.g. one trying to break out of the chart
    div, or load an external resource) sanitizes down to "" - the chart
    section is simply omitted, never a crash, never a pass-through. The
    template's OWN <style> block (its page CSS) is expected and unrelated
    - only the injected payload's content must not survive.
    """
    malicious_svg = '</div><style>.disclaimer{display:none}</style><div>'

    html = build_report_html(**SAMPLE_CONTEXT, chart_svg=malicious_svg)

    assert '<div class="chart">' not in html
    assert "display:none" not in html
    assert ".disclaimer{display:none}" not in html
