"""Batch 7 / QA audit H15 + M25 - both in apps.vehicles.admin.

H15: VehicleModelAdmin.brand no longer renders Django's "+"/pencil/
lookup icons (RelatedFieldWidgetWrapper) - those wire to the vendored
RelatedObjectLookups.js::showAdminPopup(), which crashes with an
unhandled TypeError when a popup blocker returns null from window.open().

M25: the brand field's queryset is restricted to active brands (except
the vehicle's own current brand on its change form), and the admin
autocomplete endpoint (not Brand's own changelist search) is restricted
the same way.
"""

import pytest
from django.test import Client
from django.urls import reverse

from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_django_client(django_user_model):
    user = django_user_model.objects.create_superuser(email="superadmin@example.com", password="pw")
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def active_brand():
    return Brand.objects.create(name="ActiveBrand", tier_code="2")


@pytest.fixture
def archived_brand():
    return Brand.objects.create(name="ArchivedBrand", tier_code="3", is_active=False)


# --- H15: the broken "+" popup control is gone from this field -------------


def test_add_form_has_no_add_popup_icon_for_brand(admin_django_client, active_brand):
    add_url = reverse("admin:vehicles_vehiclemodel_add")

    response = admin_django_client.get(add_url)

    assert response.status_code == 200
    # The exact anchor id Django's related_widget_wrapper.html template
    # renders for a field named "brand" - its presence is what wires up
    # showAdminPopup() client-side; its absence proves the crash path
    # (and the pencil/lookup icons alongside it) is gone.
    assert b'id="add_id_brand"' not in response.content
    assert b'id="change_id_brand"' not in response.content


def test_change_form_has_no_add_popup_icon_for_brand(admin_django_client, active_brand):
    vehicle = VehicleModel.objects.create(
        brand=active_brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00",
    )
    change_url = reverse("admin:vehicles_vehiclemodel_change", args=[vehicle.pk])

    response = admin_django_client.get(change_url)

    assert response.status_code == 200
    assert b'id="add_id_brand"' not in response.content


# --- M25: archived brands excluded from the add-form queryset --------------


def test_add_form_queryset_excludes_an_archived_brand(admin_django_client, active_brand, archived_brand):
    add_url = reverse("admin:vehicles_vehiclemodel_add")

    response = admin_django_client.get(add_url)

    form = response.context["adminform"].form
    brand_queryset = form.fields["brand"].queryset
    assert active_brand in brand_queryset
    assert archived_brand not in brand_queryset


def test_posting_an_archived_brands_pk_to_the_add_form_is_rejected(admin_django_client, archived_brand):
    add_url = reverse("admin:vehicles_vehiclemodel_add")

    response = admin_django_client.post(
        add_url,
        {
            "brand": archived_brand.pk,
            "name": "ShouldNotSave",
            "trim": "X",
            "body_segment": BodySegment.SEDAN,
            "msrp": "100000.00",
            "engine_capacity_kw": "90.00",
            "is_active": "on",
        },
    )

    assert response.status_code == 200  # re-renders the form with an error, no redirect
    form = response.context["adminform"].form
    assert "brand" in form.errors
    assert not VehicleModel.objects.filter(name="ShouldNotSave").exists()


# --- M25: the exception - a vehicle's own (now-archived) brand stays usable


def test_change_form_still_includes_the_vehicles_own_brand_after_it_was_archived(admin_django_client, active_brand):
    vehicle = VehicleModel.objects.create(
        brand=active_brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00",
    )
    active_brand.is_active = False
    active_brand.save(update_fields=["is_active"])
    change_url = reverse("admin:vehicles_vehiclemodel_change", args=[vehicle.pk])

    response = admin_django_client.get(change_url)

    form = response.context["adminform"].form
    assert active_brand in form.fields["brand"].queryset


def test_resaving_a_vehicle_unchanged_after_its_brand_was_archived_still_succeeds(
    admin_django_client, active_brand
):
    vehicle = VehicleModel.objects.create(
        brand=active_brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1498,
    )
    active_brand.is_active = False
    active_brand.save(update_fields=["is_active"])
    change_url = reverse("admin:vehicles_vehiclemodel_change", args=[vehicle.pk])

    response = admin_django_client.post(
        change_url,
        {
            "brand": active_brand.pk,
            "name": vehicle.name,
            "trim": vehicle.trim,
            "body_segment": vehicle.body_segment,
            "msrp": str(vehicle.msrp),
            "engine_capacity_kw": str(vehicle.engine_capacity_kw),
            "powertrain": vehicle.powertrain,
            "engine_capacity_cc": str(vehicle.engine_capacity_cc),
            "is_active": "on",
        },
    )

    assert response.status_code == 302  # redirect on success, not a validation error
    vehicle.refresh_from_db()
    assert vehicle.brand_id == active_brand.pk


# --- M25: the autocomplete endpoint vs. Brand's own changelist search ------


def test_brand_autocomplete_endpoint_excludes_archived_brands(admin_django_client, active_brand, archived_brand):
    autocomplete_url = reverse("admin:autocomplete")

    response = admin_django_client.get(
        autocomplete_url,
        {
            "app_label": "vehicles",
            "model_name": "vehiclemodel",
            "field_name": "brand",
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    result_ids = {int(item["id"]) for item in results}
    assert active_brand.pk in result_ids
    assert archived_brand.pk not in result_ids


def test_brands_own_changelist_search_still_finds_an_archived_brand(admin_django_client, archived_brand):
    changelist_url = reverse("admin:vehicles_brand_changelist")

    response = admin_django_client.get(changelist_url, {"q": archived_brand.name})

    assert response.status_code == 200
    assert archived_brand.name.encode() in response.content
