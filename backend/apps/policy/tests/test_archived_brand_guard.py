"""Interest rates, residual value ratios and contract penalty rules can't be
created under an archived brand (same guard as VehicleModelSerializer.
validate_brand), but an existing row whose brand was archived later can
still be edited while keeping that brand - matching AdminPolicyPage, which
keeps the row's own archived brand selectable on Edit."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import MileageBand
from apps.vehicles.models import Brand

pytestmark = pytest.mark.django_db

ARCHIVED_MESSAGE = "Brand is archived and cannot be assigned to new records."

ENDPOINTS = {
    "interest-rates": lambda brand: {"brand": brand.id, "rate_percent": "3.0000"},
    "residual-value-matrix": lambda brand: {
        "brand": brand.id,
        "tenure_months": 36,
        "mileage_band": MileageBand.STANDARD,
        "residual_value_ratio": "0.5000",
    },
    "contract-penalty-rules": lambda brand: {
        "brand": brand.id,
        "excess_mileage_charge_per_km": "0.50",
        "early_termination_fee": "5000.00",
        "wear_tear_tolerance_description": "Normal wear and tear accepted.",
    },
}


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def active_brand():
    return Brand.objects.create(name="Toyota", tier_code="2")


@pytest.fixture
def archived_brand():
    return Brand.objects.create(name="Honda", tier_code="4", is_active=False)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_create_rejects_an_archived_brand(admin_client, archived_brand, endpoint):
    response = admin_client.post(f"/api/policy/{endpoint}/", ENDPOINTS[endpoint](archived_brand), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["brand"] == [ARCHIVED_MESSAGE]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_editing_a_row_may_keep_its_own_brand_after_that_brand_was_archived(admin_client, active_brand, endpoint):
    created = admin_client.post(f"/api/policy/{endpoint}/", ENDPOINTS[endpoint](active_brand), format="json")
    assert created.status_code == status.HTTP_201_CREATED
    Brand.objects.filter(pk=active_brand.pk).update(is_active=False)

    response = admin_client.put(
        f"/api/policy/{endpoint}/{created.data['id']}/", ENDPOINTS[endpoint](active_brand), format="json"
    )

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_editing_a_row_cannot_switch_it_to_a_different_archived_brand(
    admin_client, active_brand, archived_brand, endpoint
):
    created = admin_client.post(f"/api/policy/{endpoint}/", ENDPOINTS[endpoint](active_brand), format="json")

    response = admin_client.put(
        f"/api/policy/{endpoint}/{created.data['id']}/", ENDPOINTS[endpoint](archived_brand), format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["brand"] == [ARCHIVED_MESSAGE]
