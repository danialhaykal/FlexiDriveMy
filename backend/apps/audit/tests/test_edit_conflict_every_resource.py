"""Run 3 fix batch 4 (F-01): the edit-conflict check (AuditedModelViewSet.perform_update) works for EVERY resource that
uses it. Before the fix, a PATCH that sent `updated_at` to a contract penalty rule gave HTTP 500 ("FOR UPDATE cannot be
applied to the nullable side of an outer join"): the rule's default ordering joins its NULLABLE brand. Each resource
must answer 200 with the updated_at it loaded and 409 with a stale one - including the default rule (no brand)."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.audit.mixins import EDIT_CONFLICT_MESSAGE, AuditedModelViewSet
from apps.policy.models import ContractPenaltyRule, InterestRate, ResidualValueMatrix, SubscriptionPlan
from apps.policy.views import (
    ContractPenaltyRuleViewSet,
    InterestRateViewSet,
    ResidualValueMatrixViewSet,
    SubscriptionPlanViewSet,
)
from apps.vehicles.models import BodySegment, Brand, VehicleModel
from apps.vehicles.views import BrandViewSet, VehicleModelViewSet

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def rows():
    brand = Brand.objects.create(name="Conflict Brand", tier_code="2")
    car = VehicleModel.objects.create(
        brand=brand, name="Conflict Car", trim="Base", body_segment=BodySegment.SEDAN, msrp="200000.00",
        engine_capacity_kw="120.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    rate = InterestRate.objects.create(brand=brand, rate_percent=Decimal("2.8000"))
    override = ResidualValueMatrix.objects.create(brand=brand, tenure_months=36, mileage_band="standard",
                                                  residual_value_ratio=Decimal("0.5000"))
    plan = SubscriptionPlan.objects.create(vehicle=car, fee_monthly=Decimal("3000.00"))
    brand_rule = ContractPenaltyRule.objects.create(
        brand=brand, excess_mileage_charge_per_km=Decimal("0.50"), early_termination_months=Decimal("3.00"),
        wear_tear_tolerance_description="Normal wear is fine.",
    )
    default_rule = ContractPenaltyRule.objects.filter(brand__isnull=True, is_active=True).first()
    if default_rule is None:
        default_rule = ContractPenaltyRule.objects.create(
            brand=None, excess_mileage_charge_per_km=Decimal("0.50"), early_termination_months=Decimal("3.00"),
            wear_tear_tolerance_description="Default terms.",
        )
    return {"brand": brand, "car": car, "rate": rate, "override": override, "plan": plan,
            "brand_rule": brand_rule, "default_rule": default_rule}


# (url prefix, fixture key, a field the PATCH changes, first value, second value)
CASES = [
    ("/api/vehicles/brands/", "brand", "tier_code", "3", "4"),
    ("/api/vehicles/models/", "car", "msrp", "210000.00", "220000.00"),
    ("/api/policy/interest-rates/", "rate", "rate_percent", "2.9000", "3.0000"),
    ("/api/policy/residual-value-matrix/", "override", "residual_value_ratio", "0.4800", "0.4700"),
    ("/api/policy/subscription-plans/", "plan", "fee_monthly", "3100.00", "3200.00"),
    ("/api/policy/contract-penalty-rules/", "brand_rule", "excess_mileage_charge_per_km", "0.60", "0.70"),
    ("/api/policy/contract-penalty-rules/", "default_rule", "excess_mileage_charge_per_km", "0.55", "0.65"),
]


def test_the_cases_cover_every_viewset_that_uses_the_check():
    covered = {"/api/vehicles/brands/": BrandViewSet, "/api/vehicles/models/": VehicleModelViewSet,
               "/api/policy/interest-rates/": InterestRateViewSet, "/api/policy/residual-value-matrix/": ResidualValueMatrixViewSet,
               "/api/policy/subscription-plans/": SubscriptionPlanViewSet, "/api/policy/contract-penalty-rules/": ContractPenaltyRuleViewSet}
    assert {url for url, *_ in CASES} == set(covered)
    users = {cls for cls in (BrandViewSet, VehicleModelViewSet, InterestRateViewSet, ResidualValueMatrixViewSet,
                             SubscriptionPlanViewSet, ContractPenaltyRuleViewSet) if issubclass(cls, AuditedModelViewSet)}
    assert users == set(covered.values())


@pytest.mark.parametrize("url, key, field, first_value, second_value", CASES)
def test_patch_with_the_loaded_updated_at_saves_and_a_stale_one_is_refused(admin_client, rows, url, key, field, first_value, second_value):
    pk = rows[key].pk
    loaded = admin_client.get(f"{url}{pk}/").data["updated_at"]

    first = admin_client.patch(f"{url}{pk}/", {field: first_value, "updated_at": loaded}, format="json")
    assert first.status_code == 200, first.data
    assert str(first.data[field]) == first_value

    stale = admin_client.patch(f"{url}{pk}/", {field: second_value, "updated_at": loaded}, format="json")
    assert stale.status_code == 409
    assert stale.data["detail"] == EDIT_CONFLICT_MESSAGE

    fresh = admin_client.patch(f"{url}{pk}/", {field: second_value, "updated_at": first.data["updated_at"]}, format="json")
    assert fresh.status_code == 200
    assert str(fresh.data[field]) == second_value


@pytest.mark.parametrize("url, key, field, first_value, second_value", CASES)
def test_a_put_from_the_form_with_updated_at_also_saves(admin_client, rows, url, key, field, first_value, second_value):
    pk = rows[key].pk
    loaded = admin_client.get(f"{url}{pk}/").data
    payload = {k: v for k, v in loaded.items() if k not in ("id", "created_at", "is_active", "brand_name", "vehicle_label",
                                                            "spec_complete", "min_downpayment")}
    payload[field] = first_value
    response = admin_client.patch(f"{url}{pk}/", payload, format="json")
    assert response.status_code == 200, response.data
