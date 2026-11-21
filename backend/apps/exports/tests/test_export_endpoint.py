import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.exports import tasks
from apps.exports.models import PDFExportFailureReason, PDFExportJob, PDFExportJobStatus
from apps.exports.pdf import ENGINE_UNAVAILABLE_MESSAGE, PDFCompilationTimeoutError, PDFEngineUnavailableError, TIMEOUT_MESSAGE
from apps.policy.models import InterestRate, MileageBand, ResidualValueMatrix, SubscriptionPlan
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def brand():
    return Brand.objects.create(name="ExportBrand", tier_code="A")


@pytest.fixture
def vehicle(brand):
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00",
    )


@pytest.fixture
def fully_configured(vehicle, brand):
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    ResidualValueMatrix.objects.create(
        brand=brand, tenure_months=36, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.5000"
    )
    SubscriptionPlan.objects.create(
        vehicle=vehicle, fee_monthly="1450.00", insurance_annual="3600.00",
        road_tax_annual="1200.00", maintenance_annual="1800.00",
    )
    return vehicle


def export_payload(vehicle, **overrides):
    """QA audit C4: the request carries only the SAME inputs F005's own
    comparison endpoint takes - never pathway figures. The server
    recomputes those itself via build_comparison."""
    payload = {
        "vehicle": vehicle.id,
        "tenure_months": 36,
        "mileage_band": MileageBand.STANDARD,
        "downpayment": "10000.00",
        "chart_svg": "",
    }
    payload.update(overrides)
    return payload


def test_requires_authentication(fully_configured):
    client = APIClient()
    response = client.post("/api/exports/pdf/", export_payload(fully_configured), format="json")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Successful export (compile step mocked - no real WeasyPrint needed) --


def test_successful_export_streams_pdf_bytes(user_client, fully_configured, regular_user, monkeypatch):
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: b"%PDF-1.7 fake bytes")

    response = user_client.post("/api/exports/pdf/", export_payload(fully_configured), format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response["Content-Type"] == "application/pdf"
    assert "attachment" in response["Content-Disposition"]
    assert response.content == b"%PDF-1.7 fake bytes"

    job = PDFExportJob.objects.get(user=regular_user)
    assert job.status == PDFExportJobStatus.SUCCEEDED
    assert job.file_path


# --- C4: the PDF's figures are always the server's own, never the client's -


def test_exported_pathways_are_computed_server_side_not_taken_from_the_request(
    user_client, fully_configured, monkeypatch
):
    """A client sending fabricated figures in the request body has no
    effect on what gets printed - build_report_html (the step that feeds
    the template) only ever receives rows apps.exports.comparison_rows
    built from the server's own build_comparison() result.
    """
    captured = {}

    def _capture_html(**kwargs):
        captured.update(kwargs)
        return "<html></html>"

    monkeypatch.setattr(tasks, "build_report_html", _capture_html)
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: b"%PDF-1.7 fake bytes")

    payload = export_payload(
        fully_configured,
        pathways=[{"label": "Hire Purchase", "monthly_instalment": "1.00", "upfront_cash": "0.00", "total_contract_outlay": "1.00"}],
    )
    response = user_client.post("/api/exports/pdf/", payload, format="json")

    assert response.status_code == status.HTTP_200_OK
    hp_row = next(row for row in captured["pathways"] if row["label"] == "Hire Purchase")
    assert hp_row["monthly_instalment"] != "1.00"
    # The real HP monthly for this fixture: (90000)/36 + 90000*0.03/12 =
    # 2725.00, formatted with an "RM" prefix and thousands separator
    # (QA audit M16).
    assert hp_row["monthly_instalment"] == "RM 2,725.00"
    # M16: the comparison-level metadata is now threaded through too.
    assert captured["tenure_months"] == 36
    assert captured["downpayment"] == "RM 10,000.00"
    # Run 1 fix batch 5 (A12): the screen's own band wording, from the one band list.
    # Run 3 fix batch 6: "Standard (up to 20,000 km/year)" before the recalibration.
    assert captured["mileage_band_label"] == "Standard — 10,001 to 15,000 km/year"
    assert captured["generated_at"]


def test_unavailable_pathway_is_reported_as_not_available_not_silently_dropped(
    user_client, vehicle, monkeypatch
):
    """vehicle has no InterestRate/ResidualValueMatrix/SubscriptionPlan at
    all - every pathway is unavailable, and each row says so rather than
    the export silently omitting rows or crashing.
    """
    captured = {}

    def _capture_html(**kwargs):
        captured.update(kwargs)
        return "<html></html>"

    monkeypatch.setattr(tasks, "build_report_html", _capture_html)
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: b"%PDF-1.7 fake bytes")

    response = user_client.post("/api/exports/pdf/", export_payload(vehicle), format="json")

    assert response.status_code == status.HTTP_200_OK
    assert len(captured["pathways"]) == 3
    for row in captured["pathways"]:
        assert row["monthly_instalment"] == "Not available"
        assert row["extra"] == []


# --- PDF compilation failure paths (UC008 alt flow / QA audit C3b) ---------


def test_timeout_failure_returns_504_with_uc008_message(user_client, fully_configured, monkeypatch):
    def _raise(html, timeout_seconds):
        raise PDFCompilationTimeoutError(TIMEOUT_MESSAGE)

    monkeypatch.setattr(tasks, "render_pdf_with_timeout", _raise)

    response = user_client.post("/api/exports/pdf/", export_payload(fully_configured), format="json")

    assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert response.data["detail"] == TIMEOUT_MESSAGE

    job = PDFExportJob.objects.latest("created_at")
    assert job.status == PDFExportJobStatus.FAILED
    assert job.failure_reason == PDFExportFailureReason.TIMEOUT
    assert job.error_message == TIMEOUT_MESSAGE


def test_engine_unavailable_failure_returns_503_not_a_fabricated_timeout(
    user_client, fully_configured, monkeypatch
):
    """QA audit C3b: WeasyPrint/GTK being unavailable (or any other non-
    timeout compilation failure) must be reported honestly - 503, with a
    message that doesn't claim a timeout happened, because one didn't.
    """

    def _raise(html, timeout_seconds):
        raise PDFEngineUnavailableError(ENGINE_UNAVAILABLE_MESSAGE)

    monkeypatch.setattr(tasks, "render_pdf_with_timeout", _raise)

    response = user_client.post("/api/exports/pdf/", export_payload(fully_configured), format="json")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.data["detail"] == ENGINE_UNAVAILABLE_MESSAGE
    assert "timeout" not in response.data["detail"].lower()

    job = PDFExportJob.objects.latest("created_at")
    assert job.status == PDFExportJobStatus.FAILED
    assert job.failure_reason == PDFExportFailureReason.ENGINE_UNAVAILABLE


# --- Request validation ----------------------------------------------------


def test_missing_vehicle_rejected(user_client):
    response = user_client.post(
        "/api/exports/pdf/", {"tenure_months": 36, "mileage_band": "standard", "downpayment": "10000.00"}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_unknown_vehicle_rejected(user_client):
    response = user_client.post(
        "/api/exports/pdf/",
        {"vehicle": 999999, "tenure_months": 36, "mileage_band": "standard", "downpayment": "10000.00", "chart_svg": ""},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_downpayment_below_10_percent_is_rejected(user_client, fully_configured):
    response = user_client.post(
        "/api/exports/pdf/", export_payload(fully_configured, downpayment="5000.00"), format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
