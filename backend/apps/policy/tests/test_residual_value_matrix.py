from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import MileageBand, ResidualValueMatrix
from apps.vehicles.models import Brand

pytestmark = pytest.mark.django_db


@pytest.fixture
def brand():
    return Brand.objects.create(name="BMW", tier_code="A")


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def valid_payload(brand, **overrides):
    payload = {
        "brand": brand.id,
        "tenure_months": 36,
        "mileage_band": MileageBand.STANDARD,
        "residual_value_ratio": "0.5000",
    }
    payload.update(overrides)
    return payload


def test_create_residual_value_entry(admin_client, brand):
    response = admin_client.post("/api/policy/residual-value-matrix/", valid_payload(brand), format="json")
    assert response.status_code == status.HTTP_201_CREATED
    assert ResidualValueMatrix.objects.filter(brand=brand, tenure_months=36).exists()


def test_unique_per_brand_tenure_mileage_band(admin_client, brand):
    admin_client.post("/api/policy/residual-value-matrix/", valid_payload(brand), format="json")

    response = admin_client.post("/api/policy/residual-value-matrix/", valid_payload(brand), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert ResidualValueMatrix.objects.filter(brand=brand).count() == 1


@pytest.mark.parametrize("tenure_months,expected_boundary", [(11, "12"), (109, "108")])
def test_tenure_must_be_within_hp_formula_range(admin_client, brand, tenure_months, expected_boundary):
    response = admin_client.post(
        "/api/policy/residual-value-matrix/", valid_payload(brand, tenure_months=tenure_months), format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert expected_boundary in str(response.data["tenure_months"])


@pytest.mark.parametrize("tenure_months", [12, 108])
def test_tenure_accepts_boundary_values(admin_client, brand, tenure_months):
    response = admin_client.post(
        "/api/policy/residual-value-matrix/", valid_payload(brand, tenure_months=tenure_months), format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED


# --- M15: residual ratio ceiling (1 - MIN_DOWNPAYMENT_RATIO) ----------------


def test_residual_ratio_above_the_ceiling_is_rejected(admin_client, brand):
    response = admin_client.post(
        "/api/policy/residual-value-matrix/", valid_payload(brand, residual_value_ratio="0.9001"), format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "0.90" in str(response.data["residual_value_ratio"])
    assert not ResidualValueMatrix.objects.filter(brand=brand).exists()


def test_residual_ratio_at_100_percent_is_rejected(admin_client, brand):
    response = admin_client.post(
        "/api/policy/residual-value-matrix/", valid_payload(brand, residual_value_ratio="1.0000"), format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_residual_ratio_exactly_at_the_ceiling_is_accepted(admin_client, brand):
    response = admin_client.post(
        "/api/policy/residual-value-matrix/", valid_payload(brand, residual_value_ratio="0.9000"), format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED


def test_archive_residual_value_entry(admin_client, brand):
    create_response = admin_client.post("/api/policy/residual-value-matrix/", valid_payload(brand), format="json")
    entry_id = create_response.data["id"]

    response = admin_client.delete(f"/api/policy/residual-value-matrix/{entry_id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    entry = ResidualValueMatrix.objects.get(pk=entry_id)
    assert entry.is_active is False


# --- M18: an archived cell can be replaced, and can be un-archived ----------


def test_recreating_an_archived_residual_cell_succeeds(admin_client, brand):
    create_response = admin_client.post("/api/policy/residual-value-matrix/", valid_payload(brand), format="json")
    entry_id = create_response.data["id"]
    admin_client.delete(f"/api/policy/residual-value-matrix/{entry_id}/")

    response = admin_client.post(
        "/api/policy/residual-value-matrix/", valid_payload(brand, residual_value_ratio="0.6000"), format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    active = ResidualValueMatrix.objects.filter(
        brand=brand, tenure_months=36, mileage_band=MileageBand.STANDARD, is_active=True
    )
    assert active.count() == 1
    assert active.first().residual_value_ratio == Decimal("0.6000")
    # The archived original is untouched, just no longer active.
    assert ResidualValueMatrix.objects.filter(brand=brand, is_active=False).count() == 1


def test_unarchiving_a_residual_cell_via_the_api_action(admin_client, brand):
    create_response = admin_client.post("/api/policy/residual-value-matrix/", valid_payload(brand), format="json")
    entry_id = create_response.data["id"]
    admin_client.delete(f"/api/policy/residual-value-matrix/{entry_id}/")
    assert ResidualValueMatrix.objects.get(pk=entry_id).is_active is False

    response = admin_client.post(f"/api/policy/residual-value-matrix/{entry_id}/unarchive/")

    assert response.status_code == status.HTTP_200_OK
    assert ResidualValueMatrix.objects.get(pk=entry_id).is_active is True


def test_unarchive_requires_admin_role(admin_client, regular_user, brand):
    create_response = admin_client.post("/api/policy/residual-value-matrix/", valid_payload(brand), format="json")
    entry_id = create_response.data["id"]
    admin_client.delete(f"/api/policy/residual-value-matrix/{entry_id}/")

    client = APIClient()
    client.force_authenticate(user=regular_user)
    response = client.post(f"/api/policy/residual-value-matrix/{entry_id}/unarchive/")

    assert response.status_code == status.HTTP_403_FORBIDDEN
