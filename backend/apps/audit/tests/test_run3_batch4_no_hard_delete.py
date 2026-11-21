"""Run 3 fix batch 4 (F-32): Django admin no longer hard-deletes training runs,
PDF export jobs, financial profiles, saved comparisons, users or JWT tokens - the
delete page answers 403 and the changelist offers no "Delete selected". The
catalog and policy tables already archive instead (AuditedModelAdmin)."""

import datetime

import pytest
from django.contrib import admin
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.exports.models import PDFExportJob
from apps.ml.models import MLTrainingRun
from apps.profiles.models import FinancialProfile
from apps.scenarios.models import SavedScenario
from apps.users.models import User
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser_client(django_user_model):
    client = Client()
    client.force_login(django_user_model.objects.create_superuser(email="super@example.com", password="pw"))
    return client


@pytest.fixture
def rows(regular_user):
    vehicle = VehicleModel.objects.create(
        brand=Brand.objects.create(name="DeleteBrand", tier_code="2"), name="M", trim="X",
        body_segment=BodySegment.SEDAN, msrp="300000.00", engine_capacity_kw="150.00", powertrain="petrol",
        engine_capacity_cc=1998,
    )
    outstanding = OutstandingToken.objects.create(
        user=regular_user, jti="a" * 32, token="t", expires_at=timezone.now() + datetime.timedelta(days=1),
    )
    return {
        MLTrainingRun: MLTrainingRun.objects.create(),
        PDFExportJob: PDFExportJob.objects.create(user=regular_user),
        FinancialProfile: FinancialProfile.objects.create(
            user=regular_user, monthly_budget="5000.00", preferred_tenure_months=48, annual_mileage_band="standard",
            ownership_preference="retain",
        ),
        SavedScenario: SavedScenario.objects.create(user=regular_user, title="Kept", vehicle=vehicle, payload={}),
        User: regular_user,
        OutstandingToken: outstanding,
        BlacklistedToken: BlacklistedToken.objects.create(token=outstanding),
    }


MODELS = [MLTrainingRun, PDFExportJob, FinancialProfile, SavedScenario, User, OutstandingToken, BlacklistedToken]


def admin_url(model, view, *args):
    return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_{view}", args=args)


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m._meta.label)
def test_the_delete_page_is_forbidden_and_the_row_stays(superuser_client, rows, model):
    row = rows[model]

    assert superuser_client.get(admin_url(model, "delete", row.pk)).status_code == 403
    assert superuser_client.post(admin_url(model, "delete", row.pk), {"post": "yes"}).status_code == 403
    assert model.objects.filter(pk=row.pk).exists()


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m._meta.label)
def test_the_changelist_offers_no_delete_selected(superuser_client, rows, model):
    response = superuser_client.get(admin_url(model, "changelist"))

    assert response.status_code == 200
    assert b"delete_selected" not in response.content
    request = response.wsgi_request
    assert "delete_selected" not in admin.site._registry[model].get_actions(request)


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m._meta.label)
def test_the_bulk_delete_action_cannot_be_posted(superuser_client, rows, model):
    row = rows[model]

    superuser_client.post(admin_url(model, "changelist"), {
        "action": "delete_selected", "_selected_action": [row.pk], "post": "yes",
    })

    assert model.objects.filter(pk=row.pk).exists()


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m._meta.label)
def test_the_change_page_still_opens(superuser_client, rows, model):
    assert superuser_client.get(admin_url(model, "change", rows[model].pk)).status_code == 200
