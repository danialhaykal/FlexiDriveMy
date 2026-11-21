"""Run 3 fix batch 5 (F-30b): the Audit Log's "Resource type" filter matches any
letter case and the short form an admin types - "InterestRate", "interestrate" or
"policy.interestrate" all find "policy.InterestRate" rows - without matching a
different type that merely ends the same way."""

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditActionCategory, AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(admin_user):
    c = APIClient()
    c.force_authenticate(user=admin_user)
    return c


@pytest.fixture
def rows(admin_user):
    def row(resource_type, resource_id):
        return AuditLog.objects.create(actor=admin_user, actor_email=admin_user.email, action=AuditActionCategory.UPDATE,
                                       resource_type=resource_type, resource_id=resource_id)
    return {
        "rate": row("policy.InterestRate", "1"),
        "car": row("vehicles.VehicleModel", "5"),
        "brand": row("vehicles.Brand", "2"),
        "error": row("system.error", "api"),
    }


def found(client, value):
    response = client.get("/api/audit/logs/", {"resource_type": value})
    assert response.status_code == 200, response.data
    return {r["resource_type"] for r in response.data["results"]}


@pytest.mark.parametrize("value", ["policy.InterestRate", "policy.interestrate", "POLICY.INTERESTRATE", "InterestRate",
                                   "interestrate", " interestrate "])
def test_any_case_and_the_short_form_find_the_rows(client, rows, value):
    assert found(client, value) == {"policy.InterestRate"}


def test_vehiclemodel_does_not_also_match_brand(client, rows):
    assert found(client, "vehiclemodel") == {"vehicles.VehicleModel"}
    assert found(client, "vehicles.vehiclemodel") == {"vehicles.VehicleModel"}


def test_the_runtime_error_rows_by_short_form(client, rows):
    assert found(client, "error") == {"system.error"}


def test_an_unknown_type_is_an_empty_result_not_an_error(client, rows):
    assert found(client, "nosuchthing") == set()


def test_a_partial_word_is_not_a_match(client, rows):
    assert found(client, "rate") == set()
