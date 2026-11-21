"""retire_formula_subscription_plans (audit batch 5): dry run by default, one
transaction on --apply, idempotent, archives (never deletes) only the plans the
old msrp/40 seed formula priced, leaves and reports a real provider quote,
audits every change, never touches existing audit rows."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditActionCategory, AuditLog
from apps.policy.models import SubscriptionPlan
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal


def make_vehicle(brand, name, msrp):
    vehicle = VehicleModel.objects.create(
        brand=brand, name=name, trim="X", body_segment=BodySegment.SEDAN, msrp=msrp,
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    vehicle.refresh_from_db()
    return vehicle


@pytest.fixture
def plans(create_user):
    brand = Brand.objects.create(name="PlanBrand", tier_code="2")
    admin = create_user(email="admin@flexidrivemy.local", role="admin")
    # A: seeded at today's price (msrp / 40 = 6,645.00)
    a = make_vehicle(brand, "A", "265800.00")
    # B: seeded when it cost 245,800.00 (6,145.00); the catalog correction later raised it to
    # 265,800.00 - the audit log still holds the earlier price in its before snapshot.
    b = make_vehicle(brand, "B", "265800.00")
    AuditLog.objects.create(
        actor=admin, actor_email=admin.email, action=AuditActionCategory.UPDATE,
        resource_type="vehicles.VehicleModel", resource_id=str(b.pk),
        before_data={"msrp": "245800.00"}, after_data={"msrp": "265800.00"},
    )
    # C: a real provider quote - matches neither today's nor any earlier price
    c = make_vehicle(brand, "C", "300000.00")
    # D: a fee that equals msrp/40 of a price that was NEVER this car's (no audit evidence)
    d = make_vehicle(brand, "D", "300000.00")
    # E: already archived
    e = make_vehicle(brand, "E", "280000.00")
    created = {
        "a": SubscriptionPlan.objects.create(vehicle=a, fee_monthly="6645.00"),
        "b": SubscriptionPlan.objects.create(vehicle=b, fee_monthly="6145.00"),
        "c": SubscriptionPlan.objects.create(vehicle=c, fee_monthly="8200.00"),
        "d": SubscriptionPlan.objects.create(vehicle=d, fee_monthly="6145.00"),
        "e": SubscriptionPlan.objects.create(vehicle=e, fee_monthly="7000.00", is_active=False),
    }
    return created


def run(*args):
    out = StringIO()
    call_command("retire_formula_subscription_plans", *args, stdout=out)
    return out.getvalue()


def state():
    return {"plans": list(SubscriptionPlan.objects.order_by("pk").values()), "audit": AuditLog.objects.count()}


def test_the_dry_run_is_the_default_and_writes_nothing(plans):
    before = state()

    output = run()

    assert state() == before
    assert output.startswith("DRY RUN - nothing will be changed")
    assert "Dry run only. Re-run with --apply" in output
    assert "2 to archive; 2 kept as provider quotes; 4 active plan(s) in total" in output
    assert f"ARCHIVE  #{plans['a'].pk}" in output and "equals msrp/40 (RM 265,800.00 / 40)" in output
    assert "earlier price RM 245,800.00" in output and "audit log row #" in output
    assert f"KEEP     #{plans['c'].pk}" in output and "treated as a real provider quote" in output


def test_apply_archives_exactly_the_formula_plans_and_leaves_a_real_quote(plans):
    run("--apply", "--actor", "admin@flexidrivemy.local")

    active = {p.pk for p in SubscriptionPlan.objects.filter(is_active=True)}
    assert active == {plans["c"].pk, plans["d"].pk}
    # soft delete only
    assert SubscriptionPlan.objects.count() == 5
    for key in ("a", "b"):
        plans[key].refresh_from_db()
        assert plans[key].is_active is False and plans[key].archived_by_parent is False


def test_a_plan_whose_fee_matches_no_proven_price_is_never_guessed_at(plans):
    output = run()

    assert f"KEEP     #{plans['d'].pk}" in output  # 6,145.00 is 245,800/40, but this car never cost that


def test_apply_writes_one_audit_row_per_archived_plan_and_never_touches_existing_ones(plans):
    existing = list(AuditLog.objects.values())

    run("--apply", "--actor", "admin@flexidrivemy.local")

    assert AuditLog.objects.count() == len(existing) + 2
    new_rows = AuditLog.objects.exclude(pk__in=[row["id"] for row in existing])
    assert {row.action for row in new_rows} == {AuditActionCategory.ARCHIVE}
    assert {row.resource_type for row in new_rows} == {"policy.SubscriptionPlan"}
    assert {row.actor_email for row in new_rows} == {"admin@flexidrivemy.local"}
    assert {int(row.resource_id) for row in new_rows} == {plans["a"].pk, plans["b"].pk}
    sample = new_rows.first()
    assert sample.before_data["is_active"] is True and sample.after_data["is_active"] is False
    assert "retire_formula_subscription_plans" in sample.after_data["correction"]
    assert list(AuditLog.objects.filter(pk__in=[row["id"] for row in existing]).values()) == existing


def test_a_second_run_changes_nothing(plans):
    run("--apply", "--actor", "admin@flexidrivemy.local")
    after_first = state()

    output = run("--apply", "--actor", "admin@flexidrivemy.local")
    dry = run()

    assert state() == after_first
    assert "0 to archive; 2 kept as provider quotes; 2 active plan(s) in total" in output
    assert "Nothing to change." in output and "0 to archive" in dry


def test_the_archived_plan_stops_shadowing_the_estimate(plans):
    from apps.policy.subscription_pricing import resolve_subscription_fee

    vehicle = plans["a"].vehicle
    assert resolve_subscription_fee(vehicle, 36, "standard").source == "quote"

    run("--apply")

    assert resolve_subscription_fee(vehicle, 36, "standard").source == "estimate"


def test_without_an_actor_the_audit_rows_are_attributed_to_the_system(plans):
    run("--apply")

    row = AuditLog.objects.filter(action=AuditActionCategory.ARCHIVE).first()
    assert row.actor is None and row.actor_email == ""


def test_an_unknown_actor_is_refused_before_anything_is_written(plans):
    before = state()

    with pytest.raises(CommandError):
        run("--apply", "--actor", "nobody@example.com")

    assert state() == before
