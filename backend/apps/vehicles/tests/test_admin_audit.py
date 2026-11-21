"""QA audit H3: Django admin must not bypass the same rules the API
enforces for this data - no hard delete (cascading to dependent
SubscriptionPlan rows), and every create/update/archive through admin
must write an audit row, same as apps.audit.mixins.AuditedModelViewSet
already does for the API.
"""

import pytest
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.policy.models import SubscriptionPlan
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_django_client(django_user_model):
    user = django_user_model.objects.create_superuser(email="superadmin@example.com", password="pw")
    client = Client()
    client.force_login(user)
    return client, user


@pytest.fixture
def vehicle_with_subscription_plan():
    brand = Brand.objects.create(name="AdminTestBrand", tier_code="A")
    vehicle = VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00",
    )
    SubscriptionPlan.objects.create(
        vehicle=vehicle, fee_monthly="1000.00", insurance_annual="2000.00",
        road_tax_annual="500.00", maintenance_annual="800.00",
    )
    return vehicle


def test_vehicle_with_active_subscription_plan_cannot_be_hard_deleted_via_admin(
    admin_django_client, vehicle_with_subscription_plan
):
    client, _ = admin_django_client
    vehicle = vehicle_with_subscription_plan

    delete_url = reverse("admin:vehicles_vehiclemodel_delete", args=[vehicle.pk])
    response = client.post(delete_url, {"post": "yes"})

    # has_delete_permission() = False means Django admin refuses the
    # delete outright (403), rather than ever cascading into
    # SubscriptionPlan.
    assert response.status_code == 403
    assert VehicleModel.objects.filter(pk=vehicle.pk).exists()
    assert SubscriptionPlan.objects.filter(vehicle=vehicle).exists()


def test_bulk_delete_action_is_not_offered_in_admin(admin_django_client, vehicle_with_subscription_plan):
    client, _ = admin_django_client
    changelist_url = reverse("admin:vehicles_vehiclemodel_changelist")

    response = client.get(changelist_url)

    assert response.status_code == 200
    assert b"delete_selected" not in response.content
    assert b"Archive selected" in response.content


def test_archive_action_soft_deletes_and_writes_an_audit_row(admin_django_client, vehicle_with_subscription_plan):
    client, _ = admin_django_client
    vehicle = vehicle_with_subscription_plan
    changelist_url = reverse("admin:vehicles_vehiclemodel_changelist")

    response = client.post(
        changelist_url,
        {"action": "archive_selected", "_selected_action": [str(vehicle.pk)]},
        follow=True,
    )

    assert response.status_code == 200
    vehicle.refresh_from_db()
    assert vehicle.is_active is False
    # Dependent row is untouched - still exists, just as the API's own
    # archive path leaves it.
    assert SubscriptionPlan.objects.filter(vehicle=vehicle).exists()
    log = AuditLog.objects.get(resource_type="vehicles.VehicleModel", resource_id=str(vehicle.pk), action="archive")
    assert log.actor_email == "superadmin@example.com"


def test_unarchive_action_restores_an_archived_vehicle_and_writes_an_audit_row(
    admin_django_client, vehicle_with_subscription_plan
):
    client, _ = admin_django_client
    vehicle = vehicle_with_subscription_plan
    vehicle.is_active = False
    vehicle.save(update_fields=["is_active"])
    changelist_url = reverse("admin:vehicles_vehiclemodel_changelist")

    response = client.post(
        changelist_url,
        {"action": "unarchive_selected", "_selected_action": [str(vehicle.pk)]},
        follow=True,
    )

    assert response.status_code == 200
    vehicle.refresh_from_db()
    assert vehicle.is_active is True
    assert AuditLog.objects.filter(
        resource_type="vehicles.VehicleModel", resource_id=str(vehicle.pk), action="update"
    ).exists()


def test_creating_a_brand_via_admin_writes_an_audit_row(admin_django_client):
    client, _ = admin_django_client
    add_url = reverse("admin:vehicles_brand_add")

    response = client.post(add_url, {"name": "AdminCreatedBrand", "tier_code": "5", "is_active": "on"})

    assert response.status_code == 302  # redirect on success
    brand = Brand.objects.get(name="AdminCreatedBrand")
    log = AuditLog.objects.get(resource_type="vehicles.Brand", resource_id=str(brand.pk), action="create")
    assert log.after_data["name"] == "AdminCreatedBrand"


def test_editing_a_brand_via_admin_writes_an_audit_row_with_before_and_after(admin_django_client):
    client, _ = admin_django_client
    brand = Brand.objects.create(name="OldName", tier_code="5")
    change_url = reverse("admin:vehicles_brand_change", args=[brand.pk])

    response = client.post(change_url, {"name": "NewName", "tier_code": "5", "is_active": "on"})

    assert response.status_code == 302
    log = AuditLog.objects.get(resource_type="vehicles.Brand", resource_id=str(brand.pk), action="update")
    assert log.before_data["name"] == "OldName"
    assert log.after_data["name"] == "NewName"
