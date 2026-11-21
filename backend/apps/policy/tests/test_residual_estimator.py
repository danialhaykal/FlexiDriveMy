"""Audit batch 4: the one residual-value estimator (apps.policy.residuals).

GFV's G_ratio and the depreciation fallback both come from it, so nothing is
keyed per car or per brand. The golden ratios below are hand-derived from the
seeded planning assumptions:

    ratio = baseline(tenure, band) + brand points + powertrain points

and they are the same numbers the audit prompt lists.
"""

import importlib
from decimal import Decimal

import pytest
from django.apps import apps as django_apps

from apps.common.constants import MAX_GFV_RESIDUAL_RATIO
from apps.policy.models import MileageBand, ResidualAdjustment, ResidualBaseline, ResidualValueMatrix
from apps.policy.residuals import (
    RESIDUAL_FLOOR_RATIO,
    ResidualConfigError,
    available_gfv_tenures,
    resolve_residual_ratio,
)
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal
seed_module = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")


def make_vehicle(brand_name, powertrain, *, name="Model", trim="X", cc=1998, tier="2"):
    brand, _ = Brand.objects.get_or_create(name=brand_name, defaults={"tier_code": tier})
    seed_module.seed_brand_adjustments(django_apps)  # keyed by brand, so seeded once the brand exists
    vehicle = VehicleModel.objects.create(
        brand=brand, name=name, trim=trim, body_segment=BodySegment.SEDAN, msrp="300000.00",
        engine_capacity_kw="150.00", powertrain=powertrain, engine_capacity_cc=None if powertrain == "bev" else cc,
    )
    vehicle.refresh_from_db()
    return vehicle


def ratio(vehicle, tenure, band=MileageBand.STANDARD):
    return resolve_residual_ratio(vehicle, tenure, band).ratio


# --- The seeded tables ------------------------------------------------------


def test_the_baseline_grid_is_seeded_exactly_and_falls_as_tenure_and_mileage_rise():
    # Run 3 fix batch 6 (policy 0028): the grid re-read at the recalibrated bands'
    # representative km. Was 12: .80/.77/.74/.70; 24: .64/.61/.57/.52; 36: .55/.50/.45/.40;
    # 48: .47/.42/.38/.33; 60: .40/.35/.31/.27.
    expected = {
        12: ["0.8000", "0.7807", "0.7550", "0.7200"],
        24: ["0.6400", "0.6207", "0.5900", "0.5450"],
        36: ["0.5500", "0.5179", "0.4750", "0.4250"],
        48: ["0.4700", "0.4379", "0.4000", "0.3550"],
        60: ["0.4000", "0.3679", "0.3300", "0.2900"],
    }
    bands = ["low", "standard", "high", "very_high"]
    for tenure, values in expected.items():
        for band, value in zip(bands, values):
            assert ResidualBaseline.objects.get(tenure_months=tenure, mileage_band=band, is_active=True).ratio == D(value)
    assert ResidualBaseline.objects.filter(is_active=True).count() == 20
    # The GFV formula's worked reference case (G_ratio 50%) is a formula test with the
    # ratio given (test_formulas); since Run 3 fix batch 6 the seeded 36-month standard
    # residual is 0.5179, not 0.50.
    assert ResidualBaseline.objects.get(tenure_months=36, mileage_band="standard").ratio == D("0.5179")


def test_every_seeded_row_says_plainly_that_it_is_a_planning_assumption():
    make_vehicle("Toyota", "petrol")  # brings the brand adjustment rows into existence too
    rows = [*ResidualBaseline.objects.all(), *ResidualAdjustment.objects.all()]
    assert len(rows) == 20 + 6 + 1
    for row in rows:
        assert "Planning estimate - directional, edit in admin. Real GFV residuals are set by the lender." in row.source_note


def test_the_powertrain_adjustments_are_seeded():
    points = {a.powertrain: a.delta_points for a in ResidualAdjustment.objects.filter(brand__isnull=True)}
    assert points == {
        "bev": D("-0.08"), "phev": D("-0.03"), "petrol": D("0"), "diesel": D("0"), "mild_hybrid": D("0"), "hybrid": D("0"),
    }


# --- Golden ratios (standard band unless stated) -----------------------------


