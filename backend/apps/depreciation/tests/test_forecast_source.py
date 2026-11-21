"""Run 2 fix batch 3 (A14, X1): `forecast_source` says where a car's resale curve
comes from, built from the ONE eligibility check inference already uses.

  ml_model                     the deployed model produced the curve
  estimated_curve_unsupported  the model can't cover THIS car (electric, no engine
                               size, body type not mapped) - nothing is broken
  model_unavailable            nothing usable is serving (none deployed, an
                               incompatible one, a runtime failure)

Also: the GFV block's `resale_note` is null unless the source is ml_model, and the
Vehicle Readiness line says the same thing (informational, never "needs attention").
"""

import importlib
import math
from decimal import Decimal

import joblib
import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient

from apps.depreciation import inference
from apps.depreciation.inference import (
    FORECAST_SOURCE_ML,
    FORECAST_SOURCE_UNAVAILABLE,
    FORECAST_SOURCE_UNSUPPORTED,
    coverage_gap,
    forecast_outlook,
    forecast_source,
)
from apps.ml.models import ModelType, PredictionTarget, ProductionModel
from apps.policy.models import InterestRate
from apps.scenarios.models import SavedScenario
from apps.vehicles.models import BodySegment, Brand, VehicleModel
from apps.vehicles.readiness import vehicle_readiness

pytestmark = pytest.mark.django_db

seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")

GFV_RESALE_NOTE = (
    "This residual is the lender's conservative guaranteed buy-back value. The expected market value (shown on the TCO "
    "tab) is usually higher."
)


class StubLogCurve:
    """A fitted-model stand-in on the LOG price scale (module-level so joblib can load it)."""

    def predict(self, rows):
        return [math.log(max(1.0 - 0.12 * age, 1e-9)) for age in rows["vehicle_age"]]


def deploy(tmp_path, *, target=PredictionTarget.LOG_RESALE_PRICE):
    path = tmp_path / "stub.joblib"
    joblib.dump(StubLogCurve(), path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.LOG_LINEAR
    production.model_file_path = str(path)
    production.prediction_target = target
    production.r2_score = 0.9124
    production.mae = 0.1473
    production.save()


@pytest.fixture
def bmw():
    brand = Brand.objects.create(name="BMW", tier_code="2")
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=brand, rate_percent="2.8000", is_active=True)
    return VehicleModel.objects.create(
        brand=brand, name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN, msrp="267800.00",
        engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998,
    )


@pytest.fixture
def macan_electric():
    brand = Brand.objects.create(name="Porsche", tier_code="1")
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=brand, rate_percent="3.5000", is_active=True)
    return VehicleModel.objects.create(
        brand=brand, name="Macan Electric", trim="Macan RWD", body_segment=BodySegment.SUV, msrp="575000.00",
        engine_capacity_kw="250.00", powertrain="bev",
    )


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


def tco(client, vehicle, tenure=60, downpayment="26780.00"):
    response = client.get("/api/depreciation/tco/", {
        "vehicle": vehicle.pk, "tenure_months": tenure, "mileage_band": "standard", "downpayment": downpayment,
    })
    assert response.status_code == 200, response.data
    return response.data


def comparison(client, vehicle, tenure=60, downpayment="26780.00"):
    response = client.get("/api/comparisons/", {
        "vehicle": vehicle.pk, "tenure_months": tenure, "mileage_band": "standard", "downpayment": downpayment,
    })
    assert response.status_code == 200, response.data
    return response.data


# --- the TCO response ---------------------------------------------------------------------------------------------


def test_a_car_the_model_covers_is_ml_model(client, bmw, tmp_path):
    deploy(tmp_path)

    data = tco(client, bmw)

    assert data["forecast_source"] == "ml_model"
    assert data["model_degraded"] is False and data["degraded_reason"] is None


