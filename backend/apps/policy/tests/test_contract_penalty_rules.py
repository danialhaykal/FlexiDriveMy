"""Batch 6A: ContractPenaltyRuleViewSet CRUD + archive + the one-active-
per-brand uniqueness guard (a clean 400, not a raw IntegrityError)."""

from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import ContractPenaltyRule
from apps.vehicles.models import Brand

pytestmark = pytest.mark.django_db


@pytest.fixture
def brand():
    return Brand.objects.create(name="Toyota", tier_code="1")


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def rule_payload(brand, **overrides):
    payload = {
        "brand": brand.id,
        "excess_mileage_charge_per_km": "0.50",
        "early_termination_months": "3",
        "wear_tear_tolerance_description": "Normal wear and tear accepted; excess damage charged at dealer discretion.",
    }
    payload.update(overrides)
    return payload


def test_create_and_retrieve(admin_client, brand):
    response = admin_client.post("/api/policy/contract-penalty-rules/", rule_payload(brand), format="json")
    assert response.status_code == status.HTTP_201_CREATED
    assert ContractPenaltyRule.objects.filter(brand=brand).exists()
    assert response.data["brand_name"] == "Toyota"


def test_create_requires_admin_role(regular_user, brand):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    response = client.post("/api/policy/contract-penalty-rules/", rule_payload(brand), format="json")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_rejects_a_second_active_rule_for_the_same_brand_with_a_clean_400(admin_client, brand):
    admin_client.post("/api/policy/contract-penalty-rules/", rule_payload(brand), format="json")

    response = admin_client.post("/api/policy/contract-penalty-rules/", rule_payload(brand), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "brand" in response.data
    assert ContractPenaltyRule.objects.filter(brand=brand, is_active=True).count() == 1


def test_archiving_then_creating_a_replacement_succeeds(admin_client, brand):
    first = admin_client.post("/api/policy/contract-penalty-rules/", rule_payload(brand), format="json")
    rule_id = first.data["id"]

    archive_response = admin_client.delete(f"/api/policy/contract-penalty-rules/{rule_id}/")
    assert archive_response.status_code == status.HTTP_204_NO_CONTENT

    replacement = admin_client.post(
        "/api/policy/contract-penalty-rules/",
        rule_payload(brand, early_termination_months="6"),
        format="json",
    )
    assert replacement.status_code == status.HTTP_201_CREATED
    assert ContractPenaltyRule.objects.filter(brand=brand, is_active=True).count() == 1


# --- Audit batch 4: the default rule (no brand) and months-not-ringgit ------


def test_the_migration_seeds_exactly_one_planning_estimate_default_rule():
    default = ContractPenaltyRule.objects.get(brand__isnull=True, is_active=True)
    assert default.excess_mileage_charge_per_km == Decimal("0.50")
    assert default.early_termination_months == Decimal("3.00")
    assert default.early_termination_fee is None  # the deprecated stored amount is never seeded
    assert "Planning estimate" in default.source_note and "edit in admin" in default.source_note


def test_re_running_the_seed_migration_keeps_one_default_and_touches_no_brand_row(brand):
    import importlib

    from django.apps import apps as django_apps

    seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")
    legacy = ContractPenaltyRule.objects.create(
        brand=brand, excess_mileage_charge_per_km="0.75", early_termination_fee="4500.00",
        wear_tear_tolerance_description="Legacy terms.",
    )
    default = ContractPenaltyRule.objects.get(brand__isnull=True, is_active=True)
    default.excess_mileage_charge_per_km = Decimal("0.65")  # an admin edit
    default.save()

    seed.forwards(django_apps, None)
    seed.forwards(django_apps, None)

    assert ContractPenaltyRule.objects.filter(brand__isnull=True, is_active=True).count() == 1
    default.refresh_from_db()
    assert default.excess_mileage_charge_per_km == Decimal("0.65")  # never overwritten
    legacy.refresh_from_db()  # keeps its per-km value; months stay empty (= "use the default")
    assert (legacy.excess_mileage_charge_per_km, legacy.early_termination_months) == (Decimal("0.75"), None)
    assert legacy.early_termination_fee == Decimal("4500.00")  # the deprecated column is kept, not destroyed


def test_a_second_active_default_rule_is_a_clean_400_not_an_integrity_error(admin_client):
    response = admin_client.post(
        "/api/policy/contract-penalty-rules/",
        {"excess_mileage_charge_per_km": "0.60", "early_termination_months": "4",
         "wear_tear_tolerance_description": "Another default."},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "brand" in response.data
    assert ContractPenaltyRule.objects.filter(brand__isnull=True, is_active=True).count() == 1


def test_the_database_itself_refuses_two_active_defaults():
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        ContractPenaltyRule.objects.create(
            brand=None, excess_mileage_charge_per_km="0.60", early_termination_months="4",
            wear_tear_tolerance_description="Another default.",
        )


def test_archiving_the_default_then_creating_a_replacement_succeeds(admin_client):
    default = ContractPenaltyRule.objects.get(brand__isnull=True, is_active=True)
    assert admin_client.delete(f"/api/policy/contract-penalty-rules/{default.pk}/").status_code == 204

    response = admin_client.post(
        "/api/policy/contract-penalty-rules/",
        {"brand": None, "excess_mileage_charge_per_km": "0.60", "early_termination_months": "4",
         "wear_tear_tolerance_description": "Replacement default."},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["brand"] is None and response.data["brand_name"] is None


def test_the_default_rule_must_state_its_months(admin_client):
    ContractPenaltyRule.objects.filter(brand__isnull=True).update(is_active=False)

    response = admin_client.post(
        "/api/policy/contract-penalty-rules/",
        {"excess_mileage_charge_per_km": "0.60", "wear_tear_tolerance_description": "No months."},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "early_termination_months" in response.data


def test_a_brand_rule_may_leave_its_months_empty_to_use_the_default(admin_client, brand):
    response = admin_client.post(
        "/api/policy/contract-penalty-rules/",
        rule_payload(brand, early_termination_months=None),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["early_termination_months"] is None
    assert "early_termination_fee" not in response.data  # deprecated, not exposed


def test_archive_is_soft_delete_not_hard_delete(admin_client, brand):
    created = admin_client.post("/api/policy/contract-penalty-rules/", rule_payload(brand), format="json")
    rule_id = created.data["id"]

    response = admin_client.delete(f"/api/policy/contract-penalty-rules/{rule_id}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    rule = ContractPenaltyRule.objects.get(pk=rule_id)
    assert rule.is_active is False
