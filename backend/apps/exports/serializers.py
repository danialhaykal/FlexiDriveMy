from rest_framework import serializers

from apps.comparisons.serializers import ComparisonRequestSerializer

# The real negative-equity chart is measured by NegativeEquityChart.size.test.tsx
# (frontend) at 600, 1024 (the page's widest) and 1600px. Its largest - 108
# months at 1024px - is 113,149 bytes, so the 300,000 first proposed left only
# 2.7x; this leaves 3.5x. A 1.4 MB SVG (the size that held a request for 35 s)
# is refused.
MAX_CHART_SVG_BYTES = 400_000
CHART_TOO_LARGE_MESSAGE = "The chart is too large to include in the PDF. Please refresh the page and try again."


class PDFExportRequestSerializer(ComparisonRequestSerializer):
    """UC008: the client supplies the SAME inputs F005's own comparison
    endpoint takes (vehicle/tenure_months/mileage_band/downpayment,
    including that serializer's existing validation - price/10%-minimum
    checks) - the view then recomputes the authoritative pathway figures
    itself via apps.comparisons.services.build_comparison, the single
    source of truth every other endpoint already uses, rather than
    trusting whatever a client claims a pathway's monthly instalment was
    (QA audit C4: a client could previously submit fabricated figures -
    e.g. "RM 1.00 (bank-approved)" - under an official-looking exported
    PDF header).

    chart_svg is still client-supplied (a Recharts chart rendered in the
    browser, per the project spec - WeasyPrint has no JS runtime to render a
    chart itself) but is sanitized to an inert markup subset before it
    ever reaches the template - see apps.exports.svg_sanitizer.
    """

    chart_svg = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_chart_svg(self, value):
        # Run 1 fix batch 2 (G4): an unbounded SVG held the request for 35 s
        # and slowed every other user. Measured in UTF-8 bytes, before any
        # parsing - see MAX_CHART_SVG_BYTES for the headroom over the real chart.
        if len(value.encode("utf-8")) > MAX_CHART_SVG_BYTES:
            raise serializers.ValidationError(CHART_TOO_LARGE_MESSAGE)
        return value
