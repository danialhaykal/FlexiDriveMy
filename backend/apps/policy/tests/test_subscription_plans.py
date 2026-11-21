"""Batch 6A: SubscriptionPlanViewSet CRUD + archive + the one-active-
per-vehicle uniqueness guard (a clean 400, not a raw IntegrityError)."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import SubscriptionPlan
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def vehicle():
    brand = Brand.objects.create(name="Toyota", tier_code="1")
    return VehicleModel.objects.create(
        brand=brand, name="Alphard", trim="2.5L", body_segment=BodySegment.MPV,
        msrp="349900.00", engine_capacity_kw="140.00",
    )


def plan_payload(vehicle, **overrides):
    payload = {
        "vehicle": vehicle.id,
        "fee_monthly": "3500.00",
        "insurance_annual": "3600.00",
        "road_tax_annual": "600.00",
        "maintenance_annual": "1800.00",
    }
    payload.update(overrides)
    return payload


def test_create_and_retrieve(admin_client, vehicle):
    response = admin_client.post("/api/policy/subscription-plans/", plan_payload(vehicle), format="json")
    assert response.status_code == status.HTTP_201_CREATED
    assert SubscriptionPlan.objects.filter(vehicle=vehicle).exists()
    assert response.data["vehicle_label"] == "Toyota Alphard 2.5L"


def test_create_requires_admin_role(regular_user, vehicle):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    response = client.post("/api/policy/subscription-plans/", plan_payload(vehicle), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_rejects_a_second_active_plan_for_the_same_vehicle_with_a_clean_400(admin_client, vehicle):
    admin_client.post("/api/policy/subscription-plans/", plan_payload(vehicle), format="json")

    response = admin_client.post("/api/policy/subscription-plans/", plan_payload(vehicle), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "vehicle" in response.data
    assert SubscriptionPlan.objects.filter(vehicle=vehicle, is_active=True).count() == 1


def test_archiving_then_creating_a_replacement_succeeds(admin_client, vehicle):
    first = admin_client.post("/api/policy/subscription-plans/", plan_payload(vehicle), format="json")
    plan_id = first.data["id"]

    archive_response = admin_client.delete(f"/api/policy/subscription-plans/{plan_id}/")
    assert archive_response.status_code == status.HTTP_204_NO_CONTENT

    replacement = admin_client.post(
        "/api/policy/subscription-plans/", plan_payload(vehicle, fee_monthly="4000.00"), format="json"
    )
    assert replacement.status_code == status.HTTP_201_CREATED
    assert SubscriptionPlan.objects.filter(vehicle=vehicle, is_active=True).count() == 1
    assert SubscriptionPlan.objects.filter(vehicle=vehicle).count() == 2


def test_archive_is_soft_delete_not_hard_delete(admin_client, vehicle):
    created = admin_client.post("/api/policy/subscription-plans/", plan_payload(vehicle), format="json")
    plan_id = created.data["id"]

    response = admin_client.delete(f"/api/policy/subscription-plans/{plan_id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    plan = SubscriptionPlan.objects.get(pk=plan_id)
    assert plan.is_active is False  # still exists, just archived
