from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from apps.audit.models import AuditActionCategory, AuditLog
from apps.scenarios.models import SavedScenario
from apps.users.models import User
from apps.vehicles.models import Brand, VehicleModel, VehicleSpecDraft

pytestmark = pytest.mark.django_db


def _vehicle(brand, name, trim, is_active=True):
    return VehicleModel.objects.create(
        brand=brand, name=name, trim=trim, body_segment="sedan",
        msrp=Decimal("100000.00"), engine_capacity_kw=Decimal("100.00"), is_active=is_active,
    )


def _token(user):
    now = timezone.now()
    return OutstandingToken.objects.create(
        user=user, jti=f"jti-{user.pk}", token="x", created_at=now, expires_at=now + timedelta(days=7)
    )


@pytest.fixture
def dev_data(create_user):
    toyota = Brand.objects.create(name="Toyota", tier_code="2")
    bmw = Brand.objects.create(name="BMW", tier_code="1")
    honda = Brand.objects.create(name="Honda", tier_code="4", is_active=False)
    perodua = Brand.objects.create(name="Perodua", tier_code="5", is_active=False)
    debug = Brand.objects.create(name="DebugBrand", is_active=False)
    Brand.objects.create(name="Volkswagen", is_active=False)
    Brand.objects.create(name="XlsxBrand", is_active=False)

    alphard = _vehicle(toyota, "Alphard", "2.5L")
    _vehicle(honda, "City", "V", is_active=False)
    _vehicle(perodua, "Myvi", "AV", is_active=False)
    _vehicle(bmw, "Test Model", "Base", is_active=False)
    _vehicle(toyota, "QA Crash Test", "Test", is_active=False)

    admin = create_user(email="admin@flexidrivemy.local", role="admin")
    loadtest = create_user(email="loadtest@flexidrivemy.local")
    _token(loadtest)
    create_user(email="qa.livetest.2026-10-05@example.com")
    tester = create_user(email="qa.tester@example.com")
    _token(tester)
    create_user(email="qa.tester+duplicate-3@example.com")

    # An audit row naming a target user as actor (actor FK is SET_NULL).
    AuditLog.objects.create(
        actor=tester, actor_email=tester.email, action=AuditActionCategory.CREATE,
        resource_type="vehicles.Brand", resource_id=str(debug.pk),
    )
    AuditLog.objects.create(
        actor=admin, actor_email=admin.email, action=AuditActionCategory.ARCHIVE,
        resource_type="vehicles.Brand", resource_id=str(debug.pk),
    )

    SavedScenario.objects.create(user=admin, title="QA test - Alphard 60mo", vehicle=alphard, payload={})
    SavedScenario.objects.create(user=admin, title="Toyota Alphard 2.5L - 60mo (fresh save)", vehicle=alphard, payload={})
    VehicleSpecDraft.objects.create(brand=bmw, model_name_query="3 Series", requested_by=admin)
    VehicleSpecDraft.objects.create(
        brand=toyota, model_name_query="Alphard", requested_by=admin, approved_vehicle=alphard
    )
    return {"debug": debug, "alphard": alphard}


def _run(*args):
    out = StringIO()
    call_command("cleanup_dev_test_data", *args, stdout=out)
    return out.getvalue()


def _snapshot():
    return {
        "brands": set(Brand.objects.values_list("name", flat=True)),
        "vehicles": set(VehicleModel.objects.values_list("name", flat=True)),
        "users": set(User.objects.values_list("email", "is_active")),
        "scenarios": set(SavedScenario.objects.values_list("title", flat=True)),
        "drafts": VehicleSpecDraft.objects.count(),
        "audit": list(AuditLog.objects.order_by("pk").values()),
        "tokens": list(OutstandingToken.objects.order_by("pk").values()),
    }


def test_dry_run_is_the_default_and_changes_nothing(dev_data):
    before = _snapshot()

    output = _run()

    assert output.startswith("DRY RUN")
    assert "vehicles.Brand#" in output and "(DebugBrand)" in output
    assert "qa.tester@example.com): deleting would modify audit.AuditLog x1, token_blacklist.OutstandingToken x1" in output
    assert _snapshot() == before


def test_apply_removes_every_target(dev_data):
    _run("--apply")

    assert not Brand.objects.filter(name__in=["DebugBrand", "Volkswagen", "XlsxBrand"]).exists()
    assert not VehicleModel.objects.filter(name__in=["Test Model", "QA Crash Test"]).exists()
    assert not User.objects.filter(email__in=["qa.livetest.2026-10-05@example.com",
                                              "qa.tester+duplicate-3@example.com"]).exists()
    assert not SavedScenario.objects.filter(title="QA test - Alphard 60mo").exists()
    assert not VehicleSpecDraft.objects.filter(approved_vehicle__isnull=True).exists()


def test_apply_keeps_loadtest_user_real_archived_brands_and_every_audit_and_token_row(dev_data):
    audit_before = list(AuditLog.objects.order_by("pk").values())
    tokens_before = list(OutstandingToken.objects.order_by("pk").values())

    _run("--apply")

    assert User.objects.get(email="loadtest@flexidrivemy.local").is_active
    assert set(Brand.objects.values_list("name", flat=True)) == {"Toyota", "BMW", "Honda", "Perodua"}
    assert set(VehicleModel.objects.values_list("name", flat=True)) == {"Alphard", "City", "Myvi"}
    assert SavedScenario.objects.filter(title="Toyota Alphard 2.5L - 60mo (fresh save)").exists()
    assert VehicleSpecDraft.objects.filter(approved_vehicle=dev_data["alphard"]).count() == 1
    assert list(AuditLog.objects.order_by("pk").values()) == audit_before
    assert list(OutstandingToken.objects.order_by("pk").values()) == tokens_before


def test_a_user_referenced_by_an_audit_log_is_deactivated_not_deleted(dev_data):
    _run("--apply")

    tester = User.objects.get(email="qa.tester@example.com")
    assert tester.is_active is False
    assert AuditLog.objects.filter(actor=tester).count() == 1  # actor FK not nulled


def test_a_target_protected_by_a_non_target_row_is_skipped_and_reported(dev_data):
    # A live (non-target) vehicle still under DebugBrand PROTECTs it.
    _vehicle(dev_data["debug"], "Real Car", "X")

    output = _run("--apply")

    assert "blocked (PROTECT) by rows outside the target list" in output
    assert Brand.objects.filter(name="DebugBrand").exists()
    assert not Brand.objects.filter(name="Volkswagen").exists()


def test_a_second_dry_run_after_apply_finds_nothing(dev_data):
    _run("--apply")

    output = _run()

    assert "== Would delete 0 target row(s) ==" in output
    assert "== Would deactivate 0 user(s) instead of deleting ==" in output
