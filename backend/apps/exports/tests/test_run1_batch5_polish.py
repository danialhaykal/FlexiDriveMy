"""Run 1 fix batch 5, steps 3-6 (backend side): the catalog's powertrain
phrase, income and DSR limit on the profile, the PDF's wording, the
total-loss month, the ML status wording, both PDF modes, and the non-saloon
source note."""

import importlib
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.test import override_settings
from rest_framework.test import APIClient

from apps.depreciation import inference
from apps.exports import tasks
from apps.exports.models import PDFExportFailureReason, PDFExportJob, PDFExportJobStatus
from apps.exports.storage import save_pdf
from apps.ml.models import MLTrainingRun, ModelType, PredictionTarget, ProductionModel
from apps.policy.mileage import mileage_band_label
from apps.policy.models import InterestRate, RoadTaxCcBand
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


def export_body(vehicle, tenure=36):
    return {"vehicle": vehicle.pk, "tenure_months": tenure, "mileage_band": "standard", "downpayment": "26580.00",
            "chart_svg": ""}


# --- 3.2 catalog cards: the readable powertrain phrase -----------------------------------------------------


@pytest.mark.parametrize("powertrain, cc, phrase", [
    ("mild_hybrid", 1496, "mild hybrid"), ("phev", 1969, "plug-in hybrid"), ("bev", None, "electric"),
    ("", None, ""),
])
def test_the_catalog_sends_the_same_powertrain_phrase_as_the_basis_lines(client, powertrain, cc, phrase):
    brand = Brand.objects.create(name=f"Phrase{powertrain or 'none'}", tier_code="2")
    car = VehicleModel.objects.create(
        brand=brand, name="M", trim="X", body_segment=BodySegment.SEDAN, msrp="200000.00",
        engine_capacity_kw="150.00", powertrain=powertrain, engine_capacity_cc=cc,
    )

    assert client.get(f"/api/vehicles/catalog/{car.pk}/").data["powertrain_phrase"] == phrase


# --- 3.3 income and DSR limit on the profile ------------------------------------------------------------------


PROFILE = {"monthly_budget": "5000.00", "preferred_tenure_months": 48, "annual_mileage_band": "standard",
           "ownership_preference": "retain", "shariah_compliant_required": False}


def test_income_and_dsr_limit_are_saved_and_dsr_defaults_to_60(client):
    default = client.put("/api/profile/financial/", PROFILE, format="json").data
    saved = client.put("/api/profile/financial/", {**PROFILE, "monthly_income": "8000", "max_dsr_percent": "45"},
                       format="json").data

    assert (default["monthly_income"], default["max_dsr_percent"]) == (None, "60.00")
    assert (saved["monthly_income"], saved["max_dsr_percent"]) == ("8000.00", "45.00")


@pytest.mark.parametrize("field, value", [("max_dsr_percent", "0"), ("max_dsr_percent", "101"),
                                          ("monthly_income", "0")])
def test_out_of_range_values_are_refused(client, field, value):
    response = client.put("/api/profile/financial/", {**PROFILE, field: value}, format="json")

    assert response.status_code == 400
    assert field in response.data


def test_a_blank_income_is_saved_as_not_given(client):
    response = client.put("/api/profile/financial/", {**PROFILE, "monthly_income": None}, format="json")

    assert response.status_code in (200, 201)
    assert response.data["monthly_income"] is None


# --- 4.1 PDF wording ---------------------------------------------------------------------------------------------


@pytest.fixture
def captured_html(monkeypatch):
    captured = []
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: captured.append(html) or b"%PDF")
    return captured


def test_the_pdf_uses_the_screens_mileage_wording_and_prints_unavailable_reasons(client, bmw, captured_html):
    response = client.post("/api/exports/pdf/", export_body(bmw, tenure=48), format="json")

    assert response.status_code == 200
    html = captured_html[0]
    # Run 3 fix batch 6: the label comes from the one band definition (was "Standard (up to 20,000 km/year)")
    assert f"Mileage band: {mileage_band_label('standard')}" in html
    assert "Mileage band: Standard — 10,001 to 15,000 km/year" in html
    # Subscription isn't offered at 48 months: its reason, not three blank cells.
    assert "Not available: Subscription plans run for 12, 24 or 36 months." in html
    # The TCO table's unavailable row has no horizon line.
    assert "over 48 months, car returned" in html  # GFV hand-back IS available
    assert html.count("over 48 months, car returned") == 1


# --- 4.2 total-loss month 0 ----------------------------------------------------------------------------------------


def test_loss_month_0_is_refused_with_the_range(client, bmw):
    response = client.get("/api/depreciation/total-loss-sandbox/", {
        "vehicle": bmw.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "26580.00",
        "loss_month": 0,
    })

    assert response.status_code == 400
    assert response.data["loss_month"] == ["Choose a month from 1 to 36."]


# --- 4.4 ML status wording ------------------------------------------------------------------------------------------


def deploy_run(target):
    run = MLTrainingRun.objects.create(status="succeeded", rf_r2=0.89, rf_mae=15000.0, gb_r2=0.88, gb_mae=16000.0,
                                       deployed=True, deployed_model_type=ModelType.RANDOM_FOREST)
    production = ProductionModel.get_singleton()
    production.training_run = run
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = "C:/models/run.joblib"
    production.prediction_target = target
    production.r2_score = 0.89
    production.save()
    return run


