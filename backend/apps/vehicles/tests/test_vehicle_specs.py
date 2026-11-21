"""The new-vehicle contract (audit batch 1, see the project spec): every way of
creating a vehicle - the API/Fleet form, bulk import, Django admin - ends up
with the same rules:

  - powertrain is required
  - engine_capacity_cc is required for every powertrain except BEV, and must
    be empty for BEV
  - engine_capacity_kw stays required and now means POWER OUTPUT in kW

The rule lives in apps.vehicles.models.powertrain_spec_errors and is applied
by VehicleModelSerializer (API + bulk import), VehicleModel.clean() (Django
admin) and, for the one part old rows can't violate, a DB CheckConstraint.
Rows that predate the contract stay readable, flagged spec_complete=False.
"""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

URL = "/api/vehicles/models/"


@pytest.fixture
def brand():
    return Brand.objects.create(name="BMW", tier_code="2")


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def payload(brand, **overrides):
    data = {
        "brand": brand.id, "name": "3 Series", "trim": "320i Sport", "body_segment": BodySegment.SEDAN,
        "msrp": "265800.00", "engine_capacity_kw": "135.00", "powertrain": "petrol", "engine_capacity_cc": 1998,
    }
    data.update(overrides)
    return data


def legacy_vehicle(brand, **overrides):
    """A row entered before the contract existed: no powertrain, no cc."""
    fields = dict(
        brand=brand, name="XC60", trim="B5 Core", body_segment=BodySegment.SUV,
        msrp="328888.00", engine_capacity_kw="180.93",
    )
    fields.update(overrides)
    return VehicleModel.objects.create(**fields)


# --- serializer (API and the Fleet form) ----------------------------------------


