import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.vehicles.models import Brand

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def test_create_and_retrieve_brand(admin_client):
    response = admin_client.post("/api/vehicles/brands/", {"name": "Kia", "tier_code": "5"}, format="json")
    assert response.status_code == status.HTTP_201_CREATED
    assert Brand.objects.filter(name="Kia").exists()


def test_create_brand_requires_admin_role(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    response = client.post("/api/vehicles/brands/", {"name": "Kia", "tier_code": "5"}, format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_duplicate_brand_name_rejected(admin_client):
    Brand.objects.create(name="Kia", tier_code="5")
    response = admin_client.post("/api/vehicles/brands/", {"name": "Kia", "tier_code": "5"}, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- QA audit L14: brand name uniqueness is case-insensitive ----------------


def test_duplicate_brand_name_rejected_case_insensitively(admin_client):
    Brand.objects.create(name="Kia", tier_code="5")
    response = admin_client.post("/api/vehicles/brands/", {"name": "KIA", "tier_code": "5"}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "name" in response.data
    assert Brand.objects.filter(name__iexact="kia").count() == 1


def test_db_level_constraint_also_rejects_a_case_variant(admin_client):
    """Defense in depth: even bypassing the serializer entirely, the DB
    itself refuses a second row differing only by case."""
    from django.db import IntegrityError

    Brand.objects.create(name="Kia", tier_code="5")
    with pytest.raises(IntegrityError):
        Brand.objects.create(name="KIA", tier_code="4")


def test_archive_brand(admin_client):
    brand = Brand.objects.create(name="Kia", tier_code="5")
    response = admin_client.delete(f"/api/vehicles/brands/{brand.id}/")
    assert response.status_code == status.HTTP_204_NO_CONTENT
    brand.refresh_from_db()
    assert brand.is_active is False


# --- QA audit L12: archive is idempotent and bumps updated_at ---------------


def test_archiving_an_already_archived_brand_is_a_no_op(admin_client):
    from apps.audit.models import AuditActionCategory, AuditLog

    brand = Brand.objects.create(name="Kia", tier_code="5")
    first = admin_client.delete(f"/api/vehicles/brands/{brand.id}/")
    assert first.status_code == status.HTTP_204_NO_CONTENT

    second = admin_client.delete(f"/api/vehicles/brands/{brand.id}/")
    assert second.status_code == status.HTTP_204_NO_CONTENT

    assert (
        AuditLog.objects.filter(
            resource_type="vehicles.Brand", resource_id=str(brand.id), action=AuditActionCategory.ARCHIVE
        ).count()
        == 1
    )


def test_archiving_updates_updated_at(admin_client):
    import time

    brand = Brand.objects.create(name="Kia", tier_code="5")
    original_updated_at = brand.updated_at
    time.sleep(0.01)

    admin_client.delete(f"/api/vehicles/brands/{brand.id}/")

    brand.refresh_from_db()
    assert brand.updated_at > original_updated_at


# --- M15: tier_code is constrained to the real 1-5 tier scheme --------------


@pytest.mark.parametrize("tier_code", ["A", "9", "nan", "0", "6"])
def test_invalid_tier_code_is_rejected(admin_client, tier_code):
    response = admin_client.post(
        "/api/vehicles/brands/", {"name": "Kia", "tier_code": tier_code}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Brand.objects.filter(name="Kia").exists()


def test_blank_tier_code_is_accepted_as_not_yet_assigned(admin_client):
    response = admin_client.post("/api/vehicles/brands/", {"name": "Kia", "tier_code": ""}, format="json")
    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.parametrize("tier_code", ["1", "2", "3", "4", "5"])
def test_each_real_tier_code_is_accepted(admin_client, tier_code):
    response = admin_client.post(
        "/api/vehicles/brands/", {"name": f"Brand{tier_code}", "tier_code": tier_code}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED
