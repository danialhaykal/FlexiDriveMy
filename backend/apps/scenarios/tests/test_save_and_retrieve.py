import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.scenarios.models import SavedScenario
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def vehicle():
    brand = Brand.objects.create(name="ScenarioBrand", tier_code="A")
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00",
    )


# An old, browser-built payload - rows like this are still stored and served as-is.
SAMPLE_PAYLOAD = {"hire_purchase": {"monthly_instalment": "10900.00"}, "recommended_pathway": "hire_purchase"}
# What a client sends now (run 1 fix batch 2): inputs, never figures.
SAMPLE_INPUTS = {"tenure_months": 36, "mileage_band": "standard", "downpayment": "10000.00"}


def test_requires_authentication(vehicle):
    client = APIClient()
    response = client.post(
        "/api/scenarios/", {"title": "My Plan", "vehicle": vehicle.id, "inputs": SAMPLE_INPUTS}, format="json"
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_save_a_scenario(user_client, vehicle, regular_user):
    response = user_client.post(
        "/api/scenarios/", {"title": "My Plan", "vehicle": vehicle.id, "inputs": SAMPLE_INPUTS}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    scenario = SavedScenario.objects.get(user=regular_user, title="My Plan")
    assert scenario.payload["builtBy"] == "server"
    assert scenario.payload["comparison"]["vehicle_id"] == vehicle.id
    assert response.data["payload"] == scenario.payload
    assert scenario.vehicle_id == vehicle.id


def test_list_returns_only_the_users_own_scenarios(user_client, vehicle, regular_user, create_user):
    other_user = create_user(email="someone-else@example.com")
    SavedScenario.objects.create(user=regular_user, title="Mine", vehicle=vehicle, payload=SAMPLE_PAYLOAD)
    SavedScenario.objects.create(user=other_user, title="Theirs", vehicle=vehicle, payload=SAMPLE_PAYLOAD)

    response = user_client.get("/api/scenarios/")

    assert response.status_code == status.HTTP_200_OK
    titles = {row["title"] for row in response.data["results"]}
    assert titles == {"Mine"}


def test_retrieve_reloads_the_full_stored_payload(user_client, vehicle, regular_user):
    scenario = SavedScenario.objects.create(
        user=regular_user, title="Weekend Trip Car", vehicle=vehicle, payload=SAMPLE_PAYLOAD
    )

    response = user_client.get(f"/api/scenarios/{scenario.id}/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["payload"] == SAMPLE_PAYLOAD
    assert response.data["title"] == "Weekend Trip Car"
    assert "ScenarioBrand" in response.data["vehicle_label"]


def test_delete_a_scenario(user_client, vehicle, regular_user):
    scenario = SavedScenario.objects.create(
        user=regular_user, title="To Delete", vehicle=vehicle, payload=SAMPLE_PAYLOAD
    )

    response = user_client.delete(f"/api/scenarios/{scenario.id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not SavedScenario.objects.filter(pk=scenario.id).exists()


def test_blank_title_rejected(user_client, vehicle):
    response = user_client.post(
        "/api/scenarios/", {"title": "   ", "vehicle": vehicle.id, "inputs": SAMPLE_INPUTS}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
