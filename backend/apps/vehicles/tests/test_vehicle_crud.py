import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditActionCategory, AuditLog
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def brand():
    return Brand.objects.create(name="Honda", tier_code="A")


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def valid_payload(brand, **overrides):
    payload = {
        "brand": brand.id,
        "name": "City",
        "trim": "V",
        "body_segment": BodySegment.SEDAN,
        "msrp": "99999.99",
        "engine_capacity_kw": "90.00",
        # New-vehicle contract: powertrain + cc (see test_vehicle_specs.py).
        "powertrain": "petrol",
        "engine_capacity_cc": 1498,
    }
    payload.update(overrides)
    return payload


# --- Role-based access (UC010 Rule 1) ---------------------------------------


def test_create_requires_admin_role(brand, regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    response = client.post("/api/vehicles/models/", valid_payload(brand), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_list_rejects_unauthenticated(brand):
    client = APIClient()
    response = client.get("/api/vehicles/models/")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Single-entry CRUD (UC010 main flow) ------------------------------------


def test_create_vehicle_succeeds(admin_client, brand):
    response = admin_client.post("/api/vehicles/models/", valid_payload(brand), format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert VehicleModel.objects.filter(brand=brand, name="City", trim="V").exists()
    assert response.data["brand_name"] == "Honda"


def test_list_and_retrieve_vehicle(admin_client, brand):
    create_response = admin_client.post("/api/vehicles/models/", valid_payload(brand), format="json")
    vehicle_id = create_response.data["id"]

    list_response = admin_client.get("/api/vehicles/models/")
    assert list_response.status_code == status.HTTP_200_OK
    assert list_response.data["count"] == 1

    detail_response = admin_client.get(f"/api/vehicles/models/{vehicle_id}/")
    assert detail_response.status_code == status.HTTP_200_OK
    assert detail_response.data["name"] == "City"


def test_update_vehicle_msrp(admin_client, brand):
    create_response = admin_client.post("/api/vehicles/models/", valid_payload(brand), format="json")
    vehicle_id = create_response.data["id"]

    response = admin_client.patch(f"/api/vehicles/models/{vehicle_id}/", {"msrp": "105000.00"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["msrp"] == "105000.00"


# --- Missing/invalid-value validation flow (UC010 alt flow 4.1-4.3) ---------


def test_create_rejects_negative_msrp_and_preserves_other_fields(admin_client, brand):
    payload = valid_payload(brand, msrp="-500.00")

    response = admin_client.post("/api/vehicles/models/", payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "msrp" in response.data
    assert "MSRP must be a positive numeric value." in str(response.data["msrp"])
    # Only the offending field is flagged; nothing else is rejected.
    assert "name" not in response.data
    assert "trim" not in response.data
    assert "engine_capacity_kw" not in response.data
    # No partial/corrupt row was created.
    assert not VehicleModel.objects.filter(brand=brand, name="City").exists()


def test_create_rejects_out_of_range_engine_capacity(admin_client, brand):
    payload = valid_payload(brand, engine_capacity_kw="9999.00")

    response = admin_client.post("/api/vehicles/models/", payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Power output must be between 0.10 kW and 700.00 kW." in str(response.data["engine_capacity_kw"])
    assert not VehicleModel.objects.filter(brand=brand).exists()


# --- QA audit L13: ceiling raised to admit real in-scope cars ---------------


def test_create_accepts_a_bmw_m5_real_engine_capacity(admin_client, brand):
    payload = valid_payload(brand, engine_capacity_kw="535.00")

    response = admin_client.post("/api/vehicles/models/", payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED


def test_create_accepts_a_porsche_taycan_turbo_s_real_engine_capacity(admin_client, brand):
    payload = valid_payload(brand, engine_capacity_kw="560.00")

    response = admin_client.post("/api/vehicles/models/", payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED


# --- QA audit L11: msrp gets a sane upper bound -----------------------------


def test_create_rejects_an_msrp_past_the_new_ceiling(admin_client, brand):
    payload = valid_payload(brand, msrp="100000000.01")

    response = admin_client.post("/api/vehicles/models/", payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "MSRP must be between RM0.01 and RM100,000,000.00." in str(response.data["msrp"])
    assert not VehicleModel.objects.filter(brand=brand).exists()


def test_create_accepts_an_msrp_exactly_at_the_new_ceiling(admin_client, brand):
    payload = valid_payload(brand, msrp="100000000.00")

    response = admin_client.post("/api/vehicles/models/", payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED


def test_create_rejects_missing_mandatory_field(admin_client, brand):
    payload = valid_payload(brand)
    del payload["trim"]

    response = admin_client.post("/api/vehicles/models/", payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "trim" in response.data
    assert not VehicleModel.objects.filter(brand=brand).exists()


def test_create_rejects_non_numeric_msrp(admin_client, brand):
    payload = valid_payload(brand, msrp="not-a-number")

    response = admin_client.post("/api/vehicles/models/", payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "msrp" in response.data


# --- Archive, not hard delete (UC010 alt flow, Rule 2) ----------------------


def test_delete_archives_instead_of_hard_deleting(admin_client, brand):
    create_response = admin_client.post("/api/vehicles/models/", valid_payload(brand), format="json")
    vehicle_id = create_response.data["id"]

    response = admin_client.delete(f"/api/vehicles/models/{vehicle_id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    vehicle = VehicleModel.objects.get(pk=vehicle_id)
    assert vehicle.is_active is False  # still exists, just archived


def test_archived_vehicle_excluded_from_default_list(admin_client, brand):
    create_response = admin_client.post("/api/vehicles/models/", valid_payload(brand), format="json")
    vehicle_id = create_response.data["id"]
    admin_client.delete(f"/api/vehicles/models/{vehicle_id}/")

    default_list = admin_client.get("/api/vehicles/models/")
    assert default_list.data["count"] == 0

    with_archived = admin_client.get("/api/vehicles/models/", {"include_archived": "true"})
    assert with_archived.data["count"] == 1


# --- F013 integration: F010 actions must write audit rows ------------------


def test_create_writes_audit_log(admin_client, brand, admin_user):
    response = admin_client.post("/api/vehicles/models/", valid_payload(brand), format="json")
    vehicle_id = response.data["id"]

    log = AuditLog.objects.get(action=AuditActionCategory.CREATE, resource_type="vehicles.VehicleModel", resource_id=str(vehicle_id))
    assert log.actor_id == admin_user.id
    assert log.before_data is None
    assert log.after_data["name"] == "City"


def test_update_writes_audit_log_with_before_and_after(admin_client, brand):
    create_response = admin_client.post("/api/vehicles/models/", valid_payload(brand), format="json")
    vehicle_id = create_response.data["id"]

    admin_client.patch(f"/api/vehicles/models/{vehicle_id}/", {"msrp": "105000.00"}, format="json")

    log = AuditLog.objects.get(action=AuditActionCategory.UPDATE, resource_type="vehicles.VehicleModel", resource_id=str(vehicle_id))
    assert log.before_data["msrp"] == "99999.99"
    assert log.after_data["msrp"] == "105000.00"


def test_archive_writes_audit_log(admin_client, brand):
    create_response = admin_client.post("/api/vehicles/models/", valid_payload(brand), format="json")
    vehicle_id = create_response.data["id"]

    admin_client.delete(f"/api/vehicles/models/{vehicle_id}/")

    log = AuditLog.objects.get(action=AuditActionCategory.ARCHIVE, resource_type="vehicles.VehicleModel", resource_id=str(vehicle_id))
    assert log.before_data["is_active"] is True
    assert log.after_data["is_active"] is False


# --- Archived brands: no new vehicles under one, but an edit may keep its own

ARCHIVED_BRAND_MESSAGE = "Brand is archived and cannot be assigned to new vehicles."


@pytest.fixture
def archived_brand():
    return Brand.objects.create(name="Perodua", tier_code="5", is_active=False)


def test_create_with_an_archived_brand_is_rejected(admin_client, archived_brand):
    response = admin_client.post("/api/vehicles/models/", valid_payload(archived_brand), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["brand"] == [ARCHIVED_BRAND_MESSAGE]
    assert not VehicleModel.objects.filter(brand=archived_brand).exists()


def test_editing_a_vehicle_may_keep_its_own_brand_after_that_brand_was_archived(admin_client, brand):
    vehicle_id = admin_client.post("/api/vehicles/models/", valid_payload(brand), format="json").data["id"]
    Brand.objects.filter(pk=brand.pk).update(is_active=False)

    response = admin_client.put(
        f"/api/vehicles/models/{vehicle_id}/", valid_payload(brand, msrp="105000.00"), format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    vehicle = VehicleModel.objects.get(pk=vehicle_id)
    assert vehicle.brand_id == brand.pk
    assert str(vehicle.msrp) == "105000.00"


def test_editing_a_vehicle_cannot_switch_it_to_a_different_archived_brand(admin_client, brand, archived_brand):
    vehicle_id = admin_client.post("/api/vehicles/models/", valid_payload(brand), format="json").data["id"]

    response = admin_client.put(
        f"/api/vehicles/models/{vehicle_id}/", valid_payload(archived_brand), format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["brand"] == [ARCHIVED_BRAND_MESSAGE]
    assert VehicleModel.objects.get(pk=vehicle_id).brand_id == brand.pk


def test_bulk_import_still_rejects_a_row_under_an_archived_brand(admin_client, archived_brand):
    csv = (
        "brand,name,trim,body_segment,msrp,engine_capacity_kw,powertrain,engine_capacity_cc\n"
        f"{archived_brand.name},Myvi,AV,hatchback,60000.00,70.00,petrol,1496\n"
    )
    upload = SimpleUploadedFile("fleet.csv", csv.encode(), content_type="text/csv")

    response = admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    # Rejected even before the serializer: the importer's brand-name lookup
    # (imports.normalize_row) only resolves active brands.
    assert response.status_code == status.HTTP_200_OK
    assert response.data["created_count"] == 0
    assert response.data["errors"][0]["errors"]["brand"] == ["Brand 'Perodua' not found or inactive."]
    assert not VehicleModel.objects.filter(brand=archived_brand).exists()