def test_an_electric_car_is_an_unsupported_estimated_curve(client, macan_electric, tmp_path):
    deploy(tmp_path)

    data = tco(client, macan_electric, downpayment="57500.00")

    assert data["forecast_source"] == "estimated_curve_unsupported"
    assert data["model_degraded"] is True  # still an estimated curve, so the Arena still leaves it out of the race
    assert "does not cover electric cars yet" in data["degraded_reason"]


def test_a_body_type_the_model_does_not_know_is_unsupported(client, bmw, tmp_path):
    deploy(tmp_path)
    VehicleModel.objects.filter(pk=bmw.pk).update(body_segment="roadster")  # a segment added later

    data = tco(client, bmw)

    assert data["forecast_source"] == "estimated_curve_unsupported"
    assert "does not cover this body type yet" in data["degraded_reason"]


def test_a_car_with_no_engine_size_is_unsupported(bmw, tmp_path):
    deploy(tmp_path)
    VehicleModel.objects.filter(pk=bmw.pk).update(engine_capacity_cc=None)
    bmw.refresh_from_db()

    values, degraded, _reason = inference.predict_resale_curve(vehicle=bmw, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert forecast_source(bmw, degraded) == "estimated_curve_unsupported"
    assert coverage_gap(bmw) == "no_engine_size"


def test_with_no_model_deployed_every_car_is_model_unavailable(client, bmw):
    data = tco(client, bmw)

    assert data["forecast_source"] == "model_unavailable"
    assert data["model_degraded"] is True
    assert "switched off until a model passes the accuracy check" in data["degraded_reason"]


def test_a_model_that_predicts_the_old_target_counts_as_not_serving(client, bmw, tmp_path):
    deploy(tmp_path, target=PredictionTarget.RAW_RESALE_PRICE)

    assert tco(client, bmw)["forecast_source"] == "model_unavailable"


def test_an_electric_car_with_the_model_switched_off_is_model_unavailable_not_unsupported(client, macan_electric):
    """The order predict_resale_curve follows: no usable model comes first, whatever the car."""
    data = tco(client, macan_electric, downpayment="57500.00")

    assert data["forecast_source"] == "model_unavailable"
    assert "switched off" in data["degraded_reason"]


def test_a_runtime_failure_is_model_unavailable(client, bmw, tmp_path, monkeypatch):
    deploy(tmp_path)

    def boom(model, rows):
        raise RuntimeError("the prediction fell over")

    monkeypatch.setattr(inference, "_run_model_prediction", boom)

    data = tco(client, bmw)

    assert data["model_degraded"] is True
    assert data["forecast_source"] == "model_unavailable"
    assert "could not be produced for this car just now" in data["degraded_reason"]


def test_a_brand_with_no_price_tier_is_model_unavailable(client, bmw, tmp_path):
    deploy(tmp_path)
    Brand.objects.filter(pk=bmw.brand_id).update(tier_code="")
    bmw.refresh_from_db()

    assert coverage_gap(bmw) == "no_brand_tier"
    assert tco(client, bmw)["forecast_source"] == "model_unavailable"


# --- one eligibility check, not two ---------------------------------------------------------------------------------


@pytest.mark.parametrize("deployed", [True, False])
@pytest.mark.parametrize("change", [
    {}, {"powertrain": "bev", "engine_capacity_cc": None}, {"engine_capacity_cc": None}, {"body_segment": "roadster"},
])
def test_the_static_outlook_agrees_with_what_the_curve_actually_does(bmw, tmp_path, deployed, change):
    if deployed:
        deploy(tmp_path)
    VehicleModel.objects.filter(pk=bmw.pk).update(**change)
    bmw.refresh_from_db()

    _values, degraded, _reason = inference.predict_resale_curve(vehicle=bmw, annual_mileage_km=Decimal("15000"))
    source, gap = forecast_outlook(bmw)

    assert forecast_source(bmw, degraded) == source
    assert (source == FORECAST_SOURCE_ML) == (not degraded)
    assert (gap is None) == (source == FORECAST_SOURCE_ML)


def test_the_unsupported_gaps_are_exactly_the_ones_inference_words_as_not_covered(bmw, tmp_path):
    deploy(tmp_path)
    for change, gap, message in [
        ({"powertrain": "bev", "engine_capacity_cc": None}, "electric_car", inference.NOT_COVERED_EV_MESSAGE),
        ({"engine_capacity_cc": None}, "no_engine_size", inference.NOT_COVERED_EV_MESSAGE),
        ({"body_segment": "roadster"}, "body_type_not_mapped", inference.NOT_COVERED_BODY_MESSAGE),
    ]:
        VehicleModel.objects.filter(pk=bmw.pk).update(powertrain="petrol", engine_capacity_cc=1998,
                                                      body_segment=BodySegment.SEDAN)
        VehicleModel.objects.filter(pk=bmw.pk).update(**change)
        bmw.refresh_from_db()

        assert coverage_gap(bmw) == gap
        assert inference._resolve_car_features(bmw) == (None, message)
        assert forecast_outlook(bmw) == (FORECAST_SOURCE_UNSUPPORTED, gap)


def test_the_constants_are_the_three_documented_values():
    assert (FORECAST_SOURCE_ML, FORECAST_SOURCE_UNSUPPORTED, FORECAST_SOURCE_UNAVAILABLE) == (
        "ml_model", "estimated_curve_unsupported", "model_unavailable")


# --- GFV resale_note (Step 9) ---------------------------------------------------------------------------------------


def test_the_gfv_resale_note_is_there_when_the_model_serves_the_car(client, bmw, tmp_path):
    deploy(tmp_path)

    gfv = comparison(client, bmw)["gfv_leasing"]

    assert gfv["resale_note"] == GFV_RESALE_NOTE
    # the figures beside it are untouched (36.79% of RM 267,800 since Run 3 fix batch 6; was 35% -> 93,730.00)
    assert gfv["balloon_payment"] == "98523.62"


def test_the_gfv_resale_note_is_null_for_an_electric_car(client, macan_electric, tmp_path):
    deploy(tmp_path)

    gfv = comparison(client, macan_electric, downpayment="57500.00")["gfv_leasing"]

    assert "resale_note" in gfv and gfv["resale_note"] is None


def test_the_gfv_resale_note_is_null_when_no_model_is_serving(client, bmw):
    gfv = comparison(client, bmw)["gfv_leasing"]

    assert gfv["resale_note"] is None


def test_the_other_gfv_figures_do_not_depend_on_the_note(client, bmw, tmp_path):
    without = comparison(client, bmw)["gfv_leasing"]
    deploy(tmp_path)
    with_model = comparison(client, bmw)["gfv_leasing"]

    assert {k: v for k, v in without.items() if k != "resale_note"} == {
        k: v for k, v in with_model.items() if k != "resale_note"}


# --- the Arena ---------------------------------------------------------------------------------------------------------


def test_each_arena_entry_carries_its_cars_forecast_source(client, bmw, macan_electric, tmp_path):
    deploy(tmp_path)

    response = client.get("/api/comparisons/arena/", {
        "vehicles": [bmw.pk, macan_electric.pk], "tenure_months": 60, "mileage_band": "standard",
        "downpayment": "57500.00",
    })

    assert response.status_code == 200, response.data
    sources = {entry["vehicle_id"]: entry["forecast_source"] for entry in response.data["results"]}
    assert sources == {bmw.pk: "ml_model", macan_electric.pk: "estimated_curve_unsupported"}
    # unchanged: the estimated curve still sits out of the TCO race, so the lone ML car has nobody to beat
    assert response.data["winners"]["lowest_tco"] is None


# --- a saved snapshot and an older one ------------------------------------------------------------------------------------


def test_a_new_snapshot_keeps_the_source_and_the_null_note(client, macan_electric, regular_user, tmp_path):
    deploy(tmp_path)

    response = client.post("/api/scenarios/", {
        "title": "Macan Electric", "vehicle": macan_electric.pk,
        "inputs": {"tenure_months": 60, "mileage_band": "standard", "downpayment": "57500.00", "include_tco": True,
                   "scoring": None},
    }, format="json")

    assert response.status_code == 201, response.content
    payload = SavedScenario.objects.get(user=regular_user).payload
    assert payload["tco"]["forecast_source"] == "estimated_curve_unsupported"
    assert payload["comparison"]["gfv_leasing"]["resale_note"] is None


def test_an_older_snapshot_without_the_field_still_opens_as_saved(client, bmw, regular_user):
    old = {"tco_net": "245367.80", "model_degraded": True, "degraded_reason": "x", "monthly_forecast": []}
    scenario = SavedScenario.objects.create(user=regular_user, title="Before", vehicle=bmw, payload={"tco": old})

    response = client.get(f"/api/scenarios/{scenario.pk}/")

    assert response.status_code == 200
    assert response.data["payload"]["tco"] == old


# --- Vehicle Readiness (Step 8) ------------------------------------------------------------------------------------------


def forecast_check(vehicle):
    vehicle.refresh_from_db()  # a freshly created row still holds its price as the text it was created with
    report = vehicle_readiness(vehicle)
    return report, next(c for c in report["checks"] if c["key"] == "resale_forecast")


def test_readiness_says_machine_learning_model_for_a_covered_car(bmw, tmp_path):
    deploy(tmp_path)

    _report, check = forecast_check(bmw)

    assert check["label"] == "Resale forecast: machine-learning model"
    assert check["status"] == "info"


@pytest.mark.parametrize("change, reason", [
    ({"powertrain": "bev", "engine_capacity_cc": None}, "electric car"),
    ({"engine_capacity_cc": None}, "no engine size"),
    ({"body_segment": "roadster"}, "body type not mapped"),
])
def test_readiness_names_the_reason_the_estimated_curve_is_used(bmw, tmp_path, change, reason):
    deploy(tmp_path)
    VehicleModel.objects.filter(pk=bmw.pk).update(**change)
    bmw.refresh_from_db()

    _report, check = forecast_check(bmw)

    assert check["label"] == f"Resale forecast: estimated curve ({reason})"
    assert check["status"] == "info" and check["detail"]


def test_readiness_says_model_not_serving_when_nothing_is_deployed(bmw):
    _report, check = forecast_check(bmw)

    assert check["label"] == "Resale forecast: estimated curve (model not serving)"


def test_the_forecast_line_never_makes_a_car_need_attention(macan_electric):
    """An electric car on the estimated curve is expected: ready stays ready, and neither count moves."""
    with_note, check = forecast_check(macan_electric)
    others = [c for c in with_note["checks"] if c["key"] != "resale_forecast"]

    assert check["status"] == "info"
    assert with_note["missing_count"] == sum(c["status"] == "missing" for c in others)
    assert with_note["warning_count"] == sum(c["status"] == "warning" for c in others)
    assert with_note["status"] == ("ready" if with_note["missing_count"] == 0 else "needs_attention")
    assert with_note["missing_count"] == 0 and with_note["status"] == "ready"


def test_the_forecast_line_reads_the_same_check_the_tco_tab_uses(client, bmw, tmp_path):
    deploy(tmp_path)

    for change in ({}, {"body_segment": "roadster"}, {"engine_capacity_cc": None}):
        VehicleModel.objects.filter(pk=bmw.pk).update(**change)
        bmw.refresh_from_db()
        _report, check = forecast_check(bmw)
        source, _gap = forecast_outlook(bmw)

        assert check["label"].startswith("Resale forecast: machine-learning") == (source == FORECAST_SOURCE_ML)
