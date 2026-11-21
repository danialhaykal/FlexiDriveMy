"""F010 optional stretch goal - UC010's 'Fetch Spec Draft' assist, sourced
from paultan.org's structured Car Buyer's Guide. Every test mocks
apps.vehicles.paultan_research.render_research_page (its only network
function) - none launches a real browser or touches the internet. The pure
extraction/listing parsers have their own tests in test_paultan_research.py.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditActionCategory, AuditLog
from apps.vehicles.models import Brand, BodySegment, VehicleModel, VehicleSpecDraft, VehicleSpecDraftStatus
from apps.vehicles.tasks import fetch_vehicle_spec_draft
from apps.vehicles.tests.test_paultan_research import (
    BRAND_PAGE_LINKS,
    MODEL_PAGE_LINKS,
    TEXT_330I_2025,
    TEXT_C200_HYBRID,
    TEXT_EV_SINGLE_MOTOR,
    TITLE_330I_2025,
    URL_330I_2025,
)

pytestmark = pytest.mark.django_db

RENDER = "apps.vehicles.paultan_research.render_research_page"
MODEL_URL = "https://paultan.org/research/bmw/3-series/"


def page(status_code=200, title="", text="", links=()):
    return {"status": status_code, "final_url": "", "title": title, "text": text, "links": list(links)}


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def brand():
    return Brand.objects.create(name="BMW", tier_code="2")


@pytest.fixture
def draft(brand, admin_user):
    return VehicleSpecDraft.objects.create(
        brand=brand,
        source_url=URL_330I_2025,
        model_name_query="3 Series",
        trim_query="330i M Sport",
        requested_by=admin_user,
    )


# --- Task: variant page -> staged fields ---------------------------------


def test_full_variant_page_stages_every_field_including_cc_and_powertrain(draft, monkeypatch):
    monkeypatch.setattr(RENDER, lambda url: page(title=TITLE_330I_2025, text=TEXT_330I_2025))

    fetch_vehicle_spec_draft(draft.pk)

    draft.refresh_from_db()
    assert draft.status == VehicleSpecDraftStatus.READY
    assert draft.source_url == URL_330I_2025
    assert draft.proposed_data == {
        "body_segment": BodySegment.SEDAN,
        "model_year": "2025",
        "msrp": "313800",
        # 258 hp (PS) * 0.7355 = 189.759 -> 189.76 kW (power output)
        "engine_capacity_kw": "189.76",
        # "Capacity 1,998 cc" and "Fuel Petrol" on the page.
        "engine_capacity_cc": "1998",
        "powertrain": "petrol",
    }
    assert draft.missing_fields == []
    assert draft.fetched_at is not None


def test_fields_absent_from_the_page_go_to_missing_fields_not_guessed(draft, monkeypatch):
    text = "G20 LCI 2 · launched Jun 12 2025 · Sedan · CKD\nCapacity\n1,998 cc\n"
    monkeypatch.setattr(RENDER, lambda url: page(title="", text=text))

    fetch_vehicle_spec_draft(draft.pk)

    draft.refresh_from_db()
    assert draft.status == VehicleSpecDraftStatus.READY
    assert draft.proposed_data == {
        "body_segment": BodySegment.SEDAN, "model_year": "2025", "engine_capacity_cc": "1998",
    }
    # No Fuel line -> powertrain is never guessed from the cc.
    assert draft.missing_fields == ["msrp", "engine_capacity_kw", "powertrain"]


def test_an_ev_page_stages_bev_and_does_not_list_cc_as_missing(draft, monkeypatch):
    text = "Mk1 · launched Nov 30 2024 · SUV · CBU\n" + TEXT_EV_SINGLE_MOTOR
    monkeypatch.setattr(
        RENDER, lambda url: page(title="Porsche Macan RWD — RM575,000, specifications Malaysia — paultan.org", text=text)
    )

    fetch_vehicle_spec_draft(draft.pk)

    draft.refresh_from_db()
    assert draft.status == VehicleSpecDraftStatus.READY
    assert draft.proposed_data["powertrain"] == "bev"
    assert "engine_capacity_cc" not in draft.proposed_data  # none exists, and none may be proposed
    assert "engine_capacity_cc" not in draft.missing_fields  # an EV correctly has no cc
    assert draft.proposed_data["engine_capacity_kw"] == "261.10"  # Motor Horsepower, 355 hp
    assert draft.missing_fields == []


def test_an_ambiguous_hybrid_page_stages_cc_but_leaves_powertrain_for_the_admin(draft, monkeypatch):
    # Mercedes C200: paultan's Fuel line says only "Petrol Hybrid/REV".
    monkeypatch.setattr(RENDER, lambda url: page(title="", text=TEXT_C200_HYBRID))

    fetch_vehicle_spec_draft(draft.pk)

    draft.refresh_from_db()
    assert draft.proposed_data["engine_capacity_cc"] == "1496"
    assert "powertrain" not in draft.proposed_data
    assert "powertrain" in draft.missing_fields


def test_a_paultan_body_type_with_no_bodysegment_equivalent_is_left_missing(draft, monkeypatch):
    text = TEXT_330I_2025.replace("· Sedan ·", "· Wagon ·")
    monkeypatch.setattr(RENDER, lambda url: page(title=TITLE_330I_2025, text=text))

    fetch_vehicle_spec_draft(draft.pk)

    draft.refresh_from_db()
    assert "body_segment" not in draft.proposed_data
    assert draft.missing_fields == ["body_segment"]


def test_a_404_variant_page_sets_not_found(draft, monkeypatch):
    monkeypatch.setattr(RENDER, lambda url: page(status_code=404))

    fetch_vehicle_spec_draft(draft.pk)

    draft.refresh_from_db()
    assert draft.status == VehicleSpecDraftStatus.NOT_FOUND
    assert draft.proposed_data == {}
    assert draft.fetched_at is not None


@pytest.mark.parametrize("status_code", [403, 500, 503])
def test_a_non_404_http_error_page_is_failed_not_ready_with_everything_missing(draft, monkeypatch, status_code):
    # Even with a full spec sheet in the body, an error status means the
    # page wasn't really loaded - nothing is extracted from it.
    monkeypatch.setattr(
        RENDER, lambda url: page(status_code=status_code, title=TITLE_330I_2025, text=TEXT_330I_2025)
    )

    fetch_vehicle_spec_draft(draft.pk)

    draft.refresh_from_db()
    assert draft.status == VehicleSpecDraftStatus.FAILED
    assert draft.error_message == f"HTTP {status_code} from paultan.org"
    assert draft.proposed_data == {}
    assert draft.missing_fields == []
    assert draft.fetched_at is not None


def test_an_unhandled_exception_lands_in_failed_not_stuck_in_pending(draft, monkeypatch):
    def _boom(url):
        raise TimeoutError("Page.goto: Timeout 20000ms exceeded.")

    monkeypatch.setattr(RENDER, _boom)

    fetch_vehicle_spec_draft(draft.pk)  # must not raise

    draft.refresh_from_db()
    assert draft.status == VehicleSpecDraftStatus.FAILED
    assert draft.status != VehicleSpecDraftStatus.PENDING
    # Run 1 fix batch 4: a safe, plain message (the error's type only); the
    # raw text goes to a "runtime_error" audit row instead.
    assert draft.error_message == (
        "Couldn't fetch the spec page (TimeoutError). Please try again, or fill in the form by hand."
    )
    assert draft.fetched_at is not None


def test_a_failed_fetch_still_returns_201_from_create_rather_than_a_500(admin_client, brand, monkeypatch):
    """The task runs inline (CELERY_TASK_ALWAYS_EAGER) - before FAILED
    existed, an exception here propagated out of .delay() as a raw 500."""
    def _boom(url):
        raise RuntimeError("browser crashed")

    monkeypatch.setattr(RENDER, _boom)

    response = admin_client.post(
        "/api/vehicles/spec-drafts/", {"brand": brand.pk, "source_url": URL_330I_2025}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    polled = admin_client.get(f"/api/vehicles/spec-drafts/{response.data['id']}/")
    assert polled.data["status"] == VehicleSpecDraftStatus.FAILED
    assert polled.data["error_message"] == (
        "Couldn't fetch the spec page (RuntimeError). Please try again, or fill in the form by hand."
    )


# --- Create: SSRF guard + brand check ------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://paultan.org/research/bmw/3-series/",  # a model page, not a variant
        "https://paultan.org/2025/06/12/2025-bmw-3-series-updated-again/",  # news article
        "http://paultan.org/research/bmw/3-series/g20-lci-2/330i-m-sport-2025/",  # not https
        "https://paultan.org.evil.com/research/bmw/3-series/g20-lci-2/330i-m-sport-2025/",
        "https://169.254.169.254/research/bmw/3-series/g20-lci-2/330i-m-sport-2025/",
        "",
    ],
)
def test_create_rejects_any_url_that_is_not_a_paultan_variant_page(admin_client, brand, monkeypatch, url):
    calls = []
    monkeypatch.setattr(RENDER, lambda u: calls.append(u))

    response = admin_client.post(
        "/api/vehicles/spec-drafts/", {"brand": brand.pk, "source_url": url}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "source_url" in response.data
    assert VehicleSpecDraft.objects.count() == 0
    assert calls == []  # nothing was ever fetched


def test_create_rejects_a_variant_page_from_a_different_brand(admin_client, brand, monkeypatch):
    calls = []
    monkeypatch.setattr(RENDER, lambda u: calls.append(u))
    porsche_url = "https://paultan.org/research/porsche/macan/95b-2/macan-2024/"

    response = admin_client.post(
        "/api/vehicles/spec-drafts/", {"brand": brand.pk, "source_url": porsche_url}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["source_url"] == ["This page is not a BMW variant."]
    assert calls == []


@pytest.mark.parametrize("extra", [{}, {"model_name_query": ""}], ids=["omitted", "blank"])
def test_create_derives_model_name_from_the_url_when_not_given(admin_client, brand, monkeypatch, extra):
    monkeypatch.setattr(RENDER, lambda url: page(title=TITLE_330I_2025, text=TEXT_330I_2025))

    response = admin_client.post(
        "/api/vehicles/spec-drafts/", {"brand": brand.pk, "source_url": URL_330I_2025, **extra}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert VehicleSpecDraft.objects.get(pk=response.data["id"]).model_name_query == "3 Series"


# --- Draft never creates a VehicleModel; only the real save does --------


def test_creating_and_fetching_a_draft_never_creates_a_vehiclemodel(admin_client, brand, monkeypatch):
    monkeypatch.setattr(RENDER, lambda url: page(title=TITLE_330I_2025, text=TEXT_330I_2025))

    response = admin_client.post(
        "/api/vehicles/spec-drafts/",
        {"brand": brand.pk, "source_url": URL_330I_2025, "model_name_query": "3 Series", "trim_query": "330i M Sport"},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert VehicleModel.objects.count() == 0
    polled = admin_client.get(f"/api/vehicles/spec-drafts/{response.data['id']}/")
    assert polled.data["status"] == VehicleSpecDraftStatus.READY
    assert polled.data["proposed_data"]["msrp"] == "313800"
    assert VehicleModel.objects.count() == 0


def test_only_the_explicit_save_creates_a_vehiclemodel_and_writes_the_normal_audit_log(admin_client, draft):
    """The admin's own save goes through the exact same VehicleModelViewSet.
    create() path as manual entry - the EXISTING AuditedModelViewSet audit
    logging still fires; no new audit code was written for this feature."""
    create_response = admin_client.post(
        "/api/vehicles/models/",
        {
            "brand": draft.brand.pk,
            "name": "3 Series",
            "trim": "330i M Sport",
            "body_segment": BodySegment.SEDAN,
            "msrp": "313800.00",
            "engine_capacity_kw": "189.76",
            "powertrain": "petrol",
            "engine_capacity_cc": 1998,
        },
        format="json",
    )
    assert create_response.status_code == status.HTTP_201_CREATED
    vehicle_id = create_response.data["id"]
    log = AuditLog.objects.get(
        resource_type="vehicles.VehicleModel", resource_id=str(vehicle_id), action=AuditActionCategory.CREATE
    )
    assert log.after_data["name"] == "3 Series"

    patch_response = admin_client.patch(
        f"/api/vehicles/spec-drafts/{draft.pk}/",
        {"status": VehicleSpecDraftStatus.APPROVED, "approved_vehicle": vehicle_id},
        format="json",
    )
    assert patch_response.status_code == status.HTTP_200_OK
    draft.refresh_from_db()
    assert draft.status == VehicleSpecDraftStatus.APPROVED
    assert draft.approved_vehicle_id == vehicle_id


# --- catalog-models / catalog-variants -----------------------------------


def test_catalog_models_parses_the_brand_page_and_caches_it(admin_client, monkeypatch):
    calls = []

    def _render(url):
        calls.append(url)
        return page(links=BRAND_PAGE_LINKS)

    monkeypatch.setattr(RENDER, _render)

    first = admin_client.get("/api/vehicles/spec-drafts/catalog-models/", {"brand": "BMW"})
    second = admin_client.get("/api/vehicles/spec-drafts/catalog-models/", {"brand": "BMW"})

    assert first.status_code == status.HTTP_200_OK
    assert first.data["brand_slug"] == "bmw"
    assert [m["name"] for m in first.data["models"]] == ["BMW 3 Series", "BMW X1"]
    assert "message" not in first.data
    assert second.data == first.data
    assert calls == ["https://paultan.org/research/bmw/"]  # second request served from cache


def test_catalog_models_for_a_brand_paultan_does_not_cover_is_empty_with_a_message(admin_client, monkeypatch):
    calls = []

    def _render(url):
        calls.append(url)
        return page(status_code=404)

    monkeypatch.setattr(RENDER, _render)

    response = admin_client.get("/api/vehicles/spec-drafts/catalog-models/", {"brand": "Nonexistent"})
    admin_client.get("/api/vehicles/spec-drafts/catalog-models/", {"brand": "Nonexistent"})

    assert response.status_code == status.HTTP_200_OK
    assert response.data["models"] == []
    assert response.data["message"] == "No paultan.org buyer's-guide page for this brand"
    assert len(calls) == 1  # a real 404 IS cached


def test_catalog_models_does_not_cache_an_empty_listing_from_a_non_404_page(admin_client, monkeypatch):
    # e.g. a bot-check page served with 200 - no model cards on it.
    monkeypatch.setattr(RENDER, lambda url: page(text="Checking your browser..."))
    blip = admin_client.get("/api/vehicles/spec-drafts/catalog-models/", {"brand": "BMW"})
    assert blip.status_code == status.HTTP_200_OK
    assert blip.data["models"] == []

    monkeypatch.setattr(RENDER, lambda url: page(links=BRAND_PAGE_LINKS))
    retried = admin_client.get("/api/vehicles/spec-drafts/catalog-models/", {"brand": "BMW"})
    assert [m["name"] for m in retried.data["models"]] == ["BMW 3 Series", "BMW X1"]
    assert "message" not in retried.data


def test_catalog_models_returns_502_and_does_not_cache_when_the_site_is_unreachable(admin_client, monkeypatch):
    def _boom(url):
        raise TimeoutError("timed out")

    monkeypatch.setattr(RENDER, _boom)
    failed = admin_client.get("/api/vehicles/spec-drafts/catalog-models/", {"brand": "BMW"})
    assert failed.status_code == status.HTTP_502_BAD_GATEWAY

    monkeypatch.setattr(RENDER, lambda url: page(links=BRAND_PAGE_LINKS))
    retried = admin_client.get("/api/vehicles/spec-drafts/catalog-models/", {"brand": "BMW"})
    assert retried.status_code == status.HTTP_200_OK
    assert len(retried.data["models"]) == 2


def test_catalog_variants_parses_the_model_page_and_caches_it(admin_client, monkeypatch):
    calls = []

    def _render(url):
        calls.append(url)
        return page(links=MODEL_PAGE_LINKS)

    monkeypatch.setattr(RENDER, _render)

    first = admin_client.get("/api/vehicles/spec-drafts/catalog-variants/", {"model_url": MODEL_URL})
    admin_client.get("/api/vehicles/spec-drafts/catalog-variants/", {"model_url": MODEL_URL})

    assert first.status_code == status.HTTP_200_OK
    assert [v["year"] for v in first.data["variants"]] == [2026, 2026, 2025]
    assert first.data["variants"][0]["msrp"] == "267800"
    assert calls == [MODEL_URL]


def test_catalog_variants_does_not_cache_an_empty_listing_from_a_non_404_page(admin_client, monkeypatch):
    monkeypatch.setattr(RENDER, lambda url: page(text="Checking your browser..."))
    blip = admin_client.get("/api/vehicles/spec-drafts/catalog-variants/", {"model_url": MODEL_URL})
    assert blip.status_code == status.HTTP_200_OK
    assert blip.data["variants"] == []
    assert blip.data["message"] == "No variants listed for this model on paultan.org"

    monkeypatch.setattr(RENDER, lambda url: page(links=MODEL_PAGE_LINKS))
    retried = admin_client.get("/api/vehicles/spec-drafts/catalog-variants/", {"model_url": MODEL_URL})
    assert len(retried.data["variants"]) == 3
    assert "message" not in retried.data


@pytest.mark.parametrize(
    "model_url",
    [
        "https://evil.example.com/research/bmw/3-series/",
        "https://paultan.org/research/bmw/",  # brand page, not a model page
        "https://paultan.org/2025/06/12/some-news/",
        "",
    ],
)
def test_catalog_variants_rejects_a_non_model_url_without_fetching(admin_client, monkeypatch, model_url):
    calls = []
    monkeypatch.setattr(RENDER, lambda u: calls.append(u))

    response = admin_client.get("/api/vehicles/spec-drafts/catalog-variants/", {"model_url": model_url})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert calls == []


def test_spec_draft_endpoints_require_admin_role(regular_user, brand):
    client = APIClient()
    client.force_authenticate(user=regular_user)

    assert client.post(
        "/api/vehicles/spec-drafts/", {"brand": brand.pk, "source_url": URL_330I_2025}, format="json"
    ).status_code == status.HTTP_403_FORBIDDEN
    assert client.get(
        "/api/vehicles/spec-drafts/catalog-models/", {"brand": "BMW"}
    ).status_code == status.HTTP_403_FORBIDDEN
    assert client.get(
        "/api/vehicles/spec-drafts/catalog-variants/", {"model_url": MODEL_URL}
    ).status_code == status.HTTP_403_FORBIDDEN
