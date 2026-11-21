import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import InterestRate
from apps.vehicles.models import Brand

pytestmark = pytest.mark.django_db


@pytest.fixture
def brand():
    return Brand.objects.create(name="Toyota", tier_code="A")


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def test_create_interest_rate_within_bounds(admin_client, brand):
    response = admin_client.post(
        "/api/policy/interest-rates/", {"brand": brand.id, "rate_percent": "3.0000"}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert InterestRate.objects.filter(brand=brand).exists()


@pytest.mark.parametrize(
    "rate,expected_boundary",
    [("0.00", "0.01"), ("-1.0000", "0.01"), ("15.01", "15.00"), ("20.0000", "15.00")],
)
def test_create_interest_rate_rejects_out_of_bounds(admin_client, brand, rate, expected_boundary):
    response = admin_client.post(
        "/api/policy/interest-rates/", {"brand": brand.id, "rate_percent": rate}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert expected_boundary in str(response.data["rate_percent"])
    assert not InterestRate.objects.filter(brand=brand).exists()


# --- QA audit L1: exact UC011 alternate-flow copy, not DRF's generic text --


def test_out_of_bounds_interest_rate_uses_the_exact_uc011_copy(admin_client, brand):
    response = admin_client.post(
        "/api/policy/interest-rates/", {"brand": brand.id, "rate_percent": "20.0000"}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["rate_percent"][0] == (
        "Interest rate input exceeds acceptable limits (0.01% – 15.00%)."
    )


@pytest.mark.parametrize("rate", ["0.01", "15.00", "7.5000"])
def test_create_interest_rate_accepts_boundary_values(admin_client, brand, rate):
    response = admin_client.post(
        "/api/policy/interest-rates/", {"brand": brand.id, "rate_percent": rate}, format="json"
    )
    assert response.status_code == status.HTTP_201_CREATED


def test_archive_interest_rate(admin_client, brand):
    create_response = admin_client.post(
        "/api/policy/interest-rates/", {"brand": brand.id, "rate_percent": "3.0000"}, format="json"
    )
    rate_id = create_response.data["id"]

    response = admin_client.delete(f"/api/policy/interest-rates/{rate_id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    rate = InterestRate.objects.get(pk=rate_id)
    assert rate.is_active is False


def test_interest_rate_requires_admin_role(brand, regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    response = client.post(
        "/api/policy/interest-rates/", {"brand": brand.id, "rate_percent": "3.0000"}, format="json"
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


# --- H12: at most one active rate per brand ---------------------------------


def test_creating_a_second_active_rate_for_the_same_brand_is_rejected_cleanly(admin_client, brand):
    admin_client.post("/api/policy/interest-rates/", {"brand": brand.id, "rate_percent": "3.0000"}, format="json")

    response = admin_client.post(
        "/api/policy/interest-rates/", {"brand": brand.id, "rate_percent": "4.0000"}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "already has an active interest rate" in str(response.data["brand"])
    assert InterestRate.objects.filter(brand=brand, is_active=True).count() == 1


def test_archiving_then_creating_a_replacement_rate_succeeds(admin_client, brand):
    create_response = admin_client.post(
        "/api/policy/interest-rates/", {"brand": brand.id, "rate_percent": "3.0000"}, format="json"
    )
    old_rate_id = create_response.data["id"]
    admin_client.delete(f"/api/policy/interest-rates/{old_rate_id}/")

    response = admin_client.post(
        "/api/policy/interest-rates/", {"brand": brand.id, "rate_percent": "4.0000"}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    active_rates = InterestRate.objects.filter(brand=brand, is_active=True)
    assert active_rates.count() == 1
    assert active_rates.first().rate_percent == pytest.approx(4.0)


def test_db_constraint_rejects_two_active_rates_even_bypassing_the_serializer(brand):
    """Defense in depth - the serializer's validate() is the clean-error
    path, but the real guarantee is the DB constraint itself (migration
    0006_interestrate_unique_active_interest_rate_per_brand), which holds
    regardless of code path (management command, admin, a future
    endpoint that forgets this check).
    """
    from django.db import IntegrityError

    InterestRate.objects.create(brand=brand, rate_percent="3.0000", is_active=True)
    with pytest.raises(IntegrityError):
        InterestRate.objects.create(brand=brand, rate_percent="4.0000", is_active=True)
