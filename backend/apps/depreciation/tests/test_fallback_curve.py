"""Audit batch 4: the depreciation fallback (no trained model) follows the
same residuals as GFV - anchors at months 0/12/24/36/48/60, straight-line
interpolation of the retained RATIO between them - so the TCO and the GFV
balloon agree for the same car, and the curve is front-loaded rather than one
flat 1%/month line for every car.
"""

import importlib
from decimal import Decimal

import pytest
from django.apps import apps as django_apps

from apps.depreciation import formulas, inference
from apps.policy import mileage
from apps.policy.models import MileageBand, ResidualBaseline, ResidualValueMatrix
from apps.policy.residuals import resolve_residual_ratio
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal
seed_module = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")


def make_vehicle(brand_name="BMW", powertrain="petrol", msrp="265800.00"):
    brand, _ = Brand.objects.get_or_create(name=brand_name, defaults={"tier_code": "2"})
    seed_module.seed_brand_adjustments(django_apps)
    vehicle = VehicleModel.objects.create(
        brand=brand, name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN, msrp=msrp,
        engine_capacity_kw="135.00", powertrain=powertrain, engine_capacity_cc=None if powertrain == "bev" else 1998,
    )
    vehicle.refresh_from_db()
    return vehicle


def km_for(band):
    """The km a year the forecast uses for a band - from the one definition (apps.policy.mileage)."""
    return mileage.representative_km(band)


STANDARD_KM = "STANDARD_KM"


def curve(vehicle, km):
    km = km_for("standard") if km == STANDARD_KM else km
    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=D(km))
    assert degraded is True and reason == inference.DEGRADED_MESSAGE
    return values


def test_the_golden_bmw_320i_curve_at_the_standard_band():
    """RM 265,800, the standard band. Run 3 fix batch 6 anchors 1.00 / 0.7807 /
    0.6207 / 0.5179 / 0.4379 / 0.3679 (were 0.77 / 0.61 / 0.50 / 0.42 / 0.35), so by hand:
      month 6  = 265800 x (1.00 + (0.7807-1.00) x 6/12)     = 265800 x 0.89035 = 236,655.03
      month 12 = 265800 x 0.7807                            = 207,510.06
      month 30 = 265800 x (0.6207 + (0.5179-0.6207) x 6/12) = 265800 x 0.5693  = 151,319.94
      month 36 = 265800 x 0.5179                            = 137,657.82
      month 60 = 265800 x 0.3679                            =  97,787.82
    """
    values = curve(make_vehicle(), STANDARD_KM)

    assert len(values) == 61
    assert values[0] == D("265800.00")
    assert values[6] == D("236655.03")
    assert values[12] == D("207510.06")
    assert values[30] == D("151319.94")
    assert values[36] == D("137657.82")
    assert values[60] == D("97787.82")


def test_months_36_48_60_equal_the_gfv_residual_for_the_same_car_so_tco_and_gfv_agree():
    for brand, powertrain in [("Toyota", "petrol"), ("Porsche", "bev"), ("Volvo", "phev"), ("BMW", "petrol")]:
        vehicle = make_vehicle(brand, powertrain, msrp="400000.00")
        values = curve(vehicle, STANDARD_KM)
        for month in (12, 24, 36, 48, 60):
            gfv_ratio = resolve_residual_ratio(vehicle, month, MileageBand.STANDARD).ratio
            assert values[month] == (vehicle.msrp * gfv_ratio).quantize(D("0.01")), (brand, powertrain, month)


