import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditActionCategory, AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in_admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def test_list_requires_admin_role(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    response = client.get("/api/audit/logs/")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_list_rejects_unauthenticated():
    client = APIClient()
    response = client.get("/api/audit/logs/")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_filter_by_action_category(logged_in_admin_client):
    AuditLog.objects.create(action=AuditActionCategory.CREATE, resource_type="vehicles.VehicleModel", resource_id="1")
    AuditLog.objects.create(action=AuditActionCategory.ARCHIVE, resource_type="vehicles.VehicleModel", resource_id="1")
    AuditLog.objects.create(action=AuditActionCategory.BULK_IMPORT, resource_type="vehicles.VehicleModel", resource_id="2")

    response = logged_in_admin_client.get("/api/audit/logs/", {"action": AuditActionCategory.ARCHIVE})

    assert response.status_code == status.HTTP_200_OK
    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["action"] == AuditActionCategory.ARCHIVE


def test_filter_by_actor(logged_in_admin_client, admin_user, regular_user):
    AuditLog.objects.create(
        actor=admin_user, actor_email=admin_user.email, action=AuditActionCategory.CREATE,
        resource_type="vehicles.Brand", resource_id="1",
    )
    AuditLog.objects.create(
        actor=regular_user, actor_email=regular_user.email, action=AuditActionCategory.CREATE,
        resource_type="vehicles.Brand", resource_id="2",
    )

    response = logged_in_admin_client.get("/api/audit/logs/", {"actor": admin_user.id})

    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["actor_email"] == admin_user.email


# --- Audit batch 6b: filter by the actor's EMAIL, the way an admin thinks of them ----


@pytest.fixture
def two_actors(admin_user, regular_user):
    AuditLog.objects.create(
        actor=admin_user, actor_email=admin_user.email, action=AuditActionCategory.CREATE,
        resource_type="vehicles.Brand", resource_id="1",
    )
    AuditLog.objects.create(
        actor=admin_user, actor_email=admin_user.email, action=AuditActionCategory.UPDATE,
        resource_type="vehicles.Brand", resource_id="1",
    )
    AuditLog.objects.create(
        actor=regular_user, actor_email=regular_user.email, action=AuditActionCategory.CREATE,
        resource_type="vehicles.Brand", resource_id="2",
    )


def test_filter_by_actor_email_matches_that_users_rows(logged_in_admin_client, admin_user, two_actors):
    response = logged_in_admin_client.get("/api/audit/logs/", {"actor_email": admin_user.email})

    assert response.status_code == status.HTTP_200_OK
    results = response.data["results"]
    assert len(results) == 2
    assert {r["actor_email"] for r in results} == {admin_user.email}


def test_filter_by_actor_email_is_case_insensitive(logged_in_admin_client, admin_user, two_actors):
    response = logged_in_admin_client.get("/api/audit/logs/", {"actor_email": admin_user.email.upper()})

    assert len(response.data["results"]) == 2


def test_filter_by_actor_email_ignores_surrounding_spaces(logged_in_admin_client, admin_user, two_actors):
    response = logged_in_admin_client.get("/api/audit/logs/", {"actor_email": f"  {admin_user.email} "})

    assert len(response.data["results"]) == 2


def test_an_email_nobody_used_returns_an_empty_list_not_an_error(logged_in_admin_client, two_actors):
    response = logged_in_admin_client.get("/api/audit/logs/", {"actor_email": "nobody@example.com"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["results"] == [] and response.data["count"] == 0


def test_the_email_must_match_exactly_not_as_a_fragment(logged_in_admin_client, admin_user, two_actors):
    partial = admin_user.email.split("@")[0]

    response = logged_in_admin_client.get("/api/audit/logs/", {"actor_email": partial})

    assert response.data["results"] == []


def test_the_email_filter_still_finds_rows_of_a_deleted_account(logged_in_admin_client, create_user):
    gone = create_user(email="gone@example.com", role="admin")
    AuditLog.objects.create(
        actor=gone, actor_email=gone.email, action=AuditActionCategory.CREATE,
        resource_type="vehicles.Brand", resource_id="9",
    )
    gone.delete()  # the FK is SET_NULL; the row keeps the email it was written with

    response = logged_in_admin_client.get("/api/audit/logs/", {"actor_email": "GONE@example.com"})

    assert [r["actor_email"] for r in response.data["results"]] == ["gone@example.com"]
    assert response.data["results"][0]["actor_id"] is None


def test_the_email_and_id_filters_combine_and_the_id_filter_still_works_alone(
    logged_in_admin_client, admin_user, regular_user, two_actors
):
    by_id = logged_in_admin_client.get("/api/audit/logs/", {"actor": admin_user.id})
    both = logged_in_admin_client.get(
        "/api/audit/logs/", {"actor": admin_user.id, "actor_email": regular_user.email}
    )
    with_action = logged_in_admin_client.get(
        "/api/audit/logs/", {"actor_email": admin_user.email, "action": AuditActionCategory.UPDATE}
    )

    assert len(by_id.data["results"]) == 2  # API callers' existing id filter is unchanged
    assert both.data["results"] == []  # an id and a different user's email can't both hold
    assert len(with_action.data["results"]) == 1


def test_the_email_filter_is_admin_only(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)

    assert client.get("/api/audit/logs/", {"actor_email": regular_user.email}).status_code == status.HTTP_403_FORBIDDEN
    assert APIClient().get("/api/audit/logs/", {"actor_email": "a@b.c"}).status_code == status.HTTP_401_UNAUTHORIZED


def test_filter_by_timestamp_range(logged_in_admin_client, monkeypatch):
    # timestamp is auto_now_add + append-only (the DB trigger blocks any
    # later UPDATE), so an "old" row has to be created with a patched
    # timezone.now() rather than backdated after the fact.
    real_now = timezone.now
    monkeypatch.setattr(timezone, "now", lambda: real_now() - timezone.timedelta(days=30))
    old = AuditLog.objects.create(action=AuditActionCategory.CREATE, resource_type="vehicles.Brand", resource_id="1")

    monkeypatch.setattr(timezone, "now", real_now)
    recent = AuditLog.objects.create(action=AuditActionCategory.CREATE, resource_type="vehicles.Brand", resource_id="2")

    cutoff = (real_now() - timezone.timedelta(days=1)).isoformat()
    response = logged_in_admin_client.get("/api/audit/logs/", {"timestamp_from": cutoff})

    results = response.data["results"]
    ids = [row["id"] for row in results]
    assert recent.pk in ids
    assert old.pk not in ids


def test_filter_by_resource_type(logged_in_admin_client):
    AuditLog.objects.create(action=AuditActionCategory.CREATE, resource_type="policy.InterestRate", resource_id="1")
    AuditLog.objects.create(action=AuditActionCategory.CREATE, resource_type="vehicles.VehicleModel", resource_id="2")

    response = logged_in_admin_client.get("/api/audit/logs/", {"resource_type": "policy.InterestRate"})

    results = response.data["results"]
    assert len(results) == 1
    assert results[0]["resource_type"] == "policy.InterestRate"


# --- M1: bad filter input is a clean 400, never a 500 -----------------------


def test_non_numeric_actor_is_rejected_cleanly(logged_in_admin_client):
    response = logged_in_admin_client.get("/api/audit/logs/", {"actor": "abc"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "actor" in response.data


def test_unknown_action_is_rejected_cleanly(logged_in_admin_client):
    response = logged_in_admin_client.get("/api/audit/logs/", {"action": "nonexistent-action"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "action" in response.data


def test_malformed_timestamp_from_is_rejected_cleanly(logged_in_admin_client):
    response = logged_in_admin_client.get("/api/audit/logs/", {"timestamp_from": "not-a-date"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "timestamp_from" in response.data


def test_malformed_timestamp_to_is_rejected_cleanly(logged_in_admin_client):
    response = logged_in_admin_client.get("/api/audit/logs/", {"timestamp_to": "also-not-a-date"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "timestamp_to" in response.data


def test_timestamp_from_after_timestamp_to_is_rejected_cleanly(logged_in_admin_client):
    response = logged_in_admin_client.get(
        "/api/audit/logs/", {"timestamp_from": "2026-06-01", "timestamp_to": "2026-01-01"}
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "timestamp_from" in response.data


def test_plain_date_only_timestamp_is_accepted(logged_in_admin_client):
    AuditLog.objects.create(action=AuditActionCategory.CREATE, resource_type="vehicles.Brand", resource_id="1")
    response = logged_in_admin_client.get("/api/audit/logs/", {"timestamp_from": "2020-01-01"})
    assert response.status_code == status.HTTP_200_OK


# --- QA audit L12: a date-only timestamp_to must include the whole day -----


def test_date_only_timestamp_to_includes_entries_later_that_same_day(logged_in_admin_client, monkeypatch):
    real_now = timezone.now
    today_at_2pm = real_now().replace(hour=14, minute=30, second=0, microsecond=0)
    monkeypatch.setattr(timezone, "now", lambda: today_at_2pm)
    afternoon_entry = AuditLog.objects.create(
        action=AuditActionCategory.CREATE, resource_type="vehicles.Brand", resource_id="1"
    )
    monkeypatch.setattr(timezone, "now", real_now)

    # A date-only "to" the SAME day - previously parsed as that day's
    # midnight, which would have excluded this 2:30pm entry entirely.
    today_str = today_at_2pm.date().isoformat()
    response = logged_in_admin_client.get("/api/audit/logs/", {"timestamp_to": today_str})

    assert response.status_code == status.HTTP_200_OK
    ids = [row["id"] for row in response.data["results"]]
    assert afternoon_entry.pk in ids


def test_date_only_timestamp_to_still_excludes_the_next_day(logged_in_admin_client, monkeypatch):
    real_now = timezone.now
    tomorrow = real_now() + timezone.timedelta(days=1)
    monkeypatch.setattr(timezone, "now", lambda: tomorrow)
    tomorrows_entry = AuditLog.objects.create(
        action=AuditActionCategory.CREATE, resource_type="vehicles.Brand", resource_id="2"
    )
    monkeypatch.setattr(timezone, "now", real_now)

    today_str = real_now().date().isoformat()
    response = logged_in_admin_client.get("/api/audit/logs/", {"timestamp_to": today_str})

    ids = [row["id"] for row in response.data["results"]]
    assert tomorrows_entry.pk not in ids


def test_retrieve_shows_full_before_after_payload(logged_in_admin_client):
    log = AuditLog.objects.create(
        action=AuditActionCategory.UPDATE,
        resource_type="vehicles.VehicleModel",
        resource_id="1",
        before_data={"msrp": "90000.00"},
        after_data={"msrp": "95000.00"},
    )

    response = logged_in_admin_client.get(f"/api/audit/logs/{log.pk}/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["before_data"] == {"msrp": "90000.00"}
    assert response.data["after_data"] == {"msrp": "95000.00"}
