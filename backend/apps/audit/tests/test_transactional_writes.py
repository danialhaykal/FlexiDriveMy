"""QA audit H1: the record change and its audit-log write must commit or
roll back together, and a malformed X-Forwarded-For must never crash the
write or leave a committed change with no audit row. Exercised through
apps.vehicles.views.BrandViewSet (AuditedModelViewSet) as a real,
representative admin-audited endpoint.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit import mixins as audit_mixins
from apps.audit.models import AuditLog
from apps.audit.services import get_client_ip
from apps.vehicles.models import Brand

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


# --- get_client_ip: never raises, never returns a malformed value -----------


@pytest.mark.parametrize(
    "forwarded_for",
    ["not-an-ip-at-all!!!", "8.8.8.8; DROP TABLE audit_auditlog;--", "", "   ", "a" * 500],
)
def test_get_client_ip_never_returns_a_malformed_value(rf, forwarded_for):
    request = rf.get("/", HTTP_X_FORWARDED_FOR=forwarded_for, REMOTE_ADDR="127.0.0.1")
    # Malformed X-Forwarded-For falls back to the real REMOTE_ADDR rather
    # than ever returning the malformed value itself.
    assert get_client_ip(request) == "127.0.0.1"


def test_get_client_ip_falls_back_to_none_when_nothing_is_valid(rf):
    request = rf.get("/", HTTP_X_FORWARDED_FOR="garbage", REMOTE_ADDR="also garbage")
    assert get_client_ip(request) is None


def test_get_client_ip_accepts_a_genuinely_spoofed_but_well_formed_ip(rf):
    # A well-formed (if spoofed) IP is still accepted - this fix closes
    # the crash, it doesn't (and can't, without a trusted proxy in front)
    # detect spoofing itself.
    request = rf.get("/", HTTP_X_FORWARDED_FOR="8.8.8.8", REMOTE_ADDR="127.0.0.1")
    assert get_client_ip(request) == "8.8.8.8"


# --- End-to-end: a malformed header never crashes the request, and the
# record change + audit row always commit together ---------------------


def test_malformed_x_forwarded_for_does_not_crash_the_create(admin_client):
    response = admin_client.post(
        "/api/vehicles/brands/",
        {"name": "Kia", "tier_code": "5"},
        format="json",
        HTTP_X_FORWARDED_FOR="not-an-ip-at-all!!!",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert Brand.objects.filter(name="Kia").exists()
    log = AuditLog.objects.get(resource_type="vehicles.Brand", resource_id=str(response.data["id"]))
    # The malformed header is discarded, not stored - falls back to the
    # test client's own REMOTE_ADDR (127.0.0.1) rather than crashing.
    assert log.ip_address == "127.0.0.1"


def test_audit_write_failure_rolls_back_the_record_change_too(admin_client, monkeypatch):
    """Simulates ANY failure writing the audit row (not just a bad IP) -
    the whole transaction must roll back, never leaving a committed
    record change with no audit trail.
    """

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated audit write failure")

    monkeypatch.setattr(audit_mixins, "write_audit_log", _boom)

    with pytest.raises(RuntimeError):
        admin_client.post("/api/vehicles/brands/", {"name": "Kia", "tier_code": "5"}, format="json")

    assert not Brand.objects.filter(name="Kia").exists()


def test_archive_and_its_audit_row_commit_together(admin_client):
    brand = Brand.objects.create(name="Kia", tier_code="B")

    response = admin_client.delete(
        f"/api/vehicles/brands/{brand.id}/", HTTP_X_FORWARDED_FOR="also-not-an-ip"
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    brand.refresh_from_db()
    assert brand.is_active is False
    assert AuditLog.objects.filter(resource_type="vehicles.Brand", resource_id=str(brand.id), action="archive").exists()
