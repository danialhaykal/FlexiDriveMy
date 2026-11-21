import pytest
from django.db import connection
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.db import QueryTimeoutError, run_with_statement_timeout
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


def test_run_with_statement_timeout_returns_result_when_fast():
    assert run_with_statement_timeout(lambda: 1 + 1, timeout_ms=5000) == 2


def test_run_with_statement_timeout_cancels_slow_query():
    def slow_query():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_sleep(0.5)")

    with pytest.raises(QueryTimeoutError):
        run_with_statement_timeout(slow_query, timeout_ms=50)


def test_audit_log_list_returns_504_on_query_timeout(admin_user, monkeypatch):
    from apps.audit import views as audit_views

    def fake_timeout(fn, timeout_ms):
        raise QueryTimeoutError()

    monkeypatch.setattr(audit_views, "run_with_statement_timeout", fake_timeout)

    client = APIClient()
    client.force_authenticate(user=admin_user)
    response = client.get("/api/audit/logs/")

    assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert response.data["detail"] == "Log query timed out. Please specify a narrower date range filter."


def test_audit_log_list_works_normally_without_timeout(admin_user):
    AuditLog.objects.create(action="create", resource_type="vehicles.VehicleModel", resource_id="1")

    client = APIClient()
    client.force_authenticate(user=admin_user)
    response = client.get("/api/audit/logs/")

    assert response.status_code == status.HTTP_200_OK
