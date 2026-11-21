"""Real end-to-end WeasyPrint compilation - proves F008 actually produces
a valid PDF with the disclaimer surviving compilation, not just present in
the pre-compile HTML (that weaker guarantee is covered in test_rendering.py).

Skipped wherever `import weasyprint` fails - confirmed to fail on this dev
machine (missing native GObject/Pango libraries; see apps/exports/pdf.py's
module docstring) but expected to work in a proper Linux/CI environment,
where this test then actually exercises the real compilation path.
"""

import pytest
from rest_framework.test import APIClient

from apps.exports.pdf import render_pdf_with_timeout
from apps.exports.rendering import DISCLAIMER_TEXT, build_report_html
from apps.policy.models import InterestRate, MileageBand, SubscriptionPlan
from apps.vehicles.models import Brand, BodySegment, VehicleModel

try:
    import weasyprint  # noqa: F401
except Exception as exc:  # WeasyPrint's native GObject/Pango dependency can
    # raise OSError (not ImportError) when its shared libraries are
    # missing, which plain importorskip() (ImportError-only) won't catch.
    pytest.skip(f"weasyprint is not usable in this environment: {exc}", allow_module_level=True)

try:
    import pypdf
except ImportError as exc:
    pytest.skip(f"pypdf not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.django_db


SAMPLE_PATHWAYS = [
    {
        "label": "Hire Purchase",
        "monthly_instalment": "RM 10,900.00",
        "upfront_cash": "RM 40,000.00",
        "total_contract_outlay": "RM 432,400.00",
        "extra": [{"label": "Interest rate (p.a.)", "value": "3.0000%"}],
    },
]


def extract_text(pdf_bytes):
    import io

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_compiled_pdf_is_valid_and_contains_the_disclaimer():
    html = build_report_html(
        vehicle_label="Honda City V",
        pathways=SAMPLE_PATHWAYS,
        tenure_months=36,
        downpayment="RM 40,000.00",
        mileage_band_label="Standard (10,000-19,999 km/year)",
        generated_at="03 October 2026, 14:30",
    )

    pdf_bytes = render_pdf_with_timeout(html, timeout_seconds=30)

    assert pdf_bytes.startswith(b"%PDF-")
    text = extract_text(pdf_bytes)
    assert "estimates" in text.lower()
    assert "decision-support" in text.lower()


def test_full_export_endpoint_produces_a_real_downloadable_pdf(regular_user):
    brand = Brand.objects.create(name="RealPDFBrand", tier_code="A")
    vehicle = VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00",
    )
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    SubscriptionPlan.objects.create(
        vehicle=vehicle, fee_monthly="1450.00", insurance_annual="3600.00",
        road_tax_annual="1200.00", maintenance_annual="1800.00",
    )
    client = APIClient()
    client.force_authenticate(user=regular_user)

    response = client.post(
        "/api/exports/pdf/",
        {
            "vehicle": vehicle.id,
            "tenure_months": 36,
            "mileage_band": MileageBand.STANDARD,
            "downpayment": "10000.00",
            "chart_svg": "",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    # Text extraction keeps the PDF's own line wraps (e.g. "binding\nquotation"),
    # so compare with whitespace collapsed - every word must still survive, in order.
    first_sentence = " ".join(DISCLAIMER_TEXT.split(".")[0].split())
    assert first_sentence in " ".join(extract_text(response.content).split())
