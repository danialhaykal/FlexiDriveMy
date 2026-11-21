"""Run 3 fix batch 5 (F-31): for a loan longer than the 60-month resale forecast the
chart stops at month 60, and its caption now says so - on the TCO tab (frontend
TcoReportView.chartIntro, same sentence) and in the PDF. Unchanged up to 60 months.
The forecast horizon itself is not extended."""

import io

import pytest
from rest_framework.test import APIClient

from apps.exports.comparison_rows import chart_intro
from apps.policy.models import InterestRate
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("tenure", [12, 36, 60])
def test_up_to_60_months_the_caption_is_unchanged(tenure):
    assert chart_intro(tenure) == (
        f"Predicted resale value against the outstanding Hire Purchase balance over the {tenure}-month term.")


@pytest.mark.parametrize("tenure", [72, 84, 108])
def test_above_60_months_the_caption_says_the_chart_covers_the_first_60(tenure):
    assert chart_intro(tenure) == (
        "Predicted resale value against the outstanding Hire Purchase balance over the first 60 months of the "
        f"{tenure}-month term; the resale forecast does not go beyond 60 months."
    )


@pytest.fixture
def car():
    brand = Brand.objects.create(name="CaptionBrand", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="2.8000")
    return VehicleModel.objects.create(
        brand=brand, name="Saloon", trim="X", body_segment=BodySegment.SEDAN, msrp="267800.00",
        engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998,
    )


def test_the_108_month_pdf_prints_the_new_caption(regular_user, car):
    try:
        import weasyprint  # noqa: F401
    except Exception as exc:  # native libraries missing (OSError, not ImportError)
        pytest.skip(f"weasyprint is not usable in this environment: {exc}")
    pypdf = pytest.importorskip("pypdf")
    client = APIClient()
    client.force_authenticate(user=regular_user)

    response = client.post("/api/exports/pdf/", {
        "vehicle": car.pk, "tenure_months": 108, "mileage_band": "standard", "downpayment": "26780.00",
        "chart_svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>',
    }, format="json")

    assert response.status_code == 200
    text = " ".join(" ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(response.content)).pages).split())
    assert chart_intro(108) in text
    assert "over the 108-month term." not in text