@pytest.mark.parametrize(
    "brand_name, powertrain, tenure, band, expected",
    [
        ("BMW", "petrol", 36, MileageBand.STANDARD, "0.5179"),  # Run 3 fix batch 6: was 0.5000
        ("BMW", "petrol", 48, MileageBand.STANDARD, "0.4379"),  # was 0.4200
        ("BMW", "petrol", 12, MileageBand.STANDARD, "0.7807"),  # was 0.7700
        ("BMW", "petrol", 60, MileageBand.VERY_HIGH, "0.2900"),  # was 0.2700
        ("Toyota", "petrol", 48, MileageBand.STANDARD, "0.4979"),      # Alphard: 0.4379 + 0.06
        ("Lexus", "petrol", 48, MileageBand.STANDARD, "0.4779"),       # ES 250: 0.4379 + 0.04
        ("Porsche", "petrol", 48, MileageBand.STANDARD, "0.4879"),     # 911: 0.4379 + 0.05
        ("Porsche", "bev", 48, MileageBand.STANDARD, "0.4079"),        # Macan Electric: 0.4379 + 0.05 - 0.08
        ("Volvo", "phev", 48, MileageBand.STANDARD, "0.3679"),         # XC90 T8: 0.4379 - 0.04 - 0.03
        ("Volvo", "mild_hybrid", 48, MileageBand.STANDARD, "0.3979"),  # XC60 B5: 0.4379 - 0.04
        ("Mercedes-Benz", "mild_hybrid", 36, MileageBand.STANDARD, "0.5179"),
    ],
)
def test_golden_residual_ratios(brand_name, powertrain, tenure, band, expected):
    vehicle = make_vehicle(brand_name, powertrain)

    result = resolve_residual_ratio(vehicle, tenure, band)

    assert result.ratio == D(expected)
    assert result.source == "estimate"


def test_the_basis_is_plain_english_and_names_every_term():
    toyota = make_vehicle("Toyota", "petrol")
    assert resolve_residual_ratio(toyota, 48, MileageBand.STANDARD).basis == (
        "Estimate: 43.79% baseline for 48 months / standard mileage, +6 points Toyota, 0 points petrol"
    )
    volvo = make_vehicle("Volvo", "phev")
    assert resolve_residual_ratio(volvo, 48, MileageBand.VERY_HIGH).basis == (
        "Estimate: 35.5% baseline for 48 months / very high mileage, -4 points Volvo, -3 points plug-in hybrid"
    )


# --- A new brand / powertrain is never an error ------------------------------


def test_an_unknown_brand_with_no_adjustment_row_still_gets_the_baseline():
    brand = Brand.objects.create(name="BrandNewMarque", tier_code="3")
    vehicle = VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN, msrp="300000.00",
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    assert not ResidualAdjustment.objects.filter(brand=brand).exists()

    result = resolve_residual_ratio(vehicle, 48, MileageBand.STANDARD)

    assert result.ratio == D("0.4379")
    assert result.basis == "Estimate: 43.79% baseline for 48 months / standard mileage, 0 points BrandNewMarque, 0 points petrol"


def test_a_vehicle_with_no_powertrain_set_gets_zero_powertrain_points_rather_than_an_error():
    brand = Brand.objects.create(name="LegacyMarque", tier_code="3")
    vehicle = VehicleModel.objects.create(
        brand=brand, name="Old", trim="X", body_segment=BodySegment.SEDAN, msrp="300000.00", engine_capacity_kw="150.00",
    )

    assert resolve_residual_ratio(vehicle, 36, MileageBand.STANDARD).ratio == D("0.5179")


# --- An override wins ---------------------------------------------------------


def test_an_active_override_row_wins_over_the_estimate_and_is_used_exactly():
    toyota = make_vehicle("Toyota", "petrol")
    ResidualValueMatrix.objects.create(
        brand=toyota.brand, tenure_months=48, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.3333"
    )

    result = resolve_residual_ratio(toyota, 48, MileageBand.STANDARD)

    assert result.ratio == D("0.3333")  # not 0.4979, and no powertrain/brand points applied on top
    assert result.source == "override"
    assert result.basis == "Admin override for Toyota, 48 months, standard mileage"
    # Only that exact cell is overridden.
    assert resolve_residual_ratio(toyota, 36, MileageBand.STANDARD).source == "estimate"
    assert resolve_residual_ratio(toyota, 48, MileageBand.HIGH).source == "estimate"


def test_an_archived_override_is_ignored():
    toyota = make_vehicle("Toyota", "petrol")
    ResidualValueMatrix.objects.create(
        brand=toyota.brand, tenure_months=48, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.3333",
        is_active=False,
    )

    assert ratio(toyota, 48) == D("0.4979")


def test_an_override_enables_a_tenure_the_baseline_does_not_cover():
    bmw = make_vehicle("BMW", "petrol")
    with pytest.raises(ResidualConfigError):
        resolve_residual_ratio(bmw, 72, MileageBand.STANDARD)
    ResidualValueMatrix.objects.create(
        brand=bmw.brand, tenure_months=72, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.2000"
    )

    assert ratio(bmw, 72) == D("0.2000")


# --- Clamps ---------------------------------------------------------------------


def test_the_estimate_is_clamped_at_the_floor():
    bmw = make_vehicle("BMW", "petrol")
    ResidualAdjustment.objects.filter(brand=bmw.brand).update(is_active=False)
    ResidualAdjustment.objects.create(brand=bmw.brand, delta_points="-0.4000", effective_from="2026-10-07")

    result = resolve_residual_ratio(bmw, 60, MileageBand.VERY_HIGH)  # 0.29 - 0.40 = -0.11

    assert RESIDUAL_FLOOR_RATIO == D("0.10")
    assert result.ratio == D("0.1000")
    assert result.basis.endswith("(limited to 10%)")


