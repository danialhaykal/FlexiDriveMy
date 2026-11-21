"""retire_flat_residual_seed (audit batch 4): dry run by default, one
transaction on --apply, idempotent, archives (never deletes) only the rows
that still equal the old flat seed grid, audits every change, never touches
existing audit rows."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditActionCategory, AuditLog
from apps.policy.management.commands.retire_flat_residual_seed import FLAT_SEED_GRID
from apps.policy.models import ResidualValueMatrix
from apps.vehicles.models import Brand

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded(create_user):
    """Two brands carrying the old flat grid (12 rows each), plus one edited
    row, one row outside the grid's tenures, and an already-archived row."""
    toyota = Brand.objects.create(name="Toyota", tier_code="1")
    bmw = Brand.objects.create(name="BMW", tier_code="2")
    for brand in (toyota, bmw):
        for tenure, bands in FLAT_SEED_GRID.items():
            for band, ratio in bands.items():
                ResidualValueMatrix.objects.create(
                    brand=brand, tenure_months=tenure, mileage_band=band, residual_value_ratio=ratio
                )
    edited = ResidualValueMatrix.objects.get(brand=toyota, tenure_months=48, mileage_band="standard")
    edited.residual_value_ratio = Decimal("0.4700")  # the flat seed was 0.4200: an admin edited it
    edited.save()
    outside = ResidualValueMatrix.objects.create(
        brand=bmw, tenure_months=72, mileage_band="standard", residual_value_ratio="0.2000"
    )
    already = ResidualValueMatrix.objects.get(brand=bmw, tenure_months=36, mileage_band="low")
    already.is_active = False
    already.save()
    admin = create_user(email="admin@flexidrivemy.local", role="admin")
    AuditLog.objects.create(
        actor=admin, actor_email=admin.email, action=AuditActionCategory.CREATE,
        resource_type="policy.ResidualValueMatrix", resource_id="1", after_data={"seeded": True},
    )
    return {"toyota": toyota, "bmw": bmw, "edited": edited, "outside": outside, "already": already}


def run(*args):
    out = StringIO()
    call_command("retire_flat_residual_seed", *args, stdout=out)
    return out.getvalue()


def state():
    return {"rows": list(ResidualValueMatrix.objects.order_by("pk").values()), "audit": AuditLog.objects.count()}


def test_the_dry_run_is_the_default_and_writes_nothing(seeded):
    before = state()

    output = run()

    assert state() == before
    assert output.startswith("DRY RUN - nothing will be changed")
    assert "Dry run only. Re-run with --apply" in output
    # 24 grid rows - 1 edited - 1 already archived = 22 to archive
    assert "22 to archive; 2 kept as overrides" in output
    assert "KEEP     #" in output and "flat seed was 0.4200: edited, so a real override" in output
    assert "not part of the flat seed grid: a real override" in output


def test_apply_archives_exactly_the_rows_that_equal_the_flat_grid(seeded):
    run("--apply", "--actor", "admin@flexidrivemy.local")

    active = ResidualValueMatrix.objects.filter(is_active=True)
    assert {row.pk for row in active} == {seeded["edited"].pk, seeded["outside"].pk}
    # soft delete only - nothing is hard-deleted
    assert ResidualValueMatrix.objects.count() == 25
    # 22 archived now + the one that was already archived
    assert ResidualValueMatrix.objects.filter(is_active=False, archived_by_parent=False).count() == 23


def test_an_edited_row_is_left_alone_and_reported_as_an_override(seeded):
    output = run("--apply", "--actor", "admin@flexidrivemy.local")

    seeded["edited"].refresh_from_db()
    assert seeded["edited"].is_active is True
    assert seeded["edited"].residual_value_ratio == Decimal("0.4700")
    assert f"KEEP     #{seeded['edited'].pk} Toyota / 48 months / standard: 0.4700" in output


def test_apply_writes_one_audit_row_per_archived_row_and_never_touches_existing_ones(seeded):
    existing = list(AuditLog.objects.values())

    run("--apply", "--actor", "admin@flexidrivemy.local")

    assert AuditLog.objects.count() == len(existing) + 22
    new_rows = AuditLog.objects.exclude(pk__in=[row["id"] for row in existing])
    assert {row.action for row in new_rows} == {AuditActionCategory.ARCHIVE}
    assert {row.resource_type for row in new_rows} == {"policy.ResidualValueMatrix"}
    assert {row.actor_email for row in new_rows} == {"admin@flexidrivemy.local"}
    sample = new_rows.first()
    assert sample.before_data["is_active"] is True and sample.after_data["is_active"] is False
    assert "retire_flat_residual_seed" in sample.after_data["correction"]
    assert list(AuditLog.objects.filter(pk__in=[row["id"] for row in existing]).values()) == existing


def test_a_second_run_changes_nothing(seeded):
    run("--apply", "--actor", "admin@flexidrivemy.local")
    after_first = state()

    output = run("--apply", "--actor", "admin@flexidrivemy.local")
    dry = run()

    assert state() == after_first
    assert "0 to archive; 2 kept as overrides" in output
    assert "Nothing to change." in output
    assert "0 to archive" in dry


def test_without_an_actor_the_audit_rows_are_attributed_to_the_system(seeded):
    run("--apply")

    row = AuditLog.objects.filter(action=AuditActionCategory.ARCHIVE).first()
    assert row.actor is None and row.actor_email == ""


def test_an_unknown_actor_is_refused_before_anything_is_written(seeded):
    before = state()

    with pytest.raises(CommandError):
        run("--apply", "--actor", "nobody@example.com")

    assert state() == before


def test_the_flat_grid_constant_is_the_old_seed_exactly():
    assert FLAT_SEED_GRID[36]["standard"] == "0.5000"
    assert FLAT_SEED_GRID[48] == {"low": "0.4700", "standard": "0.4200", "high": "0.3800", "very_high": "0.3300"}
    assert FLAT_SEED_GRID[60]["very_high"] == "0.2700"
    assert sum(len(bands) for bands in FLAT_SEED_GRID.values()) == 12
