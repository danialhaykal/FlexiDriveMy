import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def honda():
    return Brand.objects.create(name="Honda", tier_code="A")


@pytest.fixture
def toyota():
    return Brand.objects.create(name="Toyota", tier_code="A")


@pytest.fixture
def catalog(honda, toyota):
    """A small active catalog plus one archived vehicle that must never
    appear (UC004 Rule 1)."""
    city = VehicleModel.objects.create(
        brand=honda, name="City", trim="V", body_segment=BodySegment.SEDAN,
        msrp="99999.99", engine_capacity_kw="90.00",
    )
    crv = VehicleModel.objects.create(
        brand=honda, name="CR-V", trim="TC", body_segment=BodySegment.SUV,
        msrp="180000.00", engine_capacity_kw="140.00",
    )
    vios = VehicleModel.objects.create(
        brand=toyota, name="Vios", trim="G", body_segment=BodySegment.SEDAN,
        msrp="89000.00", engine_capacity_kw="80.00",
    )
    archived = VehicleModel.objects.create(
        brand=toyota, name="Hilux", trim="Rogue", body_segment=BodySegment.PICKUP,
        msrp="150000.00", engine_capacity_kw="150.00", is_active=False,
    )
    return {"city": city, "crv": crv, "vios": vios, "archived": archived}


def names(response):
    return {row["name"] for row in response.data["results"]}


# --- Access control & publication rule (UC004 Rule 1) -----------------------


def test_catalog_requires_authentication(catalog):
    client = APIClient()
    response = client.get("/api/vehicles/catalog/")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_catalog_only_shows_active_vehicles(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 3
    assert "Hilux" not in names(response)


def test_regular_user_can_browse_catalog(user_client, catalog):
    # UC004's actor is "User", not System Administrator - no admin role needed.
    response = user_client.get("/api/vehicles/catalog/")
    assert response.status_code == status.HTTP_200_OK


# --- H13: archiving a brand removes its vehicles too, not just itself -------


def test_archiving_a_brand_removes_its_vehicles_from_the_catalog(user_client, catalog, toyota):
    before = user_client.get("/api/vehicles/catalog/")
    assert names(before) == {"City", "CR-V", "Vios"}

    toyota.is_active = False
    toyota.save(update_fields=["is_active"])

    after = user_client.get("/api/vehicles/catalog/")
    assert names(after) == {"City", "CR-V"}
    assert after.data["count"] == 2


def test_archiving_a_brand_does_not_affect_other_brands_vehicles(user_client, catalog, toyota):
    toyota.is_active = False
    toyota.save(update_fields=["is_active"])

    response = user_client.get("/api/vehicles/catalog/")

    assert names(response) == {"City", "CR-V"}


# --- Dynamic filters (UC004 main flow step 3) --------------------------


def test_filter_by_brand(user_client, catalog, honda):
    response = user_client.get("/api/vehicles/catalog/", {"brand": honda.id})

    assert response.data["count"] == 2
    assert names(response) == {"City", "CR-V"}


def test_filter_by_body_segment(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"body_segment": BodySegment.SUV})

    assert response.data["count"] == 1
    assert names(response) == {"CR-V"}


def test_filter_by_price_range_min_and_max(user_client, catalog):
    response = user_client.get(
        "/api/vehicles/catalog/", {"min_price": "90000", "max_price": "180000"}
    )

    assert names(response) == {"City", "CR-V"}


def test_filter_by_price_range_min_only(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"min_price": "100000"})
    assert names(response) == {"CR-V"}


def test_filter_by_price_range_max_only(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"max_price": "90000"})
    assert names(response) == {"Vios"}


def test_filter_by_search_term_matches_name(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"search": "vios"})
    assert names(response) == {"Vios"}


# --- M1: bad filter input is a clean 400, never a 500 -----------------------


def test_non_numeric_brand_is_rejected_cleanly(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"brand": "abc"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "brand" in response.data


def test_unknown_brand_id_is_rejected_cleanly(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"brand": "999999"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_unknown_body_segment_is_rejected_cleanly(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"body_segment": "spaceship"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_non_numeric_min_price_is_rejected_cleanly(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"min_price": "abc"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "min_price" in response.data


def test_non_numeric_max_price_is_rejected_cleanly(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"max_price": "abc"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "max_price" in response.data


def test_min_price_greater_than_max_price_is_a_clear_error_not_a_silent_empty_result(user_client, catalog):
    response = user_client.get(
        "/api/vehicles/catalog/", {"min_price": "200000", "max_price": "100000"}
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "min_price" in response.data


def test_filter_by_search_term_matches_brand(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"search": "Honda"})
    assert names(response) == {"City", "CR-V"}


def test_filter_by_search_term_matches_trim(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"search": "TC"})
    assert names(response) == {"CR-V"}


def test_combined_filters_brand_and_body_segment_and_price(user_client, catalog, honda):
    response = user_client.get(
        "/api/vehicles/catalog/",
        {"brand": honda.id, "body_segment": BodySegment.SEDAN, "max_price": "150000"},
    )
    assert names(response) == {"City"}


def test_combined_filters_narrow_to_nothing(user_client, catalog, honda):
    response = user_client.get(
        "/api/vehicles/catalog/",
        {"brand": honda.id, "body_segment": BodySegment.PICKUP},
    )
    assert response.data["count"] == 0


# --- No matching vehicles (UC004 alternate flow) ----------------------------


def test_no_matching_vehicles_returns_empty_result_not_an_error(user_client, catalog):
    response = user_client.get("/api/vehicles/catalog/", {"search": "Bugatti"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 0
    assert response.data["results"] == []


def test_resetting_filters_restores_full_catalog(user_client, catalog):
    filtered = user_client.get("/api/vehicles/catalog/", {"search": "Bugatti"})
    assert filtered.data["count"] == 0

    reset = user_client.get("/api/vehicles/catalog/")
    assert reset.data["count"] == 3


# --- Vehicle detail view -----------------------------------------------


def test_vehicle_detail_view_returns_full_spec(user_client, catalog):
    city = catalog["city"]
    response = user_client.get(f"/api/vehicles/catalog/{city.id}/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["name"] == "City"
    assert response.data["brand_name"] == "Honda"
    assert response.data["msrp"] == "99999.99"


def test_archived_vehicle_not_reachable_via_catalog_detail(user_client, catalog):
    archived = catalog["archived"]
    response = user_client.get(f"/api/vehicles/catalog/{archived.id}/")
    assert response.status_code == status.HTTP_404_NOT_FOUND


# --- Brand filter dropdown source ---------------------------------------


def test_catalog_brands_endpoint_lists_only_active_brands(user_client, catalog, honda, toyota):
    Brand.objects.create(name="Defunct Motors", tier_code="C", is_active=False)

    response = user_client.get("/api/vehicles/catalog/brands/")

    assert response.status_code == status.HTTP_200_OK
    brand_names = {row["name"] for row in response.data}
    assert brand_names == {"Honda", "Toyota"}
