"""apply_catalog_corrections_run2 (Run 2 fix batch 2, findings C1 and C2): dry run
by default, one transaction on --apply, idempotent, exact-match targets only,
every change audited, existing audit rows never touched.

- BMW 3 Series 320i Sport: MSRP 265,800 -> 267,800 and model year 2025 -> 2026.
- Porsche Macan Electric RWD: power 261.1 -> 250.0 kW (the JPJ EV kW engine
  then computes the road tax; nothing here assumes it).
- Lexus ES 250 Luxury and every other car: untouched.
"""

import importlib
from decimal import Decimal
from io import StringIO

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditActionCategory, AuditLog
from apps.comparisons.services import build_comparison
from apps.depreciation.services import build_tco_report
from apps.policy.models import InterestRate, MileageBand
from apps.policy.operating_costs import estimate_operating_costs
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal
seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")


@pytest.fixture
def catalog(create_user):
    """The dev catalog as it stands before this batch."""
    brands = {name: Brand.objects.create(name=name, tier_code=tier)
              for name, tier in (("BMW", "2"), ("Porsche", "1"), ("Lexus", "1"))}
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=brands["BMW"], rate_percent="2.8000", is_active=True)
    InterestRate.objects.create(brand=brands["Porsche"], rate_percent="3.5000", is_active=True)
    cars = {
        "bmw": VehicleModel.objects.create(
            brand=brands["BMW"], name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN,
            msrp="265800.00", engine_capacity_kw="135.00", engine_capacity_cc=1998, powertrain="petrol",
            model_year=2025,
        ),
        "macan_ev": VehicleModel.objects.create(
            brand=brands["Porsche"], name="Macan Electric", trim="Macan RWD", body_segment=BodySegment.SUV,
            msrp="575000.00", engine_capacity_kw="261.10", powertrain="bev", model_year=2026,
        ),
        "lexus": VehicleModel.objects.create(
            brand=brands["Lexus"], name="ES", trim="250 Luxury", body_segment=BodySegment.SEDAN,
            msrp="356888.00", engine_capacity_kw="151.00", engine_capacity_cc=2487, powertrain="petrol",
        ),
    }
    admin = create_user(email="admin@flexidrivemy.local", role="admin")
    AuditLog.objects.create(
        actor=admin, actor_email=admin.email, action=AuditActionCategory.CREATE,
        resource_type="vehicles.VehicleModel", resource_id=str(cars["bmw"].pk), after_data={"name": "3 Series"},
    )
    for car in cars.values():
        car.refresh_from_db()
    return cars


def run(*args):
    out = StringIO()
    call_command("apply_catalog_corrections_run2", *args, stdout=out)
    return out.getvalue()


def fresh(car):
    return VehicleModel.objects.get(pk=car.pk)


def state():
    return {"vehicles": list(VehicleModel.objects.order_by("pk").values()), "audit": AuditLog.objects.count()}


def test_the_dry_run_is_the_default_changes_nothing_and_shows_the_running_costs(catalog):
    before = state()

    output = run()

    assert output.startswith("DRY RUN - nothing will be changed")
    assert "msrp: 265800.00 -> 267800.00" in output and "model_year: 2025 -> 2026" in output
    assert "engine_capacity_kw (power kW): 261.10 -> 250.00" in output
    assert "== Summary: 2 change(s); 0 already up to date; 0 skipped; 0 invalid ==" in output
    assert "Dry run only. Re-run with --apply" in output
    # the road tax comes from the real engine, before and after - nothing assumed
    assert "road tax RM 455.00 (261.1 kW electric - JPJ EV kW schedule, group C)" in output
    assert "road tax RM 395.00 (250 kW electric - JPJ EV kW schedule, group C)" in output
    assert "insurance RM 4,820.40; maintenance RM 2,678.00" in output  # the BMW at 267,800
    assert state() == before


def test_apply_changes_exactly_the_listed_fields_and_nothing_else(catalog):
    run("--apply", "--actor-email", "admin@flexidrivemy.local")

    bmw, ev, lexus = fresh(catalog["bmw"]), fresh(catalog["macan_ev"]), fresh(catalog["lexus"])
    assert (bmw.msrp, bmw.model_year) == (D("267800.00"), 2026)
    assert (bmw.engine_capacity_kw, bmw.engine_capacity_cc, bmw.powertrain) == (D("135.00"), 1998, "petrol")
    assert ev.engine_capacity_kw == D("250.00")
    assert (ev.msrp, ev.powertrain, ev.engine_capacity_cc, ev.model_year) == (D("575000.00"), "bev", None, 2026)
    # Lexus ES 250 is deliberately left alone (the ES 300h price is only an estimate)
    assert state_of(lexus) == state_of(catalog["lexus"])
    assert (lexus.msrp, lexus.model_year) == (D("356888.00"), None)


def state_of(vehicle):
    return {f.name: getattr(vehicle, f.name) for f in VehicleModel._meta.concrete_fields if f.name != "updated_at"}