def test_the_estimate_is_clamped_at_the_maximum_gfv_ratio():
    toyota = make_vehicle("Toyota", "petrol")
    ResidualAdjustment.objects.filter(brand=toyota.brand).update(is_active=False)
    ResidualAdjustment.objects.create(brand=toyota.brand, delta_points="0.2000", effective_from="2026-10-07")

    result = resolve_residual_ratio(toyota, 12, MileageBand.LOW)  # 0.80 + 0.20 = 1.00

    assert MAX_GFV_RESIDUAL_RATIO == D("0.9")
    assert result.ratio == D("0.9000")
    assert result.basis.endswith("(limited to 90%)")


# --- A tenure with no baseline -----------------------------------------------------


@pytest.mark.parametrize("tenure", [6, 40, 72, 108])
def test_a_tenure_with_no_baseline_raises_the_friendly_error(tenure):
    bmw = make_vehicle("BMW", "petrol")

    with pytest.raises(ResidualConfigError) as excinfo:
        resolve_residual_ratio(bmw, tenure, MileageBand.STANDARD)

    assert str(excinfo.value) == (
        f"GFV leasing isn't offered for {tenure} months - it is offered for 12 to 60 months in 12-month steps."
    )


def test_the_available_tenures_list_follows_the_real_tables():
    bmw = make_vehicle("BMW", "petrol")
    assert available_gfv_tenures(bmw.brand, MileageBand.STANDARD) == [12, 24, 36, 48, 60]

    ResidualBaseline.objects.filter(tenure_months=12).update(is_active=False)
    ResidualBaseline.objects.filter(tenure_months=24).update(is_active=False)
    with pytest.raises(ResidualConfigError) as excinfo:
        resolve_residual_ratio(bmw, 24, MileageBand.STANDARD)
    assert str(excinfo.value) == "GFV leasing isn't offered for 24 months - it is offered for 36 to 60 months in 12-month steps."

    ResidualBaseline.objects.update(is_active=False)
    with pytest.raises(ResidualConfigError) as excinfo:
        resolve_residual_ratio(bmw, 24, MileageBand.STANDARD)
    assert str(excinfo.value) == "GFV leasing isn't offered for 24 months - it isn't offered for this model."


# --- The data migration: idempotent, never overwrites an admin edit -----------------


def test_re_running_the_seed_is_a_no_op_and_never_overwrites_an_admin_edit():
    make_vehicle("Toyota", "petrol")
    edited = ResidualBaseline.objects.get(tenure_months=48, mileage_band="standard")
    edited.ratio = D("0.4400")
    edited.source_note = "Edited by an admin"
    edited.save()
    adjustment = ResidualAdjustment.objects.get(brand__name="Toyota")
    adjustment.delta_points = D("0.0900")
    adjustment.save()
    counts = (ResidualBaseline.objects.count(), ResidualAdjustment.objects.count())

    seed_module.forwards(django_apps, None)
    seed_module.forwards(django_apps, None)

    assert (ResidualBaseline.objects.count(), ResidualAdjustment.objects.count()) == counts
    edited.refresh_from_db()
    adjustment.refresh_from_db()
    assert (edited.ratio, edited.source_note) == (D("0.4400"), "Edited by an admin")
    assert adjustment.delta_points == D("0.0900")


def test_a_retired_row_is_not_resurrected_over_an_active_replacement():
    row = ResidualBaseline.objects.get(tenure_months=48, mileage_band="standard")
    row.is_active = False
    row.save()
    ResidualBaseline.objects.create(
        tenure_months=48, mileage_band="standard", ratio="0.4000", effective_from="2026-10-07"
    )

    seed_module.forwards(django_apps, None)

    active = ResidualBaseline.objects.filter(tenure_months=48, mileage_band="standard", is_active=True)
    assert [r.ratio for r in active] == [D("0.4000")]


# --- DB constraints -----------------------------------------------------------------


def test_an_adjustment_must_have_exactly_one_of_brand_or_powertrain():
    from django.db import IntegrityError, transaction

    brand = Brand.objects.create(name="ConstraintBrand", tier_code="3")
    for kwargs in ({}, {"brand": brand, "powertrain": "bev"}):
        with pytest.raises(IntegrityError), transaction.atomic():
            ResidualAdjustment.objects.create(delta_points="0.0100", effective_from="2026-10-07", **kwargs)


def test_only_one_active_adjustment_per_brand_and_per_powertrain():
    from django.db import IntegrityError, transaction

    brand = Brand.objects.create(name="OneRowBrand", tier_code="3")
    ResidualAdjustment.objects.create(brand=brand, delta_points="0.0100", effective_from="2026-10-07")
    with pytest.raises(IntegrityError), transaction.atomic():
        ResidualAdjustment.objects.create(brand=brand, delta_points="0.0200", effective_from="2026-10-07")
    with pytest.raises(IntegrityError), transaction.atomic():
        ResidualAdjustment.objects.create(powertrain="bev", delta_points="0.0200", effective_from="2026-10-07")
