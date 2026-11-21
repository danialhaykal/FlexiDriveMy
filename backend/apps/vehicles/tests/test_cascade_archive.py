"""Cascade archive (apps.vehicles.archiving): archiving a brand archives its
vehicles, interest rate, residual value rows, penalty rule and their
vehicles' subscription plans; reactivating restores only what came with
it. Exercised through every entry point: the API, the Django admin
actions, and the Django admin edit form's is_active checkbox."""

from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.policy.models import (
    ContractPenaltyRule,
    InterestRate,
    MileageBand,
    ResidualValueMatrix,
    SubscriptionPlan,
)
from apps.vehicles.models import Brand, VehicleModel

pytestmark = pytest.mark.django_db


def _vehicle(brand, name, is_active=True):
    return VehicleModel.objects.create(
        brand=brand, name=name, trim="T", body_segment="suv",
        msrp=Decimal("300000.00"), engine_capacity_kw=Decimal("200.00"), is_active=is_active,
    )


def _plan(vehicle, is_active=True):
    return SubscriptionPlan.objects.create(
        vehicle=vehicle, fee_monthly=Decimal("5000.00"), insurance_annual=Decimal("6000.00"),
        road_tax_annual=Decimal("1000.00"), maintenance_annual=Decimal("2000.00"), is_active=is_active,
    )


def _rv(brand, tenure, is_active=True):
    return ResidualValueMatrix.objects.create(
        brand=brand, tenure_months=tenure, mileage_band=MileageBand.STANDARD,
        residual_value_ratio=Decimal("0.5000"), is_active=is_active,
    )


def _rule(brand):
    return ContractPenaltyRule.objects.create(
        brand=brand, excess_mileage_charge_per_km=Decimal("0.50"),
        early_termination_fee=Decimal("5000.00"), wear_tear_tolerance_description="Normal wear accepted.",
    )