def test_every_change_is_audited_under_the_actor_and_existing_rows_are_untouched(catalog):
    existing = list(AuditLog.objects.order_by("pk").values())

    output = run("--apply", "--actor-email", "admin@flexidrivemy.local")

    assert list(AuditLog.objects.order_by("pk").values())[: len(existing)] == existing
    new_rows = list(AuditLog.objects.order_by("pk"))[len(existing):]
    assert len(new_rows) == 2
    assert {r.action for r in new_rows} == {AuditActionCategory.UPDATE}
    assert {r.resource_type for r in new_rows} == {"vehicles.VehicleModel"}
    assert {r.actor_email for r in new_rows} == {"admin@flexidrivemy.local"}
    assert {r.resource_id for r in new_rows} == {str(catalog["bmw"].pk), str(catalog["macan_ev"].pk)}
    bmw_row = next(r for r in new_rows if r.resource_id == str(catalog["bmw"].pk))
    assert (bmw_row.before_data["msrp"], bmw_row.after_data["msrp"]) == ("265800.00", "267800.00")
    assert (bmw_row.before_data["model_year"], bmw_row.after_data["model_year"]) == (2025, 2026)
    ev_row = next(r for r in new_rows if r.resource_id == str(catalog["macan_ev"].pk))
    assert (ev_row.before_data["engine_capacity_kw"], ev_row.after_data["engine_capacity_kw"]) == ("261.10", "250.00")
    assert "apply_catalog_corrections_run2" in bmw_row.after_data["correction"]
    assert f"Audit rows: #{new_rows[0].pk}, #{new_rows[1].pk}." in output


def test_a_second_run_changes_nothing_and_writes_no_audit_row(catalog):
    run("--apply", "--actor-email", "admin@flexidrivemy.local")
    after_first = state()

    second = run("--apply", "--actor-email", "admin@flexidrivemy.local")
    dry = run()

    assert state() == after_first
    assert "== Summary: 0 change(s); 2 already up to date" in second and "Nothing to change." in second
    assert "Nothing to change." in dry


def test_an_unmatched_target_is_reported_and_skipped_never_widened(catalog):
    VehicleModel.objects.filter(pk=catalog["bmw"].pk).update(trim="320i Sport Plus")  # no exact match now

    output = run("--apply")

    assert "SKIPPED BMW / 3 Series / 320i Sport: no row matches" in output
    assert fresh(catalog["bmw"]).msrp == D("265800.00")  # the near-miss was not touched
    assert fresh(catalog["macan_ev"]).engine_capacity_kw == D("250.00")  # the other target still applied


def test_an_unknown_actor_is_refused_before_anything_is_written(catalog):
    before = state()

    with pytest.raises(CommandError):
        run("--apply", "--actor-email", "nobody@example.com")

    assert state() == before


def test_the_batch_1_command_is_unchanged_and_still_documents_that_it_is_superseded():
    from apps.vehicles.management.commands import apply_catalog_corrections as batch1

    bmw = next(t for t in batch1.CORRECTIONS if t["key"] == ("BMW", "3 Series", "320i Sport"))
    assert bmw["set"]["msrp"] == D("265800.00") and bmw["set"]["model_year"] == 2025  # what batch 1 applied
    assert "do not re-run it" in batch1.__doc__.lower()


# --- model_year is display-only --------------------------------------------------------------------------------------


def test_model_year_changes_no_figure_anywhere(catalog):
    """Checked before the BMW's year was changed: 2025 vs 2026 gives byte-identical
    comparison, TCO and running-cost results (it is not an ML feature and no price,
    residual, subscription or cost calculation reads it)."""
    bmw = catalog["bmw"]

    def figures():
        common = dict(vehicle=fresh(bmw), tenure_months=36, mileage_band=MileageBand.STANDARD,
                      downpayment=D("26580.00"))
        return build_comparison(**common), build_tco_report(**common), estimate_operating_costs(fresh(bmw))

    as_2025 = figures()
    VehicleModel.objects.filter(pk=bmw.pk).update(model_year=2026)
    as_2026 = figures()
    VehicleModel.objects.filter(pk=bmw.pk).update(model_year=None)
    as_blank = figures()

    assert as_2025 == as_2026 == as_blank


# --- the goldens after the correction (BMW 320i Sport at RM 267,800, 60 months, standard, 10% down) -----------------------


def test_the_bmw_goldens_after_the_correction(catalog):
    run("--apply", "--actor-email", "admin@flexidrivemy.local")
    bmw = fresh(catalog["bmw"])
    common = dict(vehicle=bmw, tenure_months=60, mileage_band=MileageBand.STANDARD, downpayment=D("26780.00"))

    comparison = build_comparison(**common)
    report = build_tco_report(**common)

    hp, gfv = comparison["hire_purchase"], comparison["gfv_leasing"]
    assert hp["monthly_instalment"] == D("4579.38")
    assert hp["total_contract_outlay"] == D("301542.80")  # (267,800 - 26,780) x 1.14 / 60 x 60 + 26,780
    # Run 3 fix batch 6: 36.79% of 267,800 (the recalibrated 60-month standard residual; was
    # 35% -> 93,730.00 / 3,017.21); (241,020 - 98,523.62) / 60 + 241,020 x 2.8% / 12 = 2,937.32
    assert gfv["balloon_payment"] == D("98523.62")
    assert gfv["monthly_instalment"] == D("2937.32")
    assert (report["road_tax_annual"], report["insurance_annual"], report["maintenance_annual"]) == (
        D("379.00"), D("4820.40"), D("2678.00"))


def test_the_macan_electric_road_tax_is_what_the_jpj_engine_computes_at_250_kw(catalog):
    assert estimate_operating_costs(fresh(catalog["macan_ev"])).road_tax_annual == D("455.00")  # at 261.1 kW

    run("--apply")

    costs = estimate_operating_costs(fresh(catalog["macan_ev"]))
    assert costs.road_tax_annual == D("395.00")
    assert costs.basis["road_tax"] == "250 kW electric - JPJ EV kW schedule, group C"
