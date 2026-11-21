"""Guards the FYP1 report's locked premium catalog scope (A1 Update Table
7: BMW, Mercedes-Benz, Lexus, Porsche, Toyota only - see the project spec's
"Catalog scope" note) against drifting back in a future sprint. A real,
repeatable regression test, not just a documentation comment.
"""

from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.policy.models import MileageBand, ResidualValueMatrix
from apps.policy.operating_costs import estimate_operating_costs
from apps.vehicles.models import Brand, VehicleModel

pytestmark = pytest.mark.django_db

LOCKED_BRANDS = {"BMW", "Mercedes-Benz", "Lexus", "Porsche", "Toyota"}

# Explicitly out of the locked scope - never reintroduced by seed_dev_data.
OUT_OF_SCOPE_BRANDS = {"Perodua", "Honda", "Proton"}


def test_fresh_seed_produces_exactly_the_five_locked_brands(settings):
    settings.DEBUG = True

    call_command("seed_dev_data")

    brand_names = set(Brand.objects.values_list("name", flat=True))
    assert brand_names == LOCKED_BRANDS


def test_fresh_seed_never_reintroduces_an_out_of_scope_brand(settings):
    settings.DEBUG = True

    call_command("seed_dev_data")

    brand_names = set(Brand.objects.values_list("name", flat=True))
    assert brand_names.isdisjoint(OUT_OF_SCOPE_BRANDS)


# --- Audit batch 2: one operating-cost engine, nothing keyed per car ----------


def test_every_seeded_vehicle_is_costed_automatically_and_priced_with_no_plan_keyed(settings):
    """Previously each seeded SubscriptionPlan snapshotted its own road
    tax/insurance/maintenance from an OperatingCostBand lookup (which went
    stale, and crashed for a kW outside the old bands), and later carried an
    MSRP/40 fee - a formula, not provider data. Audit batch 5: the seed
    creates NO plan at all; the three costs come from
    apps.policy.operating_costs and the Subscription fee is estimated from
    the vehicle's own specs, for every seeded car."""
    from apps.policy.models import SubscriptionPlan
    from apps.policy.subscription_pricing import resolve_subscription_fee

    settings.DEBUG = True

    call_command("seed_dev_data")

    assert not SubscriptionPlan.objects.exists()
    for vehicle in VehicleModel.objects.all():
        costs = estimate_operating_costs(vehicle)
        assert costs.road_tax_annual > 0 and costs.insurance_annual > 0 and costs.maintenance_annual > 0
        quote = resolve_subscription_fee(vehicle, 36, "standard")
        assert quote.source == "estimate" and quote.fee_monthly > 0


def test_fresh_seed_toyota_vehicle_is_a_premium_model_not_a_vios_or_yaris(settings):
    settings.DEBUG = True

    call_command("seed_dev_data")

    toyota = Brand.objects.get(name="Toyota")
    toyota_vehicle_names = set(
        VehicleModel.objects.filter(brand=toyota).values_list("name", flat=True)
    )
    assert "Vios" not in toyota_vehicle_names
    assert "Yaris" not in toyota_vehicle_names
    assert toyota_vehicle_names  # something was actually seeded


# --- Audit batch 4: residuals are estimated, never seeded per brand ---------
# (The old seed gave EVERY brand the same flat grid, so a Toyota Alphard and
# a BMW got identical GFV residuals. A matrix row is now an optional override.)


def test_seed_creates_no_residual_override_rows_and_every_vehicle_still_gets_a_gfv_residual(settings):
    from apps.policy.residuals import resolve_residual_ratio

    settings.DEBUG = True

    call_command("seed_dev_data")

    assert not ResidualValueMatrix.objects.exists()
    for vehicle in VehicleModel.objects.select_related("brand"):
        for tenure in (36, 48, 60):
            result = resolve_residual_ratio(vehicle, tenure, MileageBand.STANDARD)
            assert result.source == "estimate"


def test_seed_gives_each_premium_brand_its_own_residual_adjustment_and_is_idempotent(settings):
    from apps.policy.models import ResidualAdjustment

    settings.DEBUG = True

    call_command("seed_dev_data")
    call_command("seed_dev_data")

    deltas = {a.brand.name: a.delta_points for a in ResidualAdjustment.objects.filter(brand__isnull=False)}
    assert deltas == {
        "Toyota": Decimal("0.0600"), "Lexus": Decimal("0.0400"), "Porsche": Decimal("0.0500"),
        "BMW": Decimal("0.0000"), "Mercedes-Benz": Decimal("0.0000"),
    }  # Volvo is not one of the five seeded report brands
    assert ResidualAdjustment.objects.filter(brand__isnull=False).count() == 5


# --- Audit batch 1: the seed follows the new-vehicle contract and converges
# vehicle rows too (update_or_create, not get_or_create) ---------------------


def test_every_seeded_vehicle_satisfies_the_new_vehicle_contract(settings):
    settings.DEBUG = True

    call_command("seed_dev_data")

    vehicles = list(VehicleModel.objects.all())
    assert vehicles
    assert all(v.spec_complete for v in vehicles)
    for vehicle in vehicles:
        vehicle.full_clean()  # the same rule the Django admin form applies


def test_reseed_converges_a_stale_vehicle_to_the_corrected_values(settings):
    settings.DEBUG = True
    call_command("seed_dev_data")
    bmw = VehicleModel.objects.get(name="3 Series", trim="320i Sport")
    # A dev DB seeded before the corrections: old MSRP, no cc/powertrain/year.
    VehicleModel.objects.filter(pk=bmw.pk).update(
        msrp=Decimal("245800.00"), engine_capacity_cc=None, powertrain="", model_year=None
    )

    call_command("seed_dev_data")

    bmw.refresh_from_db()
    assert (bmw.msrp, bmw.engine_capacity_cc, bmw.powertrain, bmw.model_year) == (
        Decimal("265800.00"), 1998, "petrol", 2025)


def test_reseed_never_unarchives_a_vehicle(settings):
    settings.DEBUG = True
    call_command("seed_dev_data")
    VehicleModel.objects.filter(name="3 Series").update(is_active=False)

    call_command("seed_dev_data")

    assert VehicleModel.objects.get(name="3 Series").is_active is False


# --- H4: DEBUG no longer accidentally defaults to True everywhere, so this
# guard (which only matters when DEBUG is actually False) now means
# something ------------------------------------------------------------


def test_refuses_to_run_with_debug_false(settings):
    from django.core.management.base import CommandError

    settings.DEBUG = False

    with pytest.raises(CommandError):
        call_command("seed_dev_data")
