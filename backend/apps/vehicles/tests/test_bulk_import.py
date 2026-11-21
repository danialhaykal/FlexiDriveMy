import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditActionCategory, AuditLog
from apps.vehicles.models import Brand, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def honda():
    return Brand.objects.create(name="Honda", tier_code="A")


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def csv_file(rows, header=None):
    # Default file: the full column set. Rows given as the original six
    # values get a valid petrol powertrain + cc appended, so these tests
    # keep exercising what they were written for (row errors, encoding,
    # duplicates, audit rows...); the new columns have their own tests in
    # test_vehicle_specs.py.
    default_header = header is None
    header = header or [
        "brand", "name", "trim", "body_segment", "msrp", "engine_capacity_kw", "powertrain", "engine_capacity_cc",
    ]
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(row + ["petrol", "1498"] if default_header and len(row) == 6 else row))
    content = "\n".join(lines).encode("utf-8")
    return SimpleUploadedFile("import.csv", content, content_type="text/csv")


def test_bulk_import_requires_admin_role(honda, regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    upload = csv_file([["Honda", "City", "V", "sedan", "99999.99", "90.00"]])

    response = client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_bulk_import_mixed_valid_and_invalid_rows(admin_client, honda):
    upload = csv_file(
        [
            ["Honda", "City", "V", "sedan", "99999.99", "90.00"],  # row 2: valid
            ["Nissan", "Almera", "E", "sedan", "79000.00", "80.00"],  # row 3: unknown brand
            ["Honda", "CR-V", "TC", "suv", "180000.00", "140.00"],  # row 4: valid
            ["Honda", "Civic", "RS", "sedan", "-5000.00", "100.00"],  # row 5: negative msrp
        ]
    )

    response = admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["total_rows"] == 4
    assert response.data["created_count"] == 2
    assert response.data["error_count"] == 2

    error_rows = {err["row"] for err in response.data["errors"]}
    assert error_rows == {3, 5}

    brand_error = next(err for err in response.data["errors"] if err["row"] == 3)
    assert "not found" in str(brand_error["errors"]["brand"])

    msrp_error = next(err for err in response.data["errors"] if err["row"] == 5)
    assert "positive" in str(msrp_error["errors"]["msrp"]).lower()

    # Only the two valid rows were actually committed.
    assert VehicleModel.objects.count() == 2
    assert VehicleModel.objects.filter(name="City").exists()
    assert VehicleModel.objects.filter(name="CR-V").exists()
    assert not VehicleModel.objects.filter(name="Almera").exists()
    assert not VehicleModel.objects.filter(name="Civic").exists()


def test_bulk_import_rejects_whole_batch_on_missing_required_column(admin_client, honda):
    # No "trim" column at all - a structural error, not a row-level one.
    upload = csv_file(
        [["Honda", "City", "sedan", "99999.99", "90.00", "petrol"]],
        header=["brand", "name", "body_segment", "msrp", "engine_capacity_kw", "powertrain"],
    )

    response = admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "trim" in response.data["detail"]
    # Nothing at all was committed, even though the row content was otherwise fine.
    assert VehicleModel.objects.count() == 0


def test_bulk_import_rejects_unsupported_file_type(admin_client, honda):
    upload = SimpleUploadedFile("import.txt", b"brand,name\nHonda,City", content_type="text/plain")

    response = admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert VehicleModel.objects.count() == 0


def test_bulk_import_requires_a_file(admin_client):
    response = admin_client.post("/api/vehicles/models/bulk_import/", {}, format="multipart")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- M2: never crash, never silently accept nothing -------------------


def test_bulk_import_header_only_file_reports_no_rows_not_a_silent_success(admin_client, honda):
    upload = csv_file([])  # header line only, no data rows

    response = admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "no data rows" in response.data["detail"].lower()


def test_bulk_import_duplicate_row_within_the_same_file_is_a_row_error_not_a_500(admin_client, honda):
    upload = csv_file(
        [
            ["Honda", "City", "V", "sedan", "99999.99", "90.00"],  # row 2
            ["Honda", "City", "V", "sedan", "99999.99", "90.00"],  # row 3: exact duplicate of row 2
            ["Honda", "CR-V", "TC", "suv", "180000.00", "140.00"],  # row 4: valid, unrelated
        ]
    )

    response = admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["created_count"] == 2
    assert response.data["error_count"] == 1
    dup_error = next(err for err in response.data["errors"] if err["row"] == 3)
    assert "duplicated" in str(dup_error["errors"]).lower()
    # The two genuinely distinct rows still committed - a duplicate
    # elsewhere in the batch doesn't sink the whole import.
    assert VehicleModel.objects.filter(name="City").count() == 1
    assert VehicleModel.objects.filter(name="CR-V").count() == 1


def test_bulk_import_accepts_windows_1252_encoded_csv(admin_client):
    # Windows-1252 (Excel's own CSV export default on Windows): a brand
    # name with a non-ASCII, non-UTF-8-valid byte (e9 = 'é' in cp1252,
    # an invalid standalone UTF-8 continuation byte).
    accented_brand = Brand.objects.create(name="Citro\xebn", tier_code="A")
    header = "brand,name,trim,body_segment,msrp,engine_capacity_kw,powertrain,engine_capacity_cc"
    row = f"{accented_brand.name},C3,Feel,hatchback,89999.99,81.00,petrol,1199"
    content = (header + "\n" + row).encode("cp1252")
    upload = SimpleUploadedFile("import.csv", content, content_type="text/csv")

    response = admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["created_count"] == 1
    assert VehicleModel.objects.filter(name="C3", brand=accented_brand).exists()


def test_bulk_import_rejects_corrupt_xlsx_cleanly(admin_client, honda):
    upload = SimpleUploadedFile("import.xlsx", b"this is not a real zip/xlsx file at all", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    response = admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "xlsx" in response.data["detail"].lower()
    assert VehicleModel.objects.count() == 0


def test_bulk_import_header_matching_is_case_insensitive(admin_client, honda):
    upload = csv_file(
        [["Honda", "City", "V", "sedan", "99999.99", "90.00", "petrol", "1498"]],
        header=["Brand", "Name", "Trim", "Body_Segment", "MSRP", "Engine_Capacity_KW", "Powertrain", "Engine_Capacity_CC"],
    )

    response = admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["created_count"] == 1
    assert VehicleModel.objects.filter(name="City").exists()


def test_bulk_import_writes_one_audit_row_per_created_vehicle(admin_client, honda, admin_user):
    upload = csv_file(
        [
            ["Honda", "City", "V", "sedan", "99999.99", "90.00"],
            ["Honda", "CR-V", "TC", "suv", "180000.00", "140.00"],
        ]
    )

    admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    logs = AuditLog.objects.filter(action=AuditActionCategory.BULK_IMPORT, resource_type="vehicles.VehicleModel")
    assert logs.count() == 2
    assert all(log.actor_id == admin_user.id for log in logs)