@pytest.fixture
def admin_api(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def fleet():
    """Volvo: 2 active vehicles + 1 already archived; 1 rate; 1 active and
    1 already-archived RV row; 1 penalty rule; active plans on both active
    vehicles plus an old archived plan. Other: an untouched second brand."""
    volvo = Brand.objects.create(name="Volvo", tier_code="2")
    xc90, xc60 = _vehicle(volvo, "XC90"), _vehicle(volvo, "XC60")
    s90_old = _vehicle(volvo, "S90", is_active=False)
    rows = {
        "brand": volvo, "xc90": xc90, "xc60": xc60, "s90_old": s90_old,
        "rate": InterestRate.objects.create(brand=volvo, rate_percent=Decimal("3.0000")),
        "rv36": _rv(volvo, 36), "rv48_old": _rv(volvo, 48, is_active=False),
        "rule": _rule(volvo),
        "plan90": _plan(xc90), "plan60": _plan(xc60), "plan90_old": _plan(xc90, is_active=False),
    }
    other = Brand.objects.create(name="Lexus", tier_code="1")
    other_vehicle = _vehicle(other, "ES")
    rows.update(
        other=other, other_vehicle=other_vehicle,
        other_rate=InterestRate.objects.create(brand=other, rate_percent=Decimal("2.5000")),
        other_plan=_plan(other_vehicle),
    )
    return rows


def _state(row):
    row.refresh_from_db()
    return (row.is_active, getattr(row, "archived_by_parent", None))


CASCADED = ["xc90", "xc60", "rate", "rv36", "rule", "plan90", "plan60"]
ALREADY_ARCHIVED = ["s90_old", "rv48_old", "plan90_old"]
OTHER_BRAND = ["other", "other_vehicle", "other_rate", "other_plan"]


def _assert_other_brand_untouched(fleet):
    for name in OTHER_BRAND:
        assert fleet[name].__class__.objects.get(pk=fleet[name].pk).is_active, name


# --- archive a brand -----------------------------------------------------------


def test_archiving_a_brand_archives_exactly_its_active_rows_with_one_audit_row_each(admin_api, fleet):
    brand = fleet["brand"]
    audit_before = AuditLog.objects.count()

    response = admin_api.delete(f"/api/vehicles/brands/{brand.pk}/")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert _state(brand) == (False, None)
    for name in CASCADED:
        assert _state(fleet[name]) == (False, True), name
    for name in ALREADY_ARCHIVED:
        assert _state(fleet[name]) == (False, False), name  # flag never set on these
    _assert_other_brand_untouched(fleet)

    new_rows = AuditLog.objects.filter(pk__gt=0).order_by("pk")[audit_before:]
    cascade_rows = [row for row in new_rows if (row.after_data or {}).get("cascade") == f"Brand #{brand.pk} archived"]
    assert len(new_rows) == 1 + len(CASCADED)  # the brand + one per cascaded row
    assert len(cascade_rows) == len(CASCADED)
    assert {(row.resource_type, row.resource_id) for row in cascade_rows} == {
        ("vehicles.VehicleModel", str(fleet["xc90"].pk)),
        ("vehicles.VehicleModel", str(fleet["xc60"].pk)),
        ("policy.InterestRate", str(fleet["rate"].pk)),
        ("policy.ResidualValueMatrix", str(fleet["rv36"].pk)),
        ("policy.ContractPenaltyRule", str(fleet["rule"].pk)),
        ("policy.SubscriptionPlan", str(fleet["plan90"].pk)),
        ("policy.SubscriptionPlan", str(fleet["plan60"].pk)),
    }
    assert all(row.actor_id is not None for row in cascade_rows)


def test_reactivating_a_brand_restores_only_what_its_archive_took(admin_api, fleet):
    brand = fleet["brand"]
    admin_api.delete(f"/api/vehicles/brands/{brand.pk}/")

    response = admin_api.post(f"/api/vehicles/brands/{brand.pk}/unarchive/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["is_active"] is True
    assert response.data["cascade"] == {
        "action": "restore",
        "counts": {"vehicles": 2, "interest_rates": 1, "residual_value_rows": 1, "penalty_rules": 1,
                   "subscription_plans": 2},
        "skipped": [],
    }
    for name in CASCADED:
        assert _state(fleet[name]) == (True, False), name
    for name in ALREADY_ARCHIVED:
        assert _state(fleet[name]) == (False, False), name  # archived on their own - stay archived
    _assert_other_brand_untouched(fleet)


def test_a_replacement_interest_rate_blocks_restoring_the_old_one_which_is_reported_as_skipped(admin_api, fleet):
    brand, old_rate = fleet["brand"], fleet["rate"]
    admin_api.delete(f"/api/vehicles/brands/{brand.pk}/")
    replacement = InterestRate.objects.create(brand=brand, rate_percent=Decimal("4.0000"))

    response = admin_api.post(f"/api/vehicles/brands/{brand.pk}/unarchive/")

    skipped = response.data["cascade"]["skipped"]
    assert [(s["resource_type"], s["id"]) for s in skipped] == [("policy.InterestRate", old_rate.pk)]
    assert f"(#{replacement.pk}) is already active" in skipped[0]["reason"]
    assert response.data["cascade"]["counts"]["interest_rates"] == 0
    assert _state(old_rate) == (False, False)  # left archived, never revived by a later restore
    assert _state(replacement) == (True, False)
    assert _state(fleet["xc90"]) == (True, False)  # everything else still came back


def test_a_replacement_subscription_plan_blocks_restoring_the_old_one(admin_api, fleet):
    brand, old_plan = fleet["brand"], fleet["plan90"]
    admin_api.delete(f"/api/vehicles/brands/{brand.pk}/")
    replacement = _plan(fleet["xc90"])

    response = admin_api.post(f"/api/vehicles/brands/{brand.pk}/unarchive/")

    skipped = response.data["cascade"]["skipped"]
    assert [(s["resource_type"], s["id"]) for s in skipped] == [("policy.SubscriptionPlan", old_plan.pk)]
    assert _state(old_plan) == (False, False)
    assert _state(replacement) == (True, False)
    assert _state(fleet["plan60"]) == (True, False)


# --- one vehicle -------------------------------------------------------------


def test_archiving_and_reactivating_one_vehicle_touches_only_it_and_its_plans(admin_api, fleet):
    xc90 = fleet["xc90"]

    admin_api.delete(f"/api/vehicles/models/{xc90.pk}/")

    assert _state(xc90) == (False, False)  # archived on its own
    assert _state(fleet["plan90"]) == (False, True)
    assert _state(fleet["plan90_old"]) == (False, False)
    for name in ["xc60", "plan60", "rate", "rv36", "rule"]:
        assert _state(fleet[name]) == (True, False), name
    assert _state(fleet["brand"]) == (True, None)

    response = admin_api.post(f"/api/vehicles/models/{xc90.pk}/unarchive/")

    assert response.data["cascade"]["counts"] == {"subscription_plans": 1}
    assert _state(xc90) == (True, False)
    assert _state(fleet["plan90"]) == (True, False)
    assert _state(fleet["plan90_old"]) == (False, False)
    assert _state(fleet["xc60"]) == (True, False)
    _assert_other_brand_untouched(fleet)


def test_individually_reactivating_a_cascade_archived_vehicle_clears_its_flag_and_brand_restore_skips_it(
    admin_api, fleet
):
    brand, xc90 = fleet["brand"], fleet["xc90"]
    admin_api.delete(f"/api/vehicles/brands/{brand.pk}/")

    admin_api.post(f"/api/vehicles/models/{xc90.pk}/unarchive/")
    assert _state(xc90) == (True, False)
    assert _state(fleet["plan90"]) == (True, False)  # came back with its vehicle
    audit_rows_for_xc90 = AuditLog.objects.filter(resource_type="vehicles.VehicleModel", resource_id=str(xc90.pk))
    assert audit_rows_for_xc90.count() == 2  # cascade archive + its own reactivation

    response = admin_api.post(f"/api/vehicles/brands/{brand.pk}/unarchive/")

    assert response.data["cascade"]["counts"]["vehicles"] == 1  # only XC60 left to restore
    assert audit_rows_for_xc90.count() == 2  # not touched a second time
    assert _state(fleet["xc60"]) == (True, False)


def test_a_plan_archived_with_its_vehicle_waits_for_that_vehicle_not_the_brand(admin_api, fleet):
    """XC90 archived on its own (plan90 goes with it), then the brand is
    archived and reactivated: XC90 stays archived, so plan90 must too."""
    brand, xc90 = fleet["brand"], fleet["xc90"]
    admin_api.delete(f"/api/vehicles/models/{xc90.pk}/")
    admin_api.delete(f"/api/vehicles/brands/{brand.pk}/")

    admin_api.post(f"/api/vehicles/brands/{brand.pk}/unarchive/")

    assert _state(xc90) == (False, False)
    assert _state(fleet["plan90"]) == (False, True)  # still waiting for XC90
    admin_api.post(f"/api/vehicles/models/{xc90.pk}/unarchive/")
    assert _state(fleet["plan90"]) == (True, False)


def test_reactivating_a_cascade_archived_policy_row_on_its_own_clears_its_flag(admin_api, fleet):
    brand, rate = fleet["brand"], fleet["rate"]
    admin_api.delete(f"/api/vehicles/brands/{brand.pk}/")

    admin_api.post(f"/api/policy/interest-rates/{rate.pk}/unarchive/")
    assert _state(rate) == (True, False)
    admin_api.delete(f"/api/policy/interest-rates/{rate.pk}/")  # then archived deliberately
    assert _state(rate) == (False, False)

    admin_api.post(f"/api/vehicles/brands/{brand.pk}/unarchive/")

    assert _state(rate) == (False, False)  # the admin's own archive is respected


# --- archive-impact preview ----------------------------------------------------


def test_archive_impact_previews_archive_then_restore_without_changing_anything(admin_api, fleet):
    brand = fleet["brand"]

    archive_preview = admin_api.get(f"/api/vehicles/brands/{brand.pk}/archive-impact/")
    assert archive_preview.data == {
        "action": "archive",
        "counts": {"vehicles": 2, "interest_rates": 1, "residual_value_rows": 1, "penalty_rules": 1,
                   "subscription_plans": 2},
        "skipped": [],
    }
    assert _state(brand) == (True, None)

    admin_api.delete(f"/api/vehicles/brands/{brand.pk}/")
    InterestRate.objects.create(brand=brand, rate_percent=Decimal("4.0000"))
    restore_preview = admin_api.get(f"/api/vehicles/brands/{brand.pk}/archive-impact/")
    assert restore_preview.data["action"] == "restore"
    assert restore_preview.data["counts"]["interest_rates"] == 0
    assert [s["id"] for s in restore_preview.data["skipped"]] == [fleet["rate"].pk]
    assert _state(fleet["rate"]) == (False, True)  # preview wrote nothing

    vehicle_preview = admin_api.get(f"/api/vehicles/models/{fleet['other_vehicle'].pk}/archive-impact/")
    assert vehicle_preview.data["counts"] == {"subscription_plans": 1}


def test_archive_impact_is_admin_only(regular_user, fleet):
    client = APIClient()
    client.force_authenticate(user=regular_user)

    response = client.get(f"/api/vehicles/brands/{fleet['brand'].pk}/archive-impact/")

    assert response.status_code == status.HTTP_403_FORBIDDEN


# --- Django admin ------------------------------------------------------------


@pytest.fixture
def django_admin(django_user_model):
    user = django_user_model.objects.create_superuser(email="super@example.com", password="pw")
    client = Client()
    client.force_login(user)
    return client


def test_django_admin_archive_action_on_a_brand_cascades_and_unarchive_restores(django_admin, fleet):
    brand = fleet["brand"]
    changelist = reverse("admin:vehicles_brand_changelist")

    django_admin.post(changelist, {"action": "archive_selected", "_selected_action": [brand.pk]})

    assert _state(brand) == (False, None)
    for name in CASCADED:
        assert _state(fleet[name]) == (False, True), name
    _assert_other_brand_untouched(fleet)

    django_admin.post(changelist, {"action": "unarchive_selected", "_selected_action": [brand.pk]})

    for name in CASCADED:
        assert _state(fleet[name]) == (True, False), name
    for name in ALREADY_ARCHIVED:
        assert _state(fleet[name]) == (False, False), name


def test_django_admin_unticking_is_active_on_the_brand_form_cascades(django_admin, fleet):
    brand = fleet["brand"]
    change_url = reverse("admin:vehicles_brand_change", args=[brand.pk])

    response = django_admin.post(change_url, {"name": "Volvo", "tier_code": "2"})  # is_active unticked

    assert response.status_code == status.HTTP_302_FOUND
    assert _state(brand) == (False, None)
    for name in CASCADED:
        assert _state(fleet[name]) == (False, True), name
    _assert_other_brand_untouched(fleet)

    django_admin.post(change_url, {"name": "Volvo", "tier_code": "2", "is_active": "on"})

    for name in CASCADED:
        assert _state(fleet[name]) == (True, False), name
    for name in ALREADY_ARCHIVED:
        assert _state(fleet[name]) == (False, False), name


def test_django_admin_archive_action_on_a_vehicle_cascades_to_its_plans_only(django_admin, fleet):
    django_admin.post(
        reverse("admin:vehicles_vehiclemodel_changelist"),
        {"action": "archive_selected", "_selected_action": [fleet["xc90"].pk]},
    )

    assert _state(fleet["xc90"]) == (False, False)
    assert _state(fleet["plan90"]) == (False, True)
    assert _state(fleet["xc60"]) == (True, False)
    assert _state(fleet["brand"]) == (True, None)
