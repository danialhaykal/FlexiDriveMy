"""apply_catalog_corrections (audit batch 1): dry run by default, one
transaction on --apply, idempotent, exact-match targets only, every change
audited, existing audit rows never touched."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditActionCategory, AuditLog
from apps.policy.models import SubscriptionPlan
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

# (brand, name, trim, msrp, kw, year) as they are in the dev DB before the corrections.
STARTING_ROWS = [
    ("BMW", "3 Series", "320i Sport", "245800.00", "135.00", None),
    ("Mercedes-Benz", "C-Class", "C200 Avantgarde", "269900.00", "150.00", None),
    ("Lexus", "ES", "250 Luxury", "294200.00", "151.00", None),
    ("Porsche", "911", "Carrera", "650000.00", "283.00", 2026),
    ("Porsche", "Macan", "Base", "449000.00", "195.00", None),
    ("Porsche", "Macan Electric", "Macan RWD", "575000.00", "261.10", 2026),
    ("Volvo", "XC60", "B5 Core", "328888.00", "180.93", 2026),
    ("Volvo", "XC90", "Ultra T8", "434888.00", "233.15", 2026),
    ("Toyota", "Alphard", "2.5L", "349900.00", "140.00", None),
]


@pytest.fixture
def catalog(create_user):
    brands = {name: Brand.objects.create(name=name, tier_code="2") for name in
              {"BMW", "Mercedes-Benz", "Lexus", "Porsche", "Volvo", "Toyota"}}
    brands["Honda"] = Brand.objects.create(name="Honda", tier_code="4", is_active=False)
    for brand, name, trim, msrp, kw, year in STARTING_ROWS:
        VehicleModel.objects.create(
            brand=brands[brand], name=name, trim=trim, body_segment=BodySegment.SEDAN,
            msrp=msrp, engine_capacity_kw=kw, model_year=year,
        )
    VehicleModel.objects.create(
        brand=brands["Honda"], name="City", trim="V", body_segment=BodySegment.SEDAN,
        msrp="99999.99", engine_capacity_kw="90.00", is_active=False,
    )
    alphard = VehicleModel.objects.get(name="Alphard", trim="2.5L")
    SubscriptionPlan.objects.create(
        vehicle=alphard, fee_monthly="8750.00", insurance_annual="4500.00",
        road_tax_annual="2500.00", maintenance_annual="2500.00",
    )
    # A pre-existing audit row, to prove existing rows are never touched.
    admin = create_user(email="admin@flexidrivemy.local", role="admin")
    AuditLog.objects.create(
        actor=admin, actor_email=admin.email, action=AuditActionCategory.CREATE,
        resource_type="vehicles.VehicleModel", resource_id=str(alphard.pk), after_data={"name": "Alphard"},
    )
    return brands


def run(*args):
    out = StringIO()
    call_command("apply_catalog_corrections", *args, stdout=out)
    return out.getvalue()


def vehicle(name, trim):
    return VehicleModel.objects.get(name=name, trim=trim)


def state():
    return {
        "vehicles": list(VehicleModel.objects.order_by("pk").values()),
        "plans": list(SubscriptionPlan.objects.order_by("pk").values()),
        "audit": AuditLog.objects.count(),
    }


def test_the_dry_run_is_the_default_and_changes_nothing(catalog):
    before = state()

    output = run()

    assert output.startswith("DRY RUN")
    assert "msrp: 245800.00 -> 265800.00" in output
    assert "would ARCHIVE via archiving.archive_vehicle" in output
    assert "would CREATE Toyota / Alphard / 2.4 Executive Lounge" in output
    assert "FLAG" not in output  # the Macan price is verified now (RM469,000, paultan 17 Mar 2026)
    assert "== Summary: 10 change(s) (8 update(s), 1 archive, 1 create)" in output
    assert state() == before


def test_apply_updates_exactly_the_listed_rows(catalog):
    run("--apply")

    bmw = vehicle("3 Series", "320i Sport")
    assert (bmw.msrp, bmw.engine_capacity_cc, bmw.powertrain, bmw.model_year, bmw.engine_capacity_kw) == (
        Decimal("265800.00"), 1998, "petrol", 2025, Decimal("135.00"))
    merc = vehicle("C-Class", "C200 Avantgarde")
    assert (merc.msrp, merc.engine_capacity_cc, merc.powertrain, merc.model_year) == (
        Decimal("292888.00"), 1496, "mild_hybrid", 2026)
    lexus = vehicle("ES", "250 Luxury")
    assert (lexus.msrp, lexus.engine_capacity_cc, lexus.powertrain, lexus.model_year) == (
        Decimal("356888.00"), 2487, "petrol", None)  # year left alone
    carrera = vehicle("911", "Carrera")
    assert (carrera.msrp, carrera.engine_capacity_cc, carrera.powertrain, carrera.engine_capacity_kw) == (
        Decimal("1430000.00"), 2981, "petrol", Decimal("290.00"))
    macan = vehicle("Macan", "Base")
    assert (macan.msrp, macan.engine_capacity_cc, macan.powertrain, macan.engine_capacity_kw) == (
        Decimal("469000.00"), 1984, "petrol", Decimal("195.00"))  # petrol Macan returned at RM469,000
    electric = vehicle("Macan Electric", "Macan RWD")
    assert (electric.msrp, electric.engine_capacity_cc, electric.powertrain, electric.engine_capacity_kw) == (
        Decimal("575000.00"), None, "bev", Decimal("261.10"))
    xc60 = vehicle("XC60", "B5 Core")
    assert (xc60.msrp, xc60.engine_capacity_cc, xc60.powertrain, xc60.engine_capacity_kw) == (
        Decimal("328888.00"), 1969, "mild_hybrid", Decimal("180.93"))
    xc90 = vehicle("XC90", "Ultra T8")
    assert (xc90.msrp, xc90.engine_capacity_cc, xc90.powertrain, xc90.engine_capacity_kw) == (
        Decimal("434888.00"), 1969, "phev", Decimal("233.15"))
    # Every corrected row is now complete.
    assert all(v.spec_complete for v in VehicleModel.objects.filter(is_active=True))


def test_apply_archives_the_old_alphard_through_the_helper_and_creates_the_new_one(catalog):
    old = vehicle("Alphard", "2.5L")
    plan = SubscriptionPlan.objects.get(vehicle=old)

    run("--apply")

    old.refresh_from_db()
    plan.refresh_from_db()
    assert (old.is_active, old.archived_by_parent) == (False, False)  # archived on its own, never edited
    assert old.msrp == Decimal("349900.00") and old.powertrain == ""  # row itself untouched
    assert (plan.is_active, plan.archived_by_parent) == (False, True)  # dependent handled by archiving.py
    new = vehicle("Alphard", "2.4 Executive Lounge")
    assert (new.body_segment, new.msrp, new.engine_capacity_cc, new.powertrain, new.engine_capacity_kw,
            new.model_year, new.is_active) == (
        BodySegment.MPV, Decimal("548000.00"), 2393, "petrol", Decimal("201.53"), 2026, True)
    assert not SubscriptionPlan.objects.filter(vehicle=new).exists()  # Batch 4, expected


def test_a_saved_comparison_on_the_archived_alphard_still_opens(catalog, create_user):
    """Why the 2.5L is archived rather than edited or deleted: the saved
    comparison keeps its foreign key and still loads (scenarios are
    snapshots, not filtered on the vehicle being active)."""
    from rest_framework.test import APIClient

    from apps.scenarios.models import SavedScenario

    owner = create_user(email="rider@example.com")
    scenario = SavedScenario.objects.create(
        user=owner, title="Toyota Alphard 2.5L - 60mo (fresh save)",
        vehicle=vehicle("Alphard", "2.5L"), payload={"tco_net": "389263.75"},
    )
    client = APIClient()
    client.force_authenticate(user=owner)

    run("--apply")

    response = client.get(f"/api/scenarios/{scenario.pk}/")
    assert response.status_code == 200
    assert response.data["title"] == "Toyota Alphard 2.5L - 60mo (fresh save)"
    assert response.data["payload"] == {"tco_net": "389263.75"}
    assert client.get("/api/scenarios/").data["count"] == 1  # also listed


def test_apply_writes_audit_rows_for_every_change_and_never_touches_existing_ones(catalog):
    existing = list(AuditLog.objects.order_by("pk").values())

    run("--apply")

    assert list(AuditLog.objects.order_by("pk").values())[: len(existing)] == existing
    new_rows = list(AuditLog.objects.order_by("pk"))[len(existing):]
    by_action = {}
    for row in new_rows:
        by_action.setdefault((row.action, row.resource_type), []).append(row)
    assert len(by_action[(AuditActionCategory.UPDATE, "vehicles.VehicleModel")]) == 8
    assert len(by_action[(AuditActionCategory.ARCHIVE, "vehicles.VehicleModel")]) == 1
    assert len(by_action[(AuditActionCategory.ARCHIVE, "policy.SubscriptionPlan")]) == 1  # the cascade
    assert len(by_action[(AuditActionCategory.CREATE, "vehicles.VehicleModel")]) == 1
    assert len(new_rows) == 11

    bmw_row = next(r for r in by_action[(AuditActionCategory.UPDATE, "vehicles.VehicleModel")]
                   if r.resource_id == str(vehicle("3 Series", "320i Sport").pk))
    assert bmw_row.before_data["msrp"] == "245800.00" and bmw_row.after_data["msrp"] == "265800.00"
    assert bmw_row.before_data["powertrain"] == "" and bmw_row.after_data["powertrain"] == "petrol"
    assert "apply_catalog_corrections" in bmw_row.after_data["correction"]
    created = by_action[(AuditActionCategory.CREATE, "vehicles.VehicleModel")][0]
    assert created.before_data is None and created.after_data["trim"] == "2.4 Executive Lounge"
    assert all(r.actor_id is None and r.actor_email == "" for r in new_rows)  # no request, no actor


def test_the_actor_option_attributes_the_audit_rows(catalog):
    run("--apply", "--actor", "admin@flexidrivemy.local")

    assert AuditLog.objects.exclude(actor=None).filter(actor_email="admin@flexidrivemy.local").count() == 12  # +1 existing


def test_a_second_apply_is_a_no_op(catalog):
    run("--apply")
    after_first = state()

    second = run("--apply")

    assert "Nothing to change." in second
    assert "== Summary: 0 change(s)" in second
    assert "8 already up to date" in second
    assert "already archived" in second and "already exists" in second
    assert state() == after_first


def test_the_dry_run_after_apply_finds_nothing_to_change(catalog):
    run("--apply")

    output = run()

    assert "Nothing to change." in output
    assert "8 already up to date" in output


def test_an_unmatched_target_is_reported_and_skipped_never_widened(catalog):
    VehicleModel.objects.filter(name="Macan", trim="Base").update(trim="Base S")  # no exact match any more

    output = run("--apply")

    assert "SKIPPED Porsche / Macan / Base: no row matches" in output
    assert vehicle("Macan", "Base S").powertrain == ""  # the near-miss was not touched
    assert vehicle("3 Series", "320i Sport").powertrain == "petrol"  # the rest still applied


def test_a_missing_old_alphard_skips_the_archive_but_the_rest_still_runs(catalog):
    VehicleModel.objects.filter(name="Alphard", trim="2.5L").update(trim="2.5L Executive")

    output = run("--apply")

    assert "SKIPPED archive of Toyota / Alphard / 2.5L: no row matches" in output
    assert vehicle("Alphard", "2.5L Executive").is_active  # not archived by mistake
    assert vehicle("Alphard", "2.4 Executive Lounge").msrp == Decimal("548000.00")


def test_other_rows_without_specs_are_reported_but_left_alone(catalog):
    output = run("--apply")

    assert "== Other vehicles that still need specs (reported only, left alone) ==" in output
    assert "Honda / City / V" in output.split("== Other vehicles")[1]
    honda = vehicle("City", "V")
    assert (honda.powertrain, honda.engine_capacity_cc, honda.is_active) == ("", None, False)


def test_an_unknown_actor_is_refused(catalog):
    with pytest.raises(CommandError):
        run("--apply", "--actor", "nobody@example.com")
