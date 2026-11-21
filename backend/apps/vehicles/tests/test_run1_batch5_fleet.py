"""Run 1 fix batch 5, steps 1-2: Fleet Management (D1, UC010), the edit
conflict check (G7), Spec Draft URLs with dots (D3) and the deprecated
operating-cost-band table in Django admin (D4)."""

import pytest
from django.contrib.admin.sites import site
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.mixins import EDIT_CONFLICT_MESSAGE
from apps.policy.models import InterestRate, OperatingCostBand
from apps.vehicles import paultan_research
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

MACAN_EV_URL = "https://paultan.org/research/porsche/macan-electric/mk2/rwd-2026/"
ALPHARD_URL = "https://paultan.org/research/toyota/alphard/ah40/2.4-executive-lounge-2026/"


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def lexus():
    """Like the dev catalog's ES 250: no model year recorded."""
    brand = Brand.objects.create(name="Lexus", tier_code="1")
    return VehicleModel.objects.create(
        brand=brand, name="ES", trim="250 Luxury", body_segment=BodySegment.SEDAN, msrp="356888.00",
        engine_capacity_kw="151.00", powertrain="petrol", engine_capacity_cc=2487, model_year=None,
    )


def form_payload(vehicle, **overrides):
    """What the Fleet form sends on Save Changes (a PUT of every field)."""
    payload = {
        "brand": vehicle.brand_id, "name": vehicle.name, "trim": vehicle.trim, "body_segment": vehicle.body_segment,
        "model_year": None, "msrp": str(vehicle.msrp), "engine_capacity_kw": str(vehicle.engine_capacity_kw),
        "powertrain": vehicle.powertrain, "engine_capacity_cc": vehicle.engine_capacity_cc, "road_tax_class": "",
        "thumbnail_url": "",
    }
    payload.update(overrides)
    return payload


# --- 1.1 model year is optional --------------------------------------------------------------------------


@pytest.mark.parametrize("blank", [None, ""])
def test_a_car_with_no_model_year_can_have_its_price_edited(admin_client, lexus, blank):
    response = admin_client.put(
        f"/api/vehicles/models/{lexus.pk}/", form_payload(lexus, msrp="359888.00", model_year=blank), format="json"
    )

    assert response.status_code == 200, response.data
    lexus.refresh_from_db()
    assert (lexus.msrp, lexus.model_year) == (359888, None)
    assert response.data["model_year"] is None


def test_a_patch_without_the_year_leaves_it_null(admin_client, lexus):
    response = admin_client.patch(f"/api/vehicles/models/{lexus.pk}/", {"msrp": "360000.00"}, format="json")

    assert response.status_code == 200
    assert response.data["model_year"] is None


def test_bulk_import_accepts_a_blank_model_year(admin_client):
    Brand.objects.create(name="Lexus", tier_code="1")
    csv = (
        "brand,name,trim,body_segment,msrp,engine_capacity_kw,powertrain,engine_capacity_cc,model_year\n"
        "Lexus,RX,350h,suv,450000.00,184.00,hybrid,2487,\n"
    ).encode()

    response = admin_client.post(
        "/api/vehicles/models/bulk_import/", {"file": SimpleUploadedFile("cars.csv", csv)}, format="multipart"
    )

    assert response.status_code in (200, 201), response.data
    assert VehicleModel.objects.get(name="RX").model_year is None


def test_the_catalog_sends_null_not_a_text_null(lexus, regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)

    data = client.get(f"/api/vehicles/catalog/{lexus.pk}/").data

    assert data["model_year"] is None


# --- 1.2 plain messages --------------------------------------------------------------------------------------


def test_raw_framework_messages_become_plain_ones(admin_client):
    response = admin_client.post("/api/vehicles/models/", {
        "brand": None, "name": "", "trim": "X", "body_segment": "", "msrp": "100000.00",
        "engine_capacity_kw": "100.00", "powertrain": "petrol", "engine_capacity_cc": 1998,
    }, format="json")

    assert response.status_code == 400
    assert response.data["brand"] == ["Brand is required."]
    assert response.data["name"] == ["Model name is required."]
    assert response.data["body_segment"] == ["Choose a body segment."]


def test_missing_fields_and_the_specific_uc010_messages(admin_client):
    brand = Brand.objects.create(name="Plain", tier_code="2")

    missing = admin_client.post("/api/vehicles/models/", {"brand": brand.pk}, format="json")
    bad_price = admin_client.post("/api/vehicles/models/", {
        "brand": brand.pk, "name": "M", "trim": "X", "body_segment": "sedan", "msrp": "0",
        "engine_capacity_kw": "100.00", "powertrain": "petrol", "engine_capacity_cc": 1998,
    }, format="json")

    assert missing.data["msrp"] == ["MSRP is required."]
    assert missing.data["engine_capacity_kw"] == ["Power output is required."]
    assert bad_price.data["msrp"] == ["MSRP must be a positive numeric value."]


# --- 1.4 edited by someone else -------------------------------------------------------------------------------------


