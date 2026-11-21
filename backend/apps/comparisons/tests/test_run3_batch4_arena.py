"""Run 3 fix batch 4 (F-21): the Arena's TCO row is the Hire Purchase TCO, so a car
whose Hire Purchase is not offered (the shared downpayment is below its 10% minimum)
gets no TCO - it carries the comparison's own reason and sits out of the lowest-TCO
race - and its Status row says "Not available at this downpayment" when no pathway
is offered at all. A car that is fine is unchanged, and an estimated-curve car keeps
its wording.

A stub log-scale model is deployed so the covered cars are on the machine-learning
curve and the lowest-TCO race can have a winner (same pattern as
apps/depreciation/tests/test_forecast_source.py).
"""

import importlib
import math
from decimal import Decimal

import joblib
import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient

from apps.common.constants import minimum_downpayment_message
from apps.depreciation.services import build_tco_report
from apps.ml.models import ModelType, PredictionTarget, ProductionModel
from apps.policy.models import InterestRate
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")

AVAILABLE = "Available"
NOT_AT_THIS_DOWNPAYMENT = "Not available at this downpayment"


class StubLogCurve:
    """A fitted-model stand-in on the LOG price scale (module-level so joblib can load it)."""

    def predict(self, rows):
        return [math.log(max(1.0 - 0.12 * age, 1e-9)) for age in rows["vehicle_age"]]