def test_the_curve_is_vehicle_specific_not_one_straight_line():
    bmw = curve(make_vehicle("BMW", "petrol", "400000.00"), STANDARD_KM)
    toyota = curve(make_vehicle("Toyota", "petrol", "400000.00"), STANDARD_KM)
    macan_ev = curve(make_vehicle("Porsche", "bev", "400000.00"), STANDARD_KM)

    # month 48: BMW 0.4379, Toyota 0.4979 (+6 pts), Porsche BEV 0.4079 (+5 - 8 pts)
    assert (bmw[48], toyota[48], macan_ev[48]) == (D("175160.00"), D("199160.00"), D("163160.00"))
    # the old straight line gave every car exactly 40% at month 60 (and 52% at 48)
    assert bmw[60] != formulas.straight_line_resale_value(D("400000.00"), 60)


def test_the_curve_is_front_loaded():
    values = curve(make_vehicle(msrp="100000.00"), STANDARD_KM)

    first_year_loss = values[0] - values[12]
    last_year_loss = values[48] - values[60]
    assert first_year_loss > last_year_loss  # 21,930 vs 7,000


def test_the_curve_is_non_increasing_and_never_above_msrp_for_every_band():
    vehicle = make_vehicle()
    for km in [km_for(band) for band in mileage.BAND_ORDER]:
        values = curve(vehicle, km)
        assert values[0] == vehicle.msrp
        assert all(a >= b for a, b in zip(values, values[1:])), km


def test_mileage_changes_the_curve_by_band():
    vehicle = make_vehicle(msrp="100000.00")

    # month 60 baselines (Run 3 fix batch 6): low 0.40, standard 0.3679, high 0.33, very_high 0.29
    assert curve(vehicle, km_for("low"))[60] == D("40000.00")
    assert curve(vehicle, km_for("standard"))[60] == D("36790.00")
    assert curve(vehicle, km_for("high"))[60] == D("33000.00")
    assert curve(vehicle, km_for("very_high"))[60] == D("29000.00")


def test_mileage_band_for_km_boundaries_up_to_and_including():
    """Run 3 fix batch 6: each band runs up to and INCLUDING its limit (read from the
    definition, not repeated here): the limit itself is in the band, limit + 1 in the next."""
    definitions = mileage.band_definitions()
    assert inference.mileage_band_for_km(0) == "low"
    for current, following in zip(definitions, definitions[1:]):
        assert inference.mileage_band_for_km(current.upper_km) == current.key
        assert inference.mileage_band_for_km(D(current.upper_km)) == current.key
        assert inference.mileage_band_for_km(current.upper_km + 1) == following.key
    assert inference.mileage_band_for_km(definitions[-1].upper_km * 4) == "very_high"


def test_the_representative_km_of_each_band_lands_in_that_band():
    for band in mileage.BAND_ORDER:
        assert inference.mileage_band_for_km(km_for(band)) == band


def test_an_admin_override_flows_into_the_fallback_curve():
    vehicle = make_vehicle(msrp="100000.00")
    ResidualValueMatrix.objects.create(
        brand=vehicle.brand, tenure_months=36, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.4000"
    )

    values = curve(vehicle, STANDARD_KM)

    assert values[36] == D("40000.00")  # the override, not the 0.5179 baseline
    assert values[30] == D("51035.00")  # 0.6207 -> 0.40 over months 24..36: 0.51035


def test_an_override_that_rises_above_an_earlier_anchor_cannot_make_the_curve_increase():
    vehicle = make_vehicle(msrp="100000.00")
    ResidualValueMatrix.objects.create(  # absurdly high 60-month override (0.60 > the 0.4379 at month 48)
        brand=vehicle.brand, tenure_months=60, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.6000"
    )

    values = curve(vehicle, STANDARD_KM)

    assert all(a >= b for a, b in zip(values, values[1:]))
    assert values[60] == values[48] == D("43790.00")


def test_with_no_baseline_at_all_the_fallback_still_returns_a_curve_never_an_error():
    ResidualBaseline.objects.update(is_active=False)
    vehicle = make_vehicle(msrp="100000.00")

    values, degraded, _ = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=km_for("standard"))

    assert degraded is True
    assert values == [formulas.straight_line_resale_value(D("100000.00"), m) for m in range(61)]