def test_two_patches_with_the_same_old_updated_at_give_200_then_409(admin_client, lexus):
    loaded = admin_client.get(f"/api/vehicles/models/{lexus.pk}/").data["updated_at"]

    first = admin_client.patch(
        f"/api/vehicles/models/{lexus.pk}/", {"msrp": "360000.00", "updated_at": loaded}, format="json"
    )
    second = admin_client.patch(
        f"/api/vehicles/models/{lexus.pk}/", {"msrp": "370000.00", "updated_at": loaded}, format="json"
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.data["detail"] == EDIT_CONFLICT_MESSAGE
    lexus.refresh_from_db()
    assert lexus.msrp == 360000  # the second admin's change was not written


def test_the_fresh_updated_at_saves_again(admin_client, lexus):
    first = admin_client.patch(f"/api/vehicles/models/{lexus.pk}/", {
        "msrp": "360000.00", "updated_at": admin_client.get(f"/api/vehicles/models/{lexus.pk}/").data["updated_at"],
    }, format="json")

    again = admin_client.patch(
        f"/api/vehicles/models/{lexus.pk}/", {"msrp": "365000.00", "updated_at": first.data["updated_at"]},
        format="json",
    )

    assert again.status_code == 200


def test_without_updated_at_an_older_caller_keeps_last_write_wins(admin_client, lexus):
    assert admin_client.patch(f"/api/vehicles/models/{lexus.pk}/", {"msrp": "360000.00"}, format="json").status_code == 200
    assert admin_client.patch(f"/api/vehicles/models/{lexus.pk}/", {"msrp": "370000.00"}, format="json").status_code == 200


def test_an_unreadable_updated_at_is_a_400(admin_client, lexus):
    response = admin_client.patch(
        f"/api/vehicles/models/{lexus.pk}/", {"msrp": "360000.00", "updated_at": "yesterday"}, format="json"
    )

    assert response.status_code == 400
    assert "updated_at" in response.data


def test_policy_rows_get_the_same_check(admin_client):
    brand = Brand.objects.create(name="RateBrand", tier_code="2")
    rate = InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    loaded = admin_client.get(f"/api/policy/interest-rates/{rate.pk}/").data["updated_at"]
    url = f"/api/policy/interest-rates/{rate.pk}/"

    first = admin_client.put(url, {"brand": brand.pk, "rate_percent": "2.9000", "updated_at": loaded}, format="json")
    second = admin_client.put(url, {"brand": brand.pk, "rate_percent": "2.5000", "updated_at": loaded}, format="json")

    assert (first.status_code, second.status_code) == (200, 409)
    assert second.data["detail"] == EDIT_CONFLICT_MESSAGE


# --- 2.1 spec draft URLs with dots -----------------------------------------------------------------------------------


@pytest.mark.parametrize("url", [MACAN_EV_URL, ALPHARD_URL])
def test_variant_urls_with_and_without_dots_are_accepted(url):
    assert paultan_research.is_variant_url(url)


def test_the_year_is_read_from_a_dotted_slug():
    assert paultan_research.extract_model_year(ALPHARD_URL, "") == 2026


@pytest.mark.parametrize("url", [
    "https://example.com/research/toyota/alphard/ah40/2.4-executive-lounge-2026/",
    "http://paultan.org/research/toyota/alphard/ah40/2.4-executive-lounge-2026/",
    "https://paultan.org.evil.test/research/toyota/alphard/ah40/2.4-executive-lounge-2026/",
    "https://paultan.org/research/toyota/alphard/../../2.4-executive-lounge-2026/",
    "https://paultan.org/research/toyota/alphard/ah40/..-2026/",
    "https://paultan.org/other/toyota/alphard/ah40/2.4-executive-lounge-2026/",
])
def test_anything_off_the_research_pages_is_still_refused(url):
    assert not paultan_research.is_variant_url(url)


def test_a_dotted_variant_url_can_start_a_draft(admin_client, monkeypatch):
    brand = Brand.objects.create(name="Toyota", tier_code="1")
    monkeypatch.setattr(
        "apps.vehicles.paultan_research.render_research_page",
        lambda url: {"status": 404, "final_url": url, "title": "", "text": "", "links": []},
    )

    response = admin_client.post("/api/vehicles/spec-drafts/", {"brand": brand.pk, "source_url": ALPHARD_URL}, format="json")

    assert response.status_code == 201, response.data


def test_a_non_paultan_url_cannot_start_a_draft(admin_client):
    brand = Brand.objects.create(name="Toyota", tier_code="1")

    response = admin_client.post(
        "/api/vehicles/spec-drafts/", {"brand": brand.pk, "source_url": "https://example.com/alphard-2026/"},
        format="json",
    )

    assert response.status_code == 400


# --- 2.2 the deprecated operating-cost-band table -------------------------------------------------------------


def test_the_deprecated_table_is_read_only_in_django_admin_under_its_new_title(django_user_model):
    band = OperatingCostBand.objects.create(
        min_engine_capacity_kw="0.00", max_engine_capacity_kw="100.00", road_tax_annual="90.00",
        insurance_annual="1000.00", maintenance_annual="1000.00",
    )
    client = Client()
    client.force_login(django_user_model.objects.create_superuser(email="super@example.com", password="pw"))
    model_admin = site._registry[OperatingCostBand]

    assert OperatingCostBand._meta.verbose_name_plural == "Operating cost bands (deprecated - not used)"
    changelist = client.get(reverse("admin:policy_operatingcostband_changelist"))
    assert changelist.status_code == 200
    assert "Operating cost bands (deprecated - not used)" in changelist.content.decode()
    assert client.get(reverse("admin:policy_operatingcostband_add")).status_code == 403
    assert client.post(reverse("admin:policy_operatingcostband_change", args=[band.pk]), {}).status_code == 403
    assert client.post(reverse("admin:policy_operatingcostband_delete", args=[band.pk]), {"post": "yes"}).status_code == 403
    assert not model_admin.get_actions(changelist.wsgi_request)
    assert OperatingCostBand.objects.filter(pk=band.pk).exists()  # the data is kept
