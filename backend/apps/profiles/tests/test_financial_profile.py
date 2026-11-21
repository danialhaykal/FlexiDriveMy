from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.profiles.models import AnnualMileageBand, FinancialProfile, OwnershipPreference

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


def valid_payload(**overrides):
    payload = {
        "monthly_budget": "2500.00",
        "preferred_tenure_months": 60,
        "annual_mileage_band": "high",
        "ownership_preference": OwnershipPreference.RETAIN,
        "shariah_compliant_required": False,
    }
    payload.update(overrides)
    return payload


# --- Access control -----------------------------------------------------


def test_get_requires_authentication():
    client = APIClient()
    response = client.get("/api/profile/financial/")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_returns_404_before_first_save(user_client):
    response = user_client.get("/api/profile/financial/")
    assert response.status_code == status.HTTP_404_NOT_FOUND


# --- Main flow: save & apply baseline -----------------------------------


def test_put_creates_profile_for_first_time(user_client, regular_user):
    response = user_client.put("/api/profile/financial/", valid_payload(), format="json")

    assert response.status_code == status.HTTP_200_OK
    profile = FinancialProfile.objects.get(user=regular_user)
    assert profile.monthly_budget == Decimal("2500.00")
    assert profile.preferred_tenure_months == 60


def test_put_updates_existing_profile(user_client, regular_user):
    user_client.put("/api/profile/financial/", valid_payload(), format="json")

    response = user_client.put(
        "/api/profile/financial/", valid_payload(monthly_budget="3200.00"), format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert FinancialProfile.objects.filter(user=regular_user).count() == 1  # upsert, not a second row
    profile = FinancialProfile.objects.get(user=regular_user)
    assert str(profile.monthly_budget) == "3200.00"


def test_get_returns_saved_profile(user_client):
    user_client.put("/api/profile/financial/", valid_payload(), format="json")

    response = user_client.get("/api/profile/financial/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["monthly_budget"] == "2500.00"
    assert response.data["annual_mileage_band"] == "high"


# --- Boundary validation (UC003 Rules 1-2) -------------------------------


@pytest.mark.parametrize("budget", ["0.00", "-100.00"])
def test_rejects_non_positive_monthly_budget(user_client, budget):
    response = user_client.put("/api/profile/financial/", valid_payload(monthly_budget=budget), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Please enter a valid positive numerical amount." in str(response.data["monthly_budget"])


def test_rejects_alphabetic_monthly_budget(user_client):
    response = user_client.put(
        "/api/profile/financial/", valid_payload(monthly_budget="not-a-number"), format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Please enter a valid positive numerical amount." in str(response.data["monthly_budget"])


@pytest.mark.parametrize("tenure", [11, 109, 0, -5])
def test_rejects_tenure_outside_12_to_108_months(user_client, tenure):
    response = user_client.put(
        "/api/profile/financial/", valid_payload(preferred_tenure_months=tenure), format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "between 12 and 108 months" in str(response.data["preferred_tenure_months"])


@pytest.mark.parametrize("tenure", [12, 108])
def test_accepts_tenure_boundary_values(user_client, tenure):
    response = user_client.put(
        "/api/profile/financial/", valid_payload(preferred_tenure_months=tenure), format="json"
    )
    assert response.status_code == status.HTTP_200_OK


# --- Invalid-input flow preserves valid fields (UC003 alt flow) ---------


def test_invalid_budget_does_not_reject_other_valid_fields(user_client):
    payload = valid_payload(monthly_budget="-999.00")

    response = user_client.put("/api/profile/financial/", payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "monthly_budget" in response.data
    assert "preferred_tenure_months" not in response.data
    assert "annual_mileage_band" not in response.data
    assert "ownership_preference" not in response.data


def test_invalid_submission_does_not_persist_or_overwrite_existing_profile(user_client, regular_user):
    user_client.put("/api/profile/financial/", valid_payload(monthly_budget="2500.00"), format="json")

    bad_response = user_client.put(
        "/api/profile/financial/", valid_payload(monthly_budget="-1.00"), format="json"
    )
    assert bad_response.status_code == status.HTTP_400_BAD_REQUEST

    # The previously-saved baseline is untouched by the rejected submission.
    profile = FinancialProfile.objects.get(user=regular_user)
    assert str(profile.monthly_budget) == "2500.00"


# --- Mileage band / ownership / Shariah preference persistence ----------


@pytest.mark.parametrize("band", ["low", "standard", "high", "very_high"])
def test_all_mileage_bands_persist(user_client, regular_user, band):
    """Audit batch 6 (F6): the profile stores the SAME four bands the compare
    screens use, so one list serves both."""
    response = user_client.put("/api/profile/financial/", valid_payload(annual_mileage_band=band), format="json")
    assert response.status_code == status.HTTP_200_OK
    profile = FinancialProfile.objects.get(user=regular_user)
    assert profile.annual_mileage_band == band
    assert response.data["annual_mileage_band"] == band


@pytest.mark.parametrize(
    "old_value, band",
    [(AnnualMileageBand.KM_10000, "standard"), (AnnualMileageBand.KM_20000, "high"), (AnnualMileageBand.KM_30000, "very_high")],
)
def test_an_old_client_sending_a_literal_km_value_is_stored_as_its_band(user_client, regular_user, old_value, band):
    response = user_client.put("/api/profile/financial/", valid_payload(annual_mileage_band=old_value), format="json")

    assert response.status_code == status.HTTP_200_OK
    assert FinancialProfile.objects.get(user=regular_user).annual_mileage_band == band
    assert response.data["annual_mileage_band"] == band


@pytest.mark.parametrize(
    "stored, band", [("10000", "standard"), ("20000", "high"), ("30000", "very_high"), ("low", "low")]
)
def test_a_profile_saved_before_the_change_still_loads_and_reads_as_its_band(user_client, regular_user, stored, band):
    """A row written with a legacy km value (never re-saved) must not crash the
    API: it is shown as the band whose range starts at that figure."""
    FinancialProfile.objects.create(
        user=regular_user, monthly_budget="2500.00", preferred_tenure_months=48,
        annual_mileage_band=stored, ownership_preference="retain",
    )

    response = user_client.get("/api/profile/financial/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["annual_mileage_band"] == band


def test_a_value_that_is_neither_a_band_nor_a_legacy_figure_is_rejected_cleanly(user_client):
    response = user_client.put("/api/profile/financial/", valid_payload(annual_mileage_band="15000"), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "annual_mileage_band" in response.data


def test_the_declared_mileage_alert_works_for_a_legacy_stored_value(user_client, regular_user):
    """build_tco_report compares the profile's band with the selected one; a
    legacy stored value must map, not raise a KeyError."""
    from apps.profiles.models import normalize_mileage_band

    assert normalize_mileage_band("20000") == "high"
    assert normalize_mileage_band("very_high") == "very_high"
    assert normalize_mileage_band("bogus") is None


@pytest.mark.parametrize("preference", [OwnershipPreference.RETAIN, OwnershipPreference.UPGRADE])
def test_ownership_preference_persists(user_client, regular_user, preference):
    user_client.put(
        "/api/profile/financial/", valid_payload(ownership_preference=preference), format="json"
    )
    profile = FinancialProfile.objects.get(user=regular_user)
    assert profile.ownership_preference == preference


@pytest.mark.parametrize("shariah_required", [True, False])
def test_shariah_preference_persists(user_client, regular_user, shariah_required):
    user_client.put(
        "/api/profile/financial/",
        valid_payload(shariah_compliant_required=shariah_required),
        format="json",
    )
    profile = FinancialProfile.objects.get(user=regular_user)
    assert profile.shariah_compliant_required is shariah_required


def test_rejects_invalid_mileage_band_choice(user_client):
    response = user_client.put(
        "/api/profile/financial/", valid_payload(annual_mileage_band="15000"), format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "annual_mileage_band" in response.data


def test_profile_is_scoped_to_the_requesting_user(user_client, regular_user, create_user):
    other_user = create_user(email="someone-else@example.com")
    user_client.put("/api/profile/financial/", valid_payload(), format="json")

    other_client = APIClient()
    other_client.force_authenticate(user=other_user)
    response = other_client.get("/api/profile/financial/")

    assert response.status_code == status.HTTP_404_NOT_FOUND
