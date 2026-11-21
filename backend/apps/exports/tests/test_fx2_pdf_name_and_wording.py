"""FX-2 (item 13): the downloaded PDF is named FlexiDriveMy_{brand}-{model}_{tenure}m_{YYYY-MM-DD}.pdf (ASCII, the
Malaysia date) instead of comparison_report_{job id}.pdf, in both PDF modes; the browser may read that header
cross-origin; and the running-costs line no longer calls insurance and maintenance "mandatory". No figure changes."""

import datetime
import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.exports import tasks
from apps.exports.comparison_rows import RUNNING_COSTS_INTRO
from apps.exports.filenames import download_name_from_stored_path, pdf_download_name
from apps.exports.models import PDFExportJob, PDFExportJobStatus
from apps.exports.storage import save_pdf
from apps.policy.models import InterestRate
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")


@pytest.fixture
def bmw():
    brand = Brand.objects.create(name="BMW", tier_code="2")
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=brand, rate_percent="2.8000", is_active=True)
    return VehicleModel.objects.create(
        brand=brand, name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN, msrp="265800.00",
        engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998,
    )


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


def body(vehicle, tenure=36):
    return {"vehicle": vehicle.pk, "tenure_months": tenure, "mileage_band": "standard", "downpayment": "26580.00", "chart_svg": ""}


def car(brand, name):
    return SimpleNamespace(brand=SimpleNamespace(name=brand), name=name)


@pytest.mark.parametrize("brand, name, tenure, expected", [
    ("BMW", "3 Series", 36, "FlexiDriveMy_BMW-3-Series_36m_2026-11-02.pdf"),
    ("Mercedes-Benz", "C-Class C200", 48, "FlexiDriveMy_Mercedes-Benz-C-Class-C200_48m_2026-11-02.pdf"),
    ("Škoda", "Octávia  RS!", 108, "FlexiDriveMy_Skoda-Octavia-RS_108m_2026-11-02.pdf"),
])
def test_download_name_is_ascii_brand_model_tenure_and_date(brand, name, tenure, expected):
    assert pdf_download_name(car(brand, name), tenure, on_date=datetime.date(2026, 11, 2)) == expected


def test_a_stored_file_carries_its_download_name_and_older_files_keep_the_old_one():
    assert download_name_from_stored_path("/x/export_7_ab12cd34__FlexiDriveMy_BMW-3-Series_36m_2026-11-02.pdf", 7) == (
        "FlexiDriveMy_BMW-3-Series_36m_2026-11-02.pdf")
    assert download_name_from_stored_path("C:\\x\\export_7_ab12cd34.pdf", 7) == "comparison_report_7.pdf"
    assert download_name_from_stored_path("/x/export_7_ab__bad name\".pdf", 7) == "comparison_report_7.pdf"


def test_eager_export_names_the_file_after_the_car_tenure_and_today(client, bmw, monkeypatch):
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: b"%PDF")

    response = client.post("/api/exports/pdf/", body(bmw), format="json")

    assert response.status_code == 200
    today = timezone.localdate()
    assert response["Content-Disposition"] == f'attachment; filename="FlexiDriveMy_BMW-3-Series_36m_{today:%Y-%m-%d}.pdf"'
    assert response.content == b"%PDF"


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_a_queued_export_downloads_under_the_same_name(client, bmw, monkeypatch):
    sent = {}
    monkeypatch.setattr(tasks.generate_pdf_task, "delay", lambda *args, **kwargs: sent.update(kwargs))

    job_id = client.post("/api/exports/pdf/", body(bmw, tenure=60), format="json").data["job_id"]
    expected = f"FlexiDriveMy_BMW-3-Series_60m_{timezone.localdate():%Y-%m-%d}.pdf"
    assert sent["download_name"] == expected

    job = PDFExportJob.objects.get(pk=job_id)  # the worker finishes it with the name it was given
    job.file_path = save_pdf(b"%PDF-1.7", job.pk, download_name=sent["download_name"])
    job.status = PDFExportJobStatus.SUCCEEDED
    job.save()

    download = client.get(f"/api/exports/pdf/{job_id}/download/")
    assert download.status_code == 200
    assert download["Content-Disposition"] == f'attachment; filename="{expected}"'


def test_the_browser_may_read_the_file_name_cross_origin(client, bmw, monkeypatch):
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: b"%PDF")

    response = client.post("/api/exports/pdf/", body(bmw), format="json", HTTP_ORIGIN="http://localhost:5173")

    assert "content-disposition" in response["Access-Control-Expose-Headers"].lower()


def test_running_costs_are_not_called_mandatory(client, bmw, monkeypatch):
    captured = []
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: captured.append(html) or b"%PDF")

    client.post("/api/exports/pdf/", body(bmw), format="json")

    assert RUNNING_COSTS_INTRO == "Yearly running costs (road tax, insurance, maintenance):"
    assert RUNNING_COSTS_INTRO in captured[0]
    assert "andatory" not in captured[0]
