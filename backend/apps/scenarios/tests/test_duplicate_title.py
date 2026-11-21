import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.scenarios.models import SavedScenario
from apps.scenarios.serializers import DUPLICATE_TITLE_MESSAGE, PAYLOAD_NOT_ACCEPTED_MESSAGE
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def vehicle():
    brand = Brand.objects.create(name="DupBrand", tier_code="A")
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00",
    )


ORIGINAL_PAYLOAD = {"recommended_pathway": "hire_purchase"}
NEW_PAYLOAD = {"recommended_pathway": "subscription"}
# What a client sends now (run 1 fix batch 2): inputs, never figures.
INPUTS = {"tenure_months": 36, "mileage_band": "standard", "downpayment": "10000.00"}


# --- UC009 alt flow 2.1-2.3: reject with the exact message -----------------


def test_duplicate_title_without_overwrite_is_rejected(user_client, vehicle, regular_user):
    SavedScenario.objects.create(user=regular_user, title="Family Car", vehicle=vehicle, payload=ORIGINAL_PAYLOAD)

    response = user_client.post(
        "/api/scenarios/", {"title": "Family Car", "vehicle": vehicle.id, "inputs": INPUTS}, format="json"
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["detail"] == DUPLICATE_TITLE_MESSAGE
    # The original scenario is untouched by the rejected attempt.
    scenario = SavedScenario.objects.get(user=regular_user, title="Family Car")
    assert scenario.payload == ORIGINAL_PAYLOAD
    assert SavedScenario.objects.filter(user=regular_user, title="Family Car").count() == 1


# --- UC009 alt flow 2.4a: user picks a new title instead --------------------


def test_saving_with_a_different_title_succeeds(user_client, vehicle, regular_user):
    SavedScenario.objects.create(user=regular_user, title="Family Car", vehicle=vehicle, payload=ORIGINAL_PAYLOAD)

    response = user_client.post(
        "/api/scenarios/", {"title": "Family Car 2", "vehicle": vehicle.id, "inputs": INPUTS}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert SavedScenario.objects.filter(user=regular_user).count() == 2


# --- UC009 alt flow 2.4b: overwrite replaces the payload and bumps the timestamp ---


def test_overwrite_replaces_payload_and_bumps_updated_at(user_client, vehicle, regular_user):
    scenario = SavedScenario.objects.create(
        user=regular_user, title="Family Car", vehicle=vehicle, payload=ORIGINAL_PAYLOAD
    )
    original_updated_at = scenario.updated_at

    response = user_client.post(
        "/api/scenarios/",
        {"title": "Family Car", "vehicle": vehicle.id, "inputs": INPUTS, "overwrite": "true"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    scenario.refresh_from_db()
    assert scenario.payload["builtBy"] == "server"  # replaced by a server-built snapshot
    assert scenario.updated_at > original_updated_at
    # No second row was created - the existing one was replaced in place.
    assert SavedScenario.objects.filter(user=regular_user, title="Family Car").count() == 1


# --- M3: create's duplicate check is case-insensitive -----------------------


def test_duplicate_title_check_is_case_insensitive_on_create(user_client, vehicle, regular_user):
    SavedScenario.objects.create(user=regular_user, title="Family Car", vehicle=vehicle, payload=ORIGINAL_PAYLOAD)

    response = user_client.post(
        "/api/scenarios/", {"title": "FAMILY CAR", "vehicle": vehicle.id, "inputs": INPUTS}, format="json"
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert SavedScenario.objects.filter(user=regular_user).count() == 1


# --- M3: renaming to a duplicate title (the bug that gave a 500) -----------


def test_renaming_to_an_already_used_title_is_rejected_cleanly_not_a_500(user_client, vehicle, regular_user):
    SavedScenario.objects.create(user=regular_user, title="Family Car", vehicle=vehicle, payload=ORIGINAL_PAYLOAD)
    to_rename = SavedScenario.objects.create(
        user=regular_user, title="Road Trip", vehicle=vehicle, payload=NEW_PAYLOAD
    )

    response = user_client.patch(
        f"/api/scenarios/{to_rename.pk}/", {"title": "Family Car"}, format="json"
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data["detail"] == DUPLICATE_TITLE_MESSAGE
    to_rename.refresh_from_db()
    assert to_rename.title == "Road Trip"  # untouched by the rejected rename


def test_renaming_to_a_duplicate_title_is_rejected_case_insensitively(user_client, vehicle, regular_user):
    SavedScenario.objects.create(user=regular_user, title="Family Car", vehicle=vehicle, payload=ORIGINAL_PAYLOAD)
    to_rename = SavedScenario.objects.create(
        user=regular_user, title="Road Trip", vehicle=vehicle, payload=NEW_PAYLOAD
    )

    response = user_client.patch(
        f"/api/scenarios/{to_rename.pk}/", {"title": "FAMILY CAR"}, format="json"
    )

    assert response.status_code == status.HTTP_409_CONFLICT


def test_renaming_to_its_own_current_title_still_succeeds(user_client, vehicle, regular_user):
    scenario = SavedScenario.objects.create(
        user=regular_user, title="Family Car", vehicle=vehicle, payload=ORIGINAL_PAYLOAD
    )

    response = user_client.patch(f"/api/scenarios/{scenario.pk}/", {"title": "Family Car"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    scenario.refresh_from_db()
    assert scenario.payload == ORIGINAL_PAYLOAD  # a rename never touches the figures


def test_renaming_to_a_genuinely_new_title_succeeds(user_client, vehicle, regular_user):
    scenario = SavedScenario.objects.create(
        user=regular_user, title="Family Car", vehicle=vehicle, payload=ORIGINAL_PAYLOAD
    )

    response = user_client.patch(f"/api/scenarios/{scenario.pk}/", {"title": "Weekend Car"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    scenario.refresh_from_db()
    assert scenario.title == "Weekend Car"


# --- M3, then run 1 fix batch 2: a client-sent payload of any shape or size is refused ---


@pytest.mark.parametrize(
    "bad_payload", ["just a string", 12345, None, True, ["a", "list"], {"filler": "x" * 300_000}]
)
def test_any_client_payload_is_rejected(user_client, vehicle, bad_payload):
    response = user_client.post(
        "/api/scenarios/", {"title": "Bad Payload", "vehicle": vehicle.id, "payload": bad_payload}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["payload"] == [PAYLOAD_NOT_ACCEPTED_MESSAGE]


def test_duplicate_title_message_says_comparison_and_title():
    # FX-1 (X8): the buyer-facing words, with the rename / overwrite hint kept.
    assert DUPLICATE_TITLE_MESSAGE == (
        "A comparison with this title already exists. Please choose a different title or overwrite the existing comparison."
    )
