"""Run 1 fix batch 4 (UC013): system runtime errors in the audit log.

One "runtime_error" row per unhandled error: never for a 4xx, never with a
stack trace, request body, token, password or environment value, at most one
per (source, error type, path) per 60 seconds, and append-only like every row.
"""

import json

import pytest
from django.core.cache import cache
from django.db import connection, transaction
from django.db import DatabaseError
from rest_framework.test import APIClient

from apps.audit import services
from apps.audit.models import AuditActionCategory, AuditLog
from apps.audit.services import _rate_limit_keys, log_runtime_error
from apps.exports import tasks as export_tasks
from apps.exports.pdf import PDFCompilationTimeoutError
from apps.ml.models import MLTrainingRun, TrainingRunStatus
from apps.ml.tasks import run_training_task
from apps.policy.models import InterestRate
from apps.vehicles.models import BodySegment, Brand, VehicleModel, VehicleSpecDraft, VehicleSpecDraftStatus
from apps.vehicles.tasks import fetch_vehicle_spec_draft

pytestmark = pytest.mark.django_db

AFTER_KEYS = {"error_type", "message", "path", "method", "status", "context"}
SECRET = "hunter2-secret-value"


@pytest.fixture(autouse=True)
def fresh_cache():
    # The rate limit lives in the cache; each test starts with none.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def vehicle():
    brand = Brand.objects.create(name="ErrBrand", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000", is_active=True)
    return VehicleModel.objects.create(
        brand=brand, name="M", trim="X", body_segment=BodySegment.SEDAN, msrp="100000.00",
        engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1498,
    )


@pytest.fixture
def client(regular_user):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(user=regular_user)
    return c


def runtime_rows():
    return AuditLog.objects.filter(action=AuditActionCategory.RUNTIME_ERROR).order_by("pk")


def break_the_comparison(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError(f"comparison blew up: password={SECRET} Authorization: Bearer abc.def.ghi")

    monkeypatch.setattr("apps.comparisons.views.build_comparison", boom)


def comparison(client, vehicle, **overrides):
    params = {"vehicle": vehicle.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "10000.00"}
    params.update(overrides)
    return client.get("/api/comparisons/", params, HTTP_AUTHORIZATION=f"Bearer {SECRET}")


# --- the API -----------------------------------------------------------------------------------------


def test_an_unhandled_api_error_is_a_500_and_one_clean_row(client, vehicle, regular_user, monkeypatch):
    break_the_comparison(monkeypatch)

    response = comparison(client, vehicle)

    assert response.status_code == 500
    rows = runtime_rows()
    assert rows.count() == 1
    row = rows.get()
    assert (row.resource_type, row.resource_id, row.actor_id, row.actor_email) == (
        "system.error", "api", regular_user.pk, regular_user.email)
    assert row.before_data is None
    assert set(row.after_data) == AFTER_KEYS
    assert row.after_data["error_type"] == "RuntimeError"
    assert row.after_data["path"] == "/api/comparisons/"
    assert (row.after_data["method"], row.after_data["status"], row.after_data["context"]) == ("GET", 500, {})
    stored = json.dumps(row.after_data)
    # No secret, token, traceback, query string or request data in the row.
    assert SECRET not in stored and "abc.def.ghi" not in stored
    assert "password=[redacted]" in row.after_data["message"]
    assert "Traceback" not in stored and "File \"" not in stored
    assert "downpayment" not in stored and "tenure_months" not in stored


def test_a_400_writes_no_row(client, vehicle):
    response = comparison(client, vehicle, tenure_months=200)

    assert response.status_code == 400
    assert not runtime_rows().exists()


@pytest.mark.parametrize("path, status", [("/api/comparisons/", 401), ("/api/scenarios/999999/", 404)])
def test_other_handled_errors_write_no_row(path, status, regular_user):
    c = APIClient(raise_request_exception=False)
    if status != 401:
        c.force_authenticate(user=regular_user)

    assert c.get(path).status_code == status
    assert not runtime_rows().exists()


def test_ten_identical_errors_in_a_minute_give_one_row_then_the_count_appears(client, vehicle, monkeypatch):
    break_the_comparison(monkeypatch)

    for _ in range(10):
        assert comparison(client, vehicle).status_code == 500

    assert runtime_rows().count() == 1
    # The 60-second window passes (its cache entry expires) - the next error is
    # written and reports the 9 repeats it stood in for.
    row_key, _ = _rate_limit_keys("api", "RuntimeError", "/api/comparisons/")
    cache.delete(row_key)
    comparison(client, vehicle)

    rows = list(runtime_rows())
    assert len(rows) == 2
    assert rows[1].after_data["context"] == {"suppressed": 9}


def test_a_different_path_or_error_type_is_its_own_row(client, vehicle, monkeypatch):
    break_the_comparison(monkeypatch)
    comparison(client, vehicle)
    monkeypatch.setattr("apps.depreciation.views.build_tco_report", lambda **kw: (_ for _ in ()).throw(KeyError("x")))
    client.get("/api/depreciation/tco/", {"vehicle": vehicle.pk, "tenure_months": 36, "mileage_band": "standard",
                                          "downpayment": "10000.00"})

    assert [(r.after_data["error_type"], r.after_data["path"]) for r in runtime_rows()] == [
        ("RuntimeError", "/api/comparisons/"), ("KeyError", "/api/depreciation/tco/"),
    ]


@pytest.mark.urls("apps.audit.tests.urls_raising")
def test_a_plain_django_view_is_logged_by_the_middleware(regular_user):
    c = APIClient(raise_request_exception=False)
    c.force_login(regular_user)

    assert c.get("/plain-boom/").status_code == 500

    row = runtime_rows().get()
    assert (row.resource_id, row.after_data["path"], row.after_data["error_type"]) == ("web", "/plain-boom/", "RuntimeError")
    assert row.after_data["message"] == "plain view failed (api_key=[redacted])"


# --- background tasks ----------------------------------------------------------------------------------------


def test_a_failed_pdf_export_writes_a_row(client, vehicle, regular_user, monkeypatch):
    def timeout(html, timeout_seconds):
        raise PDFCompilationTimeoutError("PDF compilation exceeded 30s")

    monkeypatch.setattr(export_tasks, "render_pdf_with_timeout", timeout)

    response = client.post("/api/exports/pdf/", {
        "vehicle": vehicle.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "10000.00",
        "chart_svg": "",
    }, format="json")

    assert response.status_code == 504
    row = runtime_rows().get()
    assert (row.resource_id, row.actor_id, row.after_data["status"]) == ("pdf_export", regular_user.pk, 504)
    assert row.after_data["context"]["failure_reason"] == "timeout"


def test_a_failed_training_run_writes_one_row(admin_user):
    run = MLTrainingRun.objects.create(dataset_path="C:/does/not/exist.csv", triggered_by=admin_user)

    with pytest.raises(FileNotFoundError):
        run_training_task(run.pk, actor_id=admin_user.pk)

    run.refresh_from_db()
    assert run.status == TrainingRunStatus.FAILED
    row = runtime_rows().get()
    assert (row.resource_id, row.actor_id, row.after_data["error_type"]) == ("ml_training", admin_user.pk, "FileNotFoundError")
    assert row.after_data["context"] == {"training_run_id": run.pk}


def test_an_error_already_logged_by_a_task_is_not_logged_again_by_the_web_layer(client, vehicle, monkeypatch):
    error = RuntimeError("training failed")
    log_runtime_error(source="ml_training", error=error)

    def reraise(**kwargs):
        raise error

    monkeypatch.setattr("apps.comparisons.views.build_comparison", reraise)
    assert comparison(client, vehicle).status_code == 500

    assert [r.resource_id for r in runtime_rows()] == ["ml_training"]


def test_a_spec_draft_that_crashes_ends_failed_not_pending_and_writes_a_row(admin_user, monkeypatch):
    brand = Brand.objects.create(name="DraftBrand", tier_code="2")
    draft = VehicleSpecDraft.objects.create(
        brand=brand, source_url="https://paultan.org/research/bmw/3-series/", model_name_query="3 Series",
        requested_by=admin_user,
    )

    def crash(url):
        raise RuntimeError(f"browser crashed at https://user:{SECRET}@example.test/")

    monkeypatch.setattr("apps.vehicles.paultan_research.render_research_page", crash)

    fetch_vehicle_spec_draft(draft.pk)  # must not raise

    draft.refresh_from_db()
    assert draft.status == VehicleSpecDraftStatus.FAILED
    assert draft.error_message == (
        "Couldn't fetch the spec page (RuntimeError). Please try again, or fill in the form by hand."
    )
    row = runtime_rows().get()
    assert (row.resource_id, row.actor_id, row.after_data["context"]) == ("spec_draft", admin_user.pk, {"draft_id": draft.pk})
    assert SECRET not in json.dumps(row.after_data)


# --- the helper itself ------------------------------------------------------------------------------------------


def test_the_message_is_cut_to_500_characters():
    row = log_runtime_error(source="api", error=ValueError("x" * 2000))

    assert len(row.after_data["message"]) == 500


def test_the_helper_never_raises_even_if_the_row_cannot_be_written(monkeypatch, caplog):
    def broken(**kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(services, "write_audit_log", broken)

    assert log_runtime_error(source="api", error=ValueError("boom")) is None
    assert "Could not write the runtime-error audit row" in caplog.text


def test_a_runtime_error_row_is_append_only():
    row = log_runtime_error(source="api", error=ValueError("boom"))

    with pytest.raises(ValueError):
        row.save()
    with pytest.raises(ValueError):
        row.delete()
    # The database trigger refuses it too, whoever is connected.
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE audit_auditlog SET resource_id = 'tampered' WHERE id = %s", [row.pk])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM audit_auditlog WHERE id = %s", [row.pk])
    row.refresh_from_db()
    assert row.resource_id == "api"


def test_the_audit_log_api_filters_runtime_errors(admin_user):
    log_runtime_error(source="api", error=ValueError("boom"))
    admin = APIClient()
    admin.force_authenticate(user=admin_user)

    response = admin.get("/api/audit/logs/", {"action": "runtime_error"})

    assert response.status_code == 200
    assert [r["action"] for r in response.data["results"]] == ["runtime_error"]
    assert response.data["results"][0]["after_data"]["error_type"] == "ValueError"