def test_a_complete_petrol_vehicle_is_accepted_and_reports_spec_complete(admin_client, brand):
    response = admin_client.post(URL, payload(brand), format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["powertrain"] == "petrol"
    assert response.data["engine_capacity_cc"] == 1998
    assert response.data["spec_complete"] is True
    # The legacy field keeps its name and API key (power output in kW).
    assert response.data["engine_capacity_kw"] == "135.00"


def test_petrol_without_cc_is_rejected(admin_client, brand):
    data = payload(brand)
    del data["engine_capacity_cc"]

    response = admin_client.post(URL, data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "engine_capacity_cc" in response.data
    assert not VehicleModel.objects.exists()


def test_petrol_with_a_null_cc_is_rejected(admin_client, brand):
    response = admin_client.post(URL, payload(brand, engine_capacity_cc=None), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "engine_capacity_cc" in response.data


def test_bev_with_cc_is_rejected(admin_client, brand):
    response = admin_client.post(URL, payload(brand, powertrain="bev", engine_capacity_cc=1000), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "leave this empty" in str(response.data["engine_capacity_cc"])


def test_bev_without_cc_is_accepted(admin_client, brand):
    data = payload(brand, powertrain="bev", name="Macan Electric", trim="RWD")
    del data["engine_capacity_cc"]

    response = admin_client.post(URL, data, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["engine_capacity_cc"] is None
    assert response.data["spec_complete"] is True


@pytest.mark.parametrize("cc", [599, 8001, 0])
def test_cc_out_of_range_is_rejected(admin_client, brand, cc):
    response = admin_client.post(URL, payload(brand, engine_capacity_cc=cc), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Engine capacity must be between 600 cc and 8,000 cc." in str(response.data["engine_capacity_cc"])


@pytest.mark.parametrize("cc", [600, 8000])
def test_cc_boundaries_are_accepted(admin_client, brand, cc):
    response = admin_client.post(URL, payload(brand, engine_capacity_cc=cc), format="json")

    assert response.status_code == status.HTTP_201_CREATED


def test_missing_powertrain_is_rejected(admin_client, brand):
    data = payload(brand)
    del data["powertrain"]

    response = admin_client.post(URL, data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["powertrain"] == ["Powertrain is required."]


def test_blank_powertrain_is_rejected(admin_client, brand):
    response = admin_client.post(URL, payload(brand, powertrain=""), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "powertrain" in response.data


def test_an_unknown_powertrain_is_rejected(admin_client, brand):
    response = admin_client.post(URL, payload(brand, powertrain="steam"), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "powertrain" in response.data


@pytest.mark.parametrize("powertrain", ["petrol", "diesel", "mild_hybrid", "hybrid", "phev"])
def test_every_non_bev_powertrain_requires_cc(admin_client, brand, powertrain):
    ok = admin_client.post(URL, payload(brand, powertrain=powertrain), format="json")
    assert ok.status_code == status.HTTP_201_CREATED

    missing = payload(brand, powertrain=powertrain, trim="other")
    del missing["engine_capacity_cc"]
    assert admin_client.post(URL, missing, format="json").status_code == status.HTTP_400_BAD_REQUEST


def test_power_output_message_no_longer_says_engine_capacity(admin_client, brand):
    response = admin_client.post(URL, payload(brand, engine_capacity_kw="9999.00"), format="json")

    assert "Power output must be between 0.10 kW and 700.00 kW." in str(response.data["engine_capacity_kw"])


# --- legacy rows: readable, flagged, never guessed ------------------------------------


def test_a_legacy_row_stays_readable_and_is_flagged_not_guessed(admin_client, brand):
    vehicle = legacy_vehicle(brand)

    detail = admin_client.get(f"{URL}{vehicle.pk}/")

    assert detail.status_code == status.HTTP_200_OK
    assert detail.data["spec_complete"] is False
    assert detail.data["powertrain"] == ""
    assert detail.data["engine_capacity_cc"] is None
    assert vehicle.spec_complete is False


def test_updating_a_legacy_row_must_complete_its_specs_and_then_succeeds(admin_client, brand):
    vehicle = legacy_vehicle(brand)

    rejected = admin_client.patch(f"{URL}{vehicle.pk}/", {"msrp": "330000.00"}, format="json")
    assert rejected.status_code == status.HTTP_400_BAD_REQUEST
    assert rejected.data["powertrain"] == ["Powertrain is required."]

    completed = admin_client.patch(
        f"{URL}{vehicle.pk}/", {"powertrain": "mild_hybrid", "engine_capacity_cc": 1969}, format="json"
    )
    assert completed.status_code == status.HTTP_200_OK
    assert completed.data["spec_complete"] is True


def test_a_patch_is_judged_on_the_rows_effective_specs(admin_client, brand):
    vehicle = VehicleModel.objects.create(
        brand=brand, name="X", trim="Y", body_segment=BodySegment.SEDAN, msrp="100000.00",
        engine_capacity_kw="100.00", powertrain="petrol", engine_capacity_cc=1998,
    )

    # Switching to BEV without clearing cc leaves cc set -> rejected ...
    assert admin_client.patch(f"{URL}{vehicle.pk}/", {"powertrain": "bev"}, format="json").status_code == 400
    # ... clearing it in the same request is fine.
    ok = admin_client.patch(
        f"{URL}{vehicle.pk}/", {"powertrain": "bev", "engine_capacity_cc": None}, format="json"
    )
    assert ok.status_code == status.HTTP_200_OK


def test_archiving_a_legacy_row_still_works(admin_client, brand):
    vehicle = legacy_vehicle(brand)

    assert admin_client.delete(f"{URL}{vehicle.pk}/").status_code == status.HTTP_204_NO_CONTENT
    assert admin_client.post(f"{URL}{vehicle.pk}/unarchive/").status_code == status.HTTP_200_OK


# --- spec_complete -----------------------------------------------------------------


@pytest.mark.parametrize(
    "powertrain, cc, expected",
    [
        ("", None, False),
        ("", 1998, False),
        ("petrol", None, False),
        ("petrol", 1998, True),
        ("bev", None, True),
        ("bev", 1000, False),
        ("phev", 1969, True),
    ],
)
def test_spec_complete(brand, powertrain, cc, expected):
    vehicle = VehicleModel(brand=brand, powertrain=powertrain, engine_capacity_cc=cc)

    assert vehicle.spec_complete is expected


# --- bulk import (reuses the serializer row by row) -------------------------------------


def upload(lines):
    return SimpleUploadedFile("fleet.csv", "\n".join(lines).encode(), content_type="text/csv")


def post_import(client, lines):
    return client.post("/api/vehicles/models/bulk_import/", {"file": upload(lines)}, format="multipart")


FULL_HEADER = "brand,name,trim,body_segment,msrp,engine_capacity_kw,powertrain,engine_capacity_cc"


def test_a_file_without_a_powertrain_column_is_a_structural_error(admin_client, brand):
    response = post_import(
        admin_client,
        ["brand,name,trim,body_segment,msrp,engine_capacity_kw,engine_capacity_cc",
         "BMW,3 Series,320i,sedan,265800.00,135.00,1998"],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "powertrain" in response.data["detail"]
    assert not VehicleModel.objects.exists()


def test_a_file_without_a_cc_column_is_not_structural_but_non_bev_rows_fail_per_row(admin_client, brand):
    response = post_import(
        admin_client,
        ["brand,name,trim,body_segment,msrp,engine_capacity_kw,powertrain",
         "BMW,3 Series,320i,sedan,265800.00,135.00,petrol",  # row 2: needs cc
         "BMW,iX,xDrive40,suv,449000.00,240.00,bev"],  # row 3: BEV needs none
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["created_count"] == 1
    assert [e["row"] for e in response.data["errors"]] == [2]
    assert "engine_capacity_cc" in response.data["errors"][0]["errors"]
    assert VehicleModel.objects.get().name == "iX"


def test_row_level_cc_and_powertrain_errors_do_not_block_the_valid_rows(admin_client, brand):
    response = post_import(
        admin_client,
        [
            FULL_HEADER,
            "BMW,3 Series,320i Sport,sedan,265800.00,135.00,petrol,1998",  # row 2: valid
            "BMW,3 Series,330i,sedan,316800.00,190.00,petrol,",  # row 3: petrol without cc
            "BMW,iX,xDrive40,suv,449000.00,240.00,bev,1000",  # row 4: bev with cc
            "BMW,X1,sDrive20i,suv,252800.00,125.00,,1499",  # row 5: no powertrain
            "BMW,X3,xDrive20i,suv,300000.00,135.00,petrol,12000",  # row 6: cc out of range
            "BMW,iX1,eDrive20,suv,250000.00,150.00,bev,",  # row 7: valid BEV
        ],
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["total_rows"] == 6
    assert response.data["created_count"] == 2
    assert {e["row"]: set(e["errors"]) for e in response.data["errors"]} == {
        3: {"engine_capacity_cc"}, 4: {"engine_capacity_cc"}, 5: {"powertrain"}, 6: {"engine_capacity_cc"},
    }
    assert set(VehicleModel.objects.values_list("trim", flat=True)) == {"320i Sport", "eDrive20"}


def test_spreadsheet_spellings_of_a_powertrain_are_normalised_but_nothing_is_guessed(admin_client, brand):
    response = post_import(
        admin_client,
        [
            FULL_HEADER,
            "BMW,330e,M Sport,sedan,300000.00,215.00,Plug-in Hybrid,1998",  # not a real choice -> row error
            "BMW,320i,Mild Hybrid,sedan,265800.00,135.00,Mild Hybrid,1998",  # -> mild_hybrid
            "BMW,325i,Mild-Hybrid,sedan,265800.00,135.00,MILD-HYBRID,1998",  # -> mild_hybrid
        ],
    )

    assert response.data["created_count"] == 2
    assert [e["row"] for e in response.data["errors"]] == [2]
    assert set(VehicleModel.objects.values_list("powertrain", flat=True)) == {"mild_hybrid"}


# --- VehicleModel.clean() (the Django admin form path) -------------------------------------


def make(brand, **overrides):
    fields = dict(
        brand=brand, name="X", trim="Y", body_segment=BodySegment.SEDAN, msrp="100000.00",
        engine_capacity_kw="100.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    fields.update(overrides)
    return VehicleModel(**fields)


def test_clean_accepts_a_complete_petrol_and_a_cc_less_bev(brand):
    make(brand).full_clean()
    make(brand, trim="Z", powertrain="bev", engine_capacity_cc=None).full_clean()


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"engine_capacity_cc": None}, "engine_capacity_cc"),
        ({"powertrain": "bev"}, "engine_capacity_cc"),
        ({"powertrain": ""}, "powertrain"),
        ({"engine_capacity_cc": 599}, "engine_capacity_cc"),
        ({"engine_capacity_cc": 8001}, "engine_capacity_cc"),
    ],
    ids=["petrol-no-cc", "bev-with-cc", "no-powertrain", "cc-too-low", "cc-too-high"],
)
def test_clean_rejects_the_same_cases_as_the_serializer(brand, overrides, field):
    with pytest.raises(ValidationError) as excinfo:
        make(brand, **overrides).full_clean()

    assert field in excinfo.value.message_dict


@pytest.fixture
def django_admin(django_user_model):
    user = django_user_model.objects.create_superuser(email="super@example.com", password="pw")
    client = Client()
    client.force_login(user)
    return client


def admin_form(brand, **overrides):
    data = {
        "brand": brand.pk, "name": "3 Series", "trim": "320i Sport", "body_segment": "sedan",
        "msrp": "265800.00", "engine_capacity_kw": "135.00", "powertrain": "petrol",
        "engine_capacity_cc": "1998", "is_active": "on",
    }
    data.update(overrides)
    return data


def test_the_django_admin_add_form_enforces_the_contract(django_admin, brand):
    url = reverse("admin:vehicles_vehiclemodel_add")

    petrol_no_cc = django_admin.post(url, admin_form(brand, engine_capacity_cc=""))
    assert petrol_no_cc.status_code == 200  # re-rendered with errors, nothing saved
    assert "engine_capacity_cc" in petrol_no_cc.context["adminform"].form.errors

    no_powertrain = django_admin.post(url, admin_form(brand, powertrain=""))
    assert "powertrain" in no_powertrain.context["adminform"].form.errors

    bev_with_cc = django_admin.post(url, admin_form(brand, powertrain="bev"))
    assert "engine_capacity_cc" in bev_with_cc.context["adminform"].form.errors
    assert not VehicleModel.objects.exists()

    bev_ok = django_admin.post(url, admin_form(brand, name="iX", powertrain="bev", engine_capacity_cc=""))
    assert bev_ok.status_code == 302
    assert VehicleModel.objects.get().powertrain == "bev"


# --- the DB constraint -----------------------------------------------------------------------------


def test_the_database_rejects_a_bev_with_cc_even_bypassing_every_validator(brand):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            VehicleModel.objects.create(
                brand=brand, name="iX", trim="X", body_segment=BodySegment.SUV, msrp="449000.00",
                engine_capacity_kw="240.00", powertrain="bev", engine_capacity_cc=1000,
            )


def test_the_database_still_accepts_legacy_rows_and_a_cc_less_bev(brand):
    legacy_vehicle(brand)  # no powertrain, no cc
    VehicleModel.objects.create(
        brand=brand, name="iX", trim="X", body_segment=BodySegment.SUV, msrp="449000.00",
        engine_capacity_kw="240.00", powertrain="bev",
    )

    assert VehicleModel.objects.count() == 2