def test_a_raw_price_model_on_record_reads_as_switched_off_to_the_buyer(client, bmw):
    deploy_run(PredictionTarget.RAW_RESALE_PRICE)

    data = client.get("/api/depreciation/tco/", {
        "vehicle": bmw.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "26580.00",
    }).data

    assert data["model_degraded"] is True
    assert data["degraded_reason"] == (
        "Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast is "
        "switched off until a model passes the accuracy check."
    )
    assert "no trained model is deployed" not in data["degraded_reason"]


def test_the_ml_page_says_why_the_deployed_run_is_not_used(admin_user):
    run = deploy_run(PredictionTarget.RAW_RESALE_PRICE)
    other = MLTrainingRun.objects.create(status="succeeded", rf_r2=0.6, gb_r2=0.61)
    admin = APIClient()
    admin.force_authenticate(user=admin_user)

    runs = {r["id"]: r for r in admin.get("/api/ml/training-runs/").data["results"]}

    # ML batch 1: the forecast now needs the log resale-price model.
    assert runs[run.pk]["serving_note"] == (
        f"Run {run.pk} is marked deployed but is not used: it predicts raw prices, and the forecast now needs "
        "the resale-price model (log scale)."
    )
    assert runs[other.pk]["serving_note"] is None


def test_no_serving_note_once_a_log_price_model_is_deployed(admin_user):
    run = deploy_run(PredictionTarget.LOG_RESALE_PRICE)
    admin = APIClient()
    admin.force_authenticate(user=admin_user)

    runs = {r["id"]: r for r in admin.get("/api/ml/training-runs/").data["results"]}

    assert runs[run.pk]["serving_note"] is None
    assert inference.forecast_is_switched_off() is False


# --- 5 both PDF modes ---------------------------------------------------------------------------------------------


def test_eager_mode_still_streams_the_pdf_back(client, bmw, captured_html):
    response = client.post("/api/exports/pdf/", export_body(bmw), format="json")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content == b"%PDF"


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_with_a_real_worker_the_export_is_queued_polled_and_downloaded(client, bmw, monkeypatch, regular_user):
    # The worker hasn't picked the task up yet: .delay() only queues it.
    monkeypatch.setattr(tasks.generate_pdf_task, "delay", lambda *args, **kwargs: None)

    queued = client.post("/api/exports/pdf/", export_body(bmw), format="json")

    assert queued.status_code == 202
    job_id = queued.data["job_id"]
    assert queued.data["status"] == "pending"
    assert client.get(f"/api/exports/pdf/{job_id}/").data == {"job_id": job_id, "status": "pending", "detail": None}
    assert client.get(f"/api/exports/pdf/{job_id}/download/").status_code == 409

    # The worker finishes it.
    job = PDFExportJob.objects.get(pk=job_id)
    job.file_path = save_pdf(b"%PDF-1.7 from the worker", job.pk)
    job.status = PDFExportJobStatus.SUCCEEDED
    job.save()

    assert client.get(f"/api/exports/pdf/{job_id}/").data["status"] == "succeeded"
    download = client.get(f"/api/exports/pdf/{job_id}/download/")
    assert download.status_code == 200
    assert download["Content-Type"] == "application/pdf"
    assert download.content == b"%PDF-1.7 from the worker"


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_a_failed_queued_job_reports_its_own_message(client, regular_user):
    job = PDFExportJob.objects.create(
        user=regular_user, status=PDFExportJobStatus.FAILED, failure_reason=PDFExportFailureReason.TIMEOUT,
        error_message="PDF generation timed out. Please try downloading again.",
    )

    status_body = client.get(f"/api/exports/pdf/{job.pk}/").data
    download = client.get(f"/api/exports/pdf/{job.pk}/download/")

    assert status_body == {"job_id": job.pk, "status": "failed",
                           "detail": "PDF generation timed out. Please try downloading again."}
    assert download.status_code == 504
    assert download.data["detail"] == "PDF generation timed out. Please try downloading again."


def test_another_users_job_is_a_404(regular_user, create_user):
    job = PDFExportJob.objects.create(user=regular_user, status=PDFExportJobStatus.SUCCEEDED)
    intruder = APIClient()
    intruder.force_authenticate(user=create_user(email="intruder@example.com"))

    assert intruder.get(f"/api/exports/pdf/{job.pk}/").status_code == 404
    assert intruder.get(f"/api/exports/pdf/{job.pk}/download/").status_code == 404


# --- 6.3 the non-saloon source note ---------------------------------------------------------------------------------


def test_the_non_saloon_rows_say_the_effective_date_is_assumed_and_no_rate_moved():
    rows = RoadTaxCcBand.objects.filter(vehicle_class="non_saloon", is_active=True)

    assert rows.count() == 9
    for row in rows:
        assert row.source_note.endswith(
            "Effective date not stated by the source; 1 Jan 2007 assumed to match the saloon table."
        )
        assert "StashAway" in row.source_note
    assert rows.get(min_cc=1801).base_amount == Decimal("360.00")
    assert rows.get(min_cc=1801).per_cc_rate == Decimal("0.40")