@pytest.fixture(autouse=True)
def deployed_model(tmp_path):
    path = tmp_path / "stub.joblib"
    joblib.dump(StubLogCurve(), path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.LOG_LINEAR
    production.model_file_path = str(path)
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.r2_score = 0.9124
    production.mae = 0.1473
    production.save()


def _car(brand_name, tier, rate, **fields):
    brand, _ = Brand.objects.get_or_create(name=brand_name, defaults={"tier_code": tier})
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.get_or_create(brand=brand, defaults={"rate_percent": rate, "is_active": True})
    vehicle = VehicleModel.objects.create(brand=brand, **fields)
    vehicle.refresh_from_db()  # the price as a Decimal, as a real request loads it
    return vehicle


@pytest.fixture
def bmw():
    # RM 267,800 -> minimum downpayment RM 26,780.
    return _car("BMW", "2", "2.8000", name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN,
                msrp="267800.00", engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998)


@pytest.fixture
def porsche_911():
    # RM 1,000,000 -> minimum downpayment RM 100,000.
    return _car("Porsche", "1", "3.5000", name="911", trim="Carrera", body_segment=BodySegment.COUPE,
                msrp="1000000.00", engine_capacity_kw="290.00", powertrain="petrol", engine_capacity_cc=2981)


@pytest.fixture
def macan_electric():
    # RM 575,000 -> minimum downpayment RM 57,500.
    return _car("Porsche", "1", "3.5000", name="Macan Electric", trim="Macan RWD", body_segment=BodySegment.SUV,
                msrp="575000.00", engine_capacity_kw="250.00", powertrain="bev")


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


def arena(client, vehicles, downpayment, tenure=48):
    response = client.get("/api/comparisons/arena/", {
        "vehicles": [v.pk for v in vehicles], "tenure_months": tenure, "mileage_band": "standard",
        "downpayment": downpayment,
    })
    assert response.status_code == 200, response.data
    return {e["vehicle_id"]: e for e in response.data["results"]}, response.data["winners"]


def tco_net(vehicle, downpayment, tenure=48):
    return build_tco_report(vehicle=vehicle, tenure_months=tenure, mileage_band="standard",
                            downpayment=Decimal(downpayment))["tco_net"]


def assert_sits_out_for_the_downpayment(entry, vehicle):
    reason = minimum_downpayment_message(vehicle.msrp)
    assert entry["ok"] is True and entry["error"] is None
    assert entry["comparison"]["hire_purchase"] is None
    assert entry["comparison"]["unavailable"]["hire_purchase"] == reason
    assert entry["tco_net"] is None
    assert entry["tco_unavailable_reason"] == reason  # the comparison's own wording
    assert entry["model_degraded"] is None and entry["forecast_source"] is None


# --- one car below its minimum ------------------------------------------------------------------------------------


def test_a_car_below_its_minimum_has_no_tco_and_sits_out_of_the_race(client, bmw, porsche_911):
    results, winners = arena(client, [bmw, porsche_911], "50000.00")

    assert_sits_out_for_the_downpayment(results[porsche_911.pk], porsche_911)
    # 48 months: no Subscription either, so nothing is offered for the 911 at this downpayment
    assert results[porsche_911.pk]["comparison"]["subscription"] is None
    assert results[porsche_911.pk]["status_label"] == NOT_AT_THIS_DOWNPAYMENT

    bmw_entry = results[bmw.pk]
    assert bmw_entry["status_label"] == AVAILABLE
    assert bmw_entry["forecast_source"] == "ml_model" and bmw_entry["model_degraded"] is False
    assert Decimal(bmw_entry["tco_net"]) == tco_net(bmw, "50000.00")
    # one eligible car has nobody to beat
    assert winners["lowest_tco"] is None
    assert winners["cheapest_hp"] is None


def test_a_car_below_its_minimum_with_subscription_offered_is_still_available(client, bmw, porsche_911):
    """At 36 months Subscription is offered (it needs no downpayment), so the 911 is
    "Available" - but its Hire Purchase TCO still sits out."""
    results, winners = arena(client, [bmw, porsche_911], "50000.00", tenure=36)

    assert_sits_out_for_the_downpayment(results[porsche_911.pk], porsche_911)
    assert results[porsche_911.pk]["comparison"]["subscription"] is not None
    assert results[porsche_911.pk]["status_label"] == AVAILABLE
    assert winners["lowest_tco"] is None
    assert winners["cheapest_subscription"] is not None  # that race is unchanged


# --- both cars below ----------------------------------------------------------------------------------------------


def test_both_cars_below_their_minimum(client, bmw, porsche_911):
    results, winners = arena(client, [bmw, porsche_911], "20000.00")

    for vehicle in (bmw, porsche_911):
        assert_sits_out_for_the_downpayment(results[vehicle.pk], vehicle)
        assert results[vehicle.pk]["status_label"] == NOT_AT_THIS_DOWNPAYMENT
    assert winners == {"cheapest_hp": None, "cheapest_gfv": None, "cheapest_subscription": None, "lowest_tco": None}


# --- a pair that is fine: unchanged -------------------------------------------------------------------------------


def test_a_pair_that_is_fine_is_unchanged(client, bmw, porsche_911):
    results, winners = arena(client, [bmw, porsche_911], "100000.00")

    expected = {bmw.pk: tco_net(bmw, "100000.00"), porsche_911.pk: tco_net(porsche_911, "100000.00")}
    for vehicle_id, entry in results.items():
        assert entry["status_label"] == AVAILABLE
        assert entry["tco_unavailable_reason"] is None
        assert entry["forecast_source"] == "ml_model" and entry["model_degraded"] is False
        assert Decimal(entry["tco_net"]) == expected[vehicle_id]
    cheaper = min(expected, key=expected.get)
    assert winners["lowest_tco"] == {"winner_id": cheaper, "tied_with": [cheaper]}
    assert winners["cheapest_hp"]["winner_id"] == bmw.pk


# --- the EV case --------------------------------------------------------------------------------------------------


def test_an_electric_car_keeps_its_estimated_curve_wording(client, bmw, macan_electric):
    results, winners = arena(client, [bmw, macan_electric], "57500.00")

    ev = results[macan_electric.pk]
    assert ev["status_label"] == AVAILABLE
    assert ev["forecast_source"] == "estimated_curve_unsupported" and ev["model_degraded"] is True
    assert Decimal(ev["tco_net"]) == tco_net(macan_electric, "57500.00")
    assert ev["tco_unavailable_reason"] is None
    # unchanged: the estimated curve sits out of the race, so the lone ML car has nobody to beat
    assert winners["lowest_tco"] is None


def test_an_electric_car_below_its_minimum_sits_out_for_the_downpayment(client, bmw, macan_electric):
    results, _winners = arena(client, [bmw, macan_electric], "30000.00")

    assert_sits_out_for_the_downpayment(results[macan_electric.pk], macan_electric)
    assert results[macan_electric.pk]["status_label"] == NOT_AT_THIS_DOWNPAYMENT
    assert results[bmw.pk]["status_label"] == AVAILABLE


# --- an error entry -----------------------------------------------------------------------------------------------


def test_an_error_entry_has_no_status_label(client, bmw, porsche_911):
    results, _winners = arena(client, [bmw, porsche_911], "300000.00")

    assert results[bmw.pk]["ok"] is False
    assert results[bmw.pk]["status_label"] is None
    assert results[porsche_911.pk]["status_label"] == AVAILABLE
