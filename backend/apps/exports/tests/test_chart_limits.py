"""Run 1 fix batch 2 (G4): the PDF's client-supplied chart is size-limited.

A 1.4 MB SVG held the request for 35 s and slowed everyone else. Now a chart
over MAX_CHART_SVG_BYTES (UTF-8 bytes) is a 400 before anything runs, and one
over MAX_CHART_SVG_ELEMENTS is dropped while sanitizing so the PDF still
exports without it. The real 108-month chart is far under both (measured in
NegativeEquityChart.size.test.tsx).
"""

import logging

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.exports import tasks
from apps.exports.serializers import CHART_TOO_LARGE_MESSAGE, MAX_CHART_SVG_BYTES
from apps.exports.svg_sanitizer import MAX_CHART_SVG_ELEMENTS, sanitize_chart_svg
from apps.policy.models import InterestRate
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'


def svg_with(element_count):
    """An <svg> holding element_count elements in total (the root included)."""
    return SVG_OPEN + '<rect x="1" y="1" width="2" height="2"/>' * (element_count - 1) + "</svg>"


@pytest.fixture
def vehicle():
    brand = Brand.objects.create(name="ChartBrand", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN, msrp="100000.00",
        engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1998,
    )


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


@pytest.fixture
def rendered_html(monkeypatch):
    """Captures the HTML handed to the PDF engine (no real WeasyPrint needed)."""
    captured = []

    def fake_render(html, timeout_seconds):
        captured.append(html)
        return b"%PDF-1.7 fake bytes"

    monkeypatch.setattr(tasks, "render_pdf_with_timeout", fake_render)
    return captured


def export(client, vehicle, chart_svg):
    return client.post("/api/exports/pdf/", {
        "vehicle": vehicle.id, "tenure_months": 36, "mileage_band": "standard", "downpayment": "10000.00",
        "chart_svg": chart_svg,
    }, format="json")


# --- the byte cap ---------------------------------------------------------------------------------------


def test_a_chart_over_the_byte_cap_is_a_400_before_anything_runs(client, vehicle, rendered_html):
    oversize = SVG_OPEN + "<title>" + "x" * MAX_CHART_SVG_BYTES + "</title></svg>"

    response = export(client, vehicle, oversize)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["chart_svg"] == [CHART_TOO_LARGE_MESSAGE]
    assert rendered_html == []  # no PDF job ran


def test_the_cap_counts_utf8_bytes_not_characters(client, vehicle, rendered_html):
    # 2-byte characters: under the limit in characters, over it in bytes.
    chars = MAX_CHART_SVG_BYTES // 2
    multibyte = SVG_OPEN + "<title>" + "é" * chars + "</title></svg>"
    assert len(multibyte) < MAX_CHART_SVG_BYTES < len(multibyte.encode("utf-8"))

    response = export(client, vehicle, multibyte)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["chart_svg"] == [CHART_TOO_LARGE_MESSAGE]


# --- the element cap --------------------------------------------------------------------------------------


def test_a_chart_over_the_element_cap_is_dropped_and_the_pdf_still_builds(client, vehicle, rendered_html, caplog):
    too_many = svg_with(MAX_CHART_SVG_ELEMENTS + 1)
    assert len(too_many.encode("utf-8")) < MAX_CHART_SVG_BYTES  # so it is the element cap that acts

    with caplog.at_level(logging.WARNING, logger="apps.exports.svg_sanitizer"):
        response = export(client, vehicle, too_many)

    assert response.status_code == status.HTTP_200_OK
    assert response.content == b"%PDF-1.7 fake bytes"
    assert len(rendered_html) == 1
    assert '<div class="chart">' not in rendered_html[0] and "<rect" not in rendered_html[0]
    assert any("more than 5000 elements" in record.getMessage() for record in caplog.records)


def test_a_normal_chart_still_embeds(client, vehicle, rendered_html):
    chart = SVG_OPEN + '<g><path d="M0 0 L10 10" stroke="#123456"/><text x="1" y="2">RM 1,000</text></g></svg>'

    response = export(client, vehicle, chart)

    assert response.status_code == status.HTTP_200_OK
    assert '<div class="chart"><svg' in rendered_html[0]
    assert '<path d="M0 0 L10 10" stroke="#123456" />' in rendered_html[0]


def test_exactly_the_element_cap_is_kept_and_one_more_is_dropped():
    assert sanitize_chart_svg(svg_with(MAX_CHART_SVG_ELEMENTS)).count("<rect") == MAX_CHART_SVG_ELEMENTS - 1
    assert sanitize_chart_svg(svg_with(MAX_CHART_SVG_ELEMENTS + 1)) == ""


def test_nesting_deeper_than_python_can_walk_is_dropped_not_a_crash():
    depth = 3_000  # well under both caps' byte size, far past the recursion limit
    deep = SVG_OPEN + "<g>" * depth + "</g>" * depth + "</svg>"

    assert sanitize_chart_svg(deep) == ""


def test_the_existing_safety_rules_still_apply():
    hostile = SVG_OPEN + '<script>alert(1)</script><rect width="1" height="1" onclick="x()" style="display:none"/></svg>'

    result = sanitize_chart_svg(hostile)

    assert "<script" not in result and "onclick" not in result and "style" not in result
    assert "<rect" in result
