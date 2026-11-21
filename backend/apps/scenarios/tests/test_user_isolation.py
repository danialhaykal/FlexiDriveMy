import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.scenarios.models import SavedScenario
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def vehicle():
    brand = Brand.objects.create(name="IsolationBrand", tier_code="A")
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00",
    )


@pytest.fixture
def owners_scenario(regular_user, vehicle):
    return SavedScenario.objects.create(
        user=regular_user, title="Owner's Plan", vehicle=vehicle, payload={"recommended_pathway": "hire_purchase"}
    )


@pytest.fixture
def other_client(create_user):
    other_user = create_user(email="intruder@example.com")
    client = APIClient()
    client.force_authenticate(user=other_user)
    return client


# --- UC009 Rule 1: users can only view/modify/delete their own scenarios ---


def test_user_cannot_retrieve_another_users_scenario(other_client, owners_scenario):
    response = other_client.get(f"/api/scenarios/{owners_scenario.id}/")
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_user_cannot_list_another_users_scenario(other_client, owners_scenario):
    response = other_client.get("/api/scenarios/")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 0


def test_user_cannot_update_another_users_scenario(other_client, owners_scenario):
    response = other_client.patch(
        f"/api/scenarios/{owners_scenario.id}/", {"payload": {"tampered": True}}, format="json"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    owners_scenario.refresh_from_db()
    assert owners_scenario.payload == {"recommended_pathway": "hire_purchase"}


def test_user_cannot_delete_another_users_scenario(other_client, owners_scenario):
    response = other_client.delete(f"/api/scenarios/{owners_scenario.id}/")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert SavedScenario.objects.filter(pk=owners_scenario.id).exists()


def test_duplicate_title_check_is_scoped_per_user_not_global(regular_user, vehicle, owners_scenario, other_client):
    # Another user saving the *same* title is not a conflict - the
    # uniqueness constraint is per-account, not global.
    response = other_client.post(
        "/api/scenarios/",
        {
            "title": "Owner's Plan",
            "vehicle": vehicle.id,
            "inputs": {"tenure_months": 36, "mileage_band": "standard", "downpayment": "10000.00"},
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
