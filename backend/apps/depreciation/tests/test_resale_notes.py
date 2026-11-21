"""Run 2 fix batch 2 (E3, C6, E5): the sentences that say what the two resale
figures are - words only, built from numbers the report already holds.

Vehicle: BMW 3 Series 320i Sport (RM 265,800, 2.8% flat, 36.79% GFV residual at
60 months -> balloon RM 97,787.82; Run 3 fix batch 6, was 35% / RM 93,030.00),
standard band, 10% down. The ML case uses a
stand-in log-linear model whose log price falls so that 40% of the price is kept
at year 5 (RM 106,320.00, 40.0%): the wording and rounding are what is tested,
not the real model (the real model's figures are asserted in
apps/exports/tests/test_pdf_report_run2_batch1.py).
"""

import importlib
import math
from decimal import Decimal

import joblib
import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient

from apps.depreciation import resale_notes
from apps.ml.models import ModelType, PredictionTarget, ProductionModel
from apps.ml.serializers import MAE_UNIT_LOG_PRICE, format_mae, typical_error_percent
from apps.policy.models import InterestRate
from apps.scenarios.models import SavedScenario
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal
seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")

VIEWS_TAIL = (
    " The GFV figure is a guaranteed buy-back price that lenders set conservatively; the prediction is the expected "
    "market price, so the two are different things and can differ. Subscription fees are priced on the same "
    "conservative residual as GFV."
)
FORECAST_LOG_LINEAR = (
    "Predicted resale value is a machine-learning estimate for this car's brand tier, age and mileage, scaled to this "
    "car's own price. Cars in the same brand tier share the same shape."
)
GFV_RESALE_NOTE = (
    "This residual is the lender's conservative guaranteed buy-back value. The expected market value (shown on the TCO "
    "tab) is usually higher."
)


class StubLogCurve:
    """A fitted-model stand-in on the LOG price scale: 12% of the new price is lost per year of age, so the
    curve keeps 88/76/64/52/40% at years 1-5. Module-level so joblib can load it."""

    def predict(self, rows):
        return [math.log(max(1.0 - 0.12 * age, 1e-9)) for age in rows["vehicle_age"]]


def deploy(tmp_path, *, model_type=ModelType.LOG_LINEAR, mae=0.1473, target=PredictionTarget.LOG_RESALE_PRICE):
    path = tmp_path / "stub.joblib"
    joblib.dump(StubLogCurve(), path)
    production = ProductionModel.get_singleton()
    production.model_type = model_type
    production.model_file_path = str(path)
    production.prediction_target = target
    production.r2_score = 0.9124
    production.mae = mae
    production.save()
    return production


@pytest.fixture
def bmw():
    brand = Brand.objects.create(name="BMW", tier_code="2")
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=brand, rate_percent="2.8000", is_active=True)
    return VehicleModel.objects.create(
        brand=brand, name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN, msrp="265800.00",
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


def tco(client, vehicle, tenure=60, downpayment="26580.00"):
    response = client.get("/api/depreciation/tco/", {
        "vehicle": vehicle.pk, "tenure_months": tenure, "mileage_band": "standard", "downpayment": downpayment,
    })
    assert response.status_code == 200, response.data
    return response.data


# --- resale_views_note: the exact wording --------------------------------------------------------------------------


def test_views_note_has_the_exact_wording_with_the_bmw_60_month_numbers(client, bmw, tmp_path):
    deploy(tmp_path)

    note = tco(client, bmw)["resale_views_note"]

    assert note == (
        "At month 60, the lender's GFV residual for this car is RM 97,787.82 (36.79% of the price), while the "
        "predicted market value is RM 106,320.00 (40.0% of the price)." + VIEWS_TAIL
    )


def test_views_note_unit_with_the_real_run10_figures():
    """BMW 320i, 60 months, run 10's real curve: balloon RM 93,030.00 (35%), predicted RM 134,655.29 = 50.66%."""
    note = resale_notes.build_resale_views_note(
        tenure_months=60, gfv={"balloon_payment": D("93030.00"), "residual_value_ratio": D("0.3500")},
        predicted_value=D("134655.29"), price=D("265800.00"), degraded=False,
    )

    assert note == (
        "At month 60, the lender's GFV residual for this car is RM 93,030.00 (35% of the price), while the predicted "
        "market value is RM 134,655.29 (50.7% of the price)." + VIEWS_TAIL
    )


@pytest.mark.parametrize(
    "ratio, shown", [("0.3500", "35"), ("0.5000", "50"), ("0.4125", "41.25"), ("0.1000", "10"), ("0.3567", "35.67")]
)
def test_the_residual_percentage_is_shown_without_trailing_zeros(ratio, shown):
    note = resale_notes.build_resale_views_note(
        tenure_months=36, gfv={"balloon_payment": D("1000.00"), "residual_value_ratio": D(ratio)},
        predicted_value=D("5000.00"), price=D("10000.00"), degraded=False,
    )
    assert f"(%s%% of the price), while" % shown in note


@pytest.mark.parametrize("predicted, shown", [("5065.00", "50.7"), ("5064.99", "50.6"), ("5000.00", "50.0"), ("1.00", "0.0")])
def test_the_predicted_percentage_is_one_decimal_half_up(predicted, shown):
    note = resale_notes.build_resale_views_note(
        tenure_months=60, gfv={"balloon_payment": D("3500.00"), "residual_value_ratio": D("0.3500")},
        predicted_value=D(predicted), price=D("10000.00"), degraded=False,
    )
    assert f"({shown}% of the price). The GFV figure" in note


# --- resale_views_note: when it is null -----------------------------------------------------------------------------


@pytest.mark.parametrize("tenure", [72, 108, 18])
def test_views_note_is_null_outside_the_gfv_tenures(client, bmw, tmp_path, tenure):
    deploy(tmp_path)

    data = tco(client, bmw, tenure=tenure)

    assert data["resale_views_note"] is None
    assert data["pathway_tco"]["gfv_retain"]["available"] is False  # no GFV, so nothing to compare with
    assert data["resale_forecast_note"] is not None  # the model is serving: that note is independent


def test_views_note_is_null_when_the_downpayment_leaves_no_gfv(client, bmw, tmp_path):
    deploy(tmp_path)

    data = tco(client, bmw, downpayment="200000.00")  # above price - balloon (RM 172,770): GFV unavailable

    assert data["pathway_tco"]["gfv_retain"]["available"] is False
    assert data["resale_views_note"] is None


def test_views_note_is_null_when_the_curve_is_the_estimated_fallback(client, bmw):
    """No model deployed: the fallback curve is anchored to the same GFV residuals, so the two figures are equal
    by construction and there is nothing to explain."""
    data = tco(client, bmw)

    assert data["model_degraded"] is True
    assert data["pathway_tco"]["gfv_retain"]["available"] is True  # GFV exists...
    assert data["resale_views_note"] is None  # ...but the note is still null on the fallback
    assert data["resale_forecast_note"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(gfv=None),
        dict(degraded=True),
        dict(predicted_value=None),
        dict(tenure_months=11),
        dict(tenure_months=61),
        dict(tenure_months=0),
        dict(price=D("0")),
    ],
)
def test_views_note_unit_null_cases(kwargs):
    args = dict(
        tenure_months=60, gfv={"balloon_payment": D("93030.00"), "residual_value_ratio": D("0.3500")},
        predicted_value=D("134655.29"), price=D("265800.00"), degraded=False,
    )
    args.update(kwargs)
    assert resale_notes.build_resale_views_note(**args) is None


def test_the_boundary_tenures_get_a_note():
    for tenure in (12, 60):
        assert resale_notes.build_resale_views_note(
            tenure_months=tenure, gfv={"balloon_payment": D("1.00"), "residual_value_ratio": D("0.5000")},
            predicted_value=D("2.00"), price=D("10.00"), degraded=False,
        ).startswith(f"At month {tenure}, ")


# --- resale_forecast_note ------------------------------------------------------------------------------------------


def test_forecast_note_has_the_exact_wording_with_the_metric_derived_percentage(client, bmw, tmp_path):
    deploy(tmp_path, mae=0.1473)  # run 10's log-linear MAE: e^0.1473 - 1 = 15.87% -> 16

    note = tco(client, bmw)["resale_forecast_note"]

    assert note == FORECAST_LOG_LINEAR + " Typical error is about 16% of the price."


@pytest.mark.parametrize("mae", [0.0, 0.05, 0.1, 0.1473, 0.2022, 0.2012, 0.4055, 0.7])
def test_the_percentage_is_exactly_what_the_ml_page_shows(tmp_path, mae):
    """Same helper, same rounding: the sentence and the ML page's "typical error ≈ N% of price" can't disagree."""
    deploy(tmp_path, mae=mae)

    note = resale_notes.build_resale_forecast_note(degraded=False)

    page = format_mae(mae, MAE_UNIT_LOG_PRICE)  # "typical error ≈ 16% of price"
    assert page == f"typical error ≈ {typical_error_percent(mae)}% of price"
    assert note.endswith(f"Typical error is about {typical_error_percent(mae)}% of the price.")


def test_the_ml_page_and_the_note_read_the_deployed_runs_own_stored_metric(tmp_path, admin_user):
    from apps.ml.models import MLTrainingRun

    run = MLTrainingRun.objects.create(
        status="succeeded", prediction_target=PredictionTarget.LOG_RESALE_PRICE, ll_r2=0.9124, ll_mae=0.1473,
        deployed=True, deployed_model_type=ModelType.LOG_LINEAR,
    )
    production = deploy(tmp_path, mae=run.ll_mae)
    production.training_run = run
    production.save()
    client = APIClient()
    client.force_authenticate(user=admin_user)

    on_the_page = client.get("/api/ml/production-model/").data["mae_display"]

    assert on_the_page == "typical error ≈ 16% of price"
    assert resale_notes.build_resale_forecast_note(degraded=False).endswith("Typical error is about 16% of the price.")


def test_the_error_sentence_is_dropped_when_the_metric_is_not_available(tmp_path):
    deploy(tmp_path, mae=None)

    assert resale_notes.build_resale_forecast_note(degraded=False) == FORECAST_LOG_LINEAR


def test_the_error_sentence_is_dropped_when_the_metric_is_absurd(tmp_path):
    deploy(tmp_path, mae=900.0)  # too large to mean anything as a percentage (the ML page falls back too)

    assert resale_notes.build_resale_forecast_note(degraded=False) == FORECAST_LOG_LINEAR


def test_a_deployed_tree_model_does_not_claim_a_shared_shape_per_tier(tmp_path):
    deploy(tmp_path, model_type=ModelType.GRADIENT_BOOSTING, mae=0.2005)

    note = resale_notes.build_resale_forecast_note(degraded=False)

    assert note == (
        "Predicted resale value is a machine-learning estimate from this car's brand tier, age, mileage, engine size "
        "and body type, scaled to this car's own price. Typical error is about 22% of the price."
    )
    assert "share the same shape" not in note


def test_forecast_note_is_null_on_the_fallback_and_with_nothing_compatible_deployed(tmp_path):
    assert resale_notes.build_resale_forecast_note(degraded=True) is None
    assert resale_notes.build_resale_forecast_note(degraded=False) is None  # no model row content at all
    deploy(tmp_path, target=PredictionTarget.VALUE_RETENTION_RATIO)
    assert resale_notes.build_resale_forecast_note(degraded=False) is None  # a target inference refuses
    deploy(tmp_path, target="")
    assert resale_notes.build_resale_forecast_note(degraded=False) is None


def test_the_electric_car_gets_neither_note_because_it_uses_the_fallback(client, macan_electric, tmp_path):
    deploy(tmp_path)

    data = tco(client, macan_electric, downpayment="57500.00")

    assert data["model_degraded"] is True
    assert "does not cover electric cars yet" in data["degraded_reason"]  # its own message; no second one
    assert data["resale_views_note"] is None
    assert data["resale_forecast_note"] is None


def test_an_unmapped_body_type_gets_neither_note(client, bmw, tmp_path):
    deploy(tmp_path)
    VehicleModel.objects.filter(pk=bmw.pk).update(body_segment="roadster")  # a segment added later

    data = tco(client, bmw)

    assert data["model_degraded"] is True
    assert data["resale_views_note"] is None and data["resale_forecast_note"] is None


# --- the report is otherwise unchanged -----------------------------------------------------------------------------------


def test_the_notes_are_the_only_new_keys_and_no_figure_moves(client, bmw, tmp_path):
    fallback = tco(client, bmw)  # no model: the notes are null
    deploy(tmp_path)
    served = tco(client, bmw)

    assert {"resale_views_note", "resale_forecast_note"} <= set(fallback) and {"resale_views_note", "resale_forecast_note"} <= set(served)
    # The fallback BMW 60-month goldens (run 1 fix batch 4; resale and net moved with the
    # recalibrated standard band in Run 3 fix batch 6: 93,030.00 / 245,367.80 before).
    assert fallback["hp_monthly"] == "4545.18"
    assert fallback["tco_gross"] == "338397.80" and fallback["tco_net"] == "240609.98"
    assert (fallback["road_tax_annual"], fallback["insurance_annual"], fallback["maintenance_annual"]) == (
        "379.00", "4784.40", "2658.00")
    assert fallback["monthly_forecast"][60]["predicted_resale_value"] == "97787.82"
    # Serving the model changes the curve (as it always did) and nothing the notes touch.
    assert served["hp_monthly"] == fallback["hp_monthly"]
    assert served["monthly_forecast"][60]["predicted_resale_value"] == "106320.00"


# --- the GFV block on the Financing Pathways tab --------------------------------------------------------------------------


def test_the_gfv_block_carries_the_fixed_resale_note(client, bmw, tmp_path):
    deploy(tmp_path)  # run 2 fix batch 3: the note is only there when the machine-learning forecast is serving
    response = client.get("/api/comparisons/", {
        "vehicle": bmw.pk, "tenure_months": 60, "mileage_band": "standard", "downpayment": "26580.00",
    })

    gfv = response.data["gfv_leasing"]
    assert gfv["resale_note"] == GFV_RESALE_NOTE
    # the figures beside it are the comparison's own (Run 3 fix batch 6: was 93,030.00 / 2,994.68)
    assert gfv["balloon_payment"] == "97787.82"
    assert gfv["monthly_instalment"] == "2915.38"
    assert "resale_note" not in response.data["hire_purchase"]


def test_only_the_gfv_block_has_it_at_a_tenure_where_all_three_pathways_exist(client, bmw, tmp_path):
    deploy(tmp_path)  # run 2 fix batch 3: the note is only there when the machine-learning forecast is serving
    response = client.get("/api/comparisons/", {
        "vehicle": bmw.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "26580.00",
    })

    assert response.data["gfv_leasing"]["resale_note"] == GFV_RESALE_NOTE
    assert "resale_note" not in response.data["hire_purchase"]
    assert "resale_note" not in response.data["subscription"]


def test_no_gfv_block_means_no_resale_note(client, bmw):
    response = client.get("/api/comparisons/", {
        "vehicle": bmw.pk, "tenure_months": 72, "mileage_band": "standard", "downpayment": "26580.00",
    })

    assert response.data["gfv_leasing"] is None
    assert "GFV leasing" in response.data["unavailable"]["gfv_leasing"]


# --- saved snapshots -----------------------------------------------------------------------------------------------------------


def test_a_new_saved_snapshot_carries_the_notes_exactly_as_the_live_screen_shows_them(client, bmw, tmp_path, regular_user):
    deploy(tmp_path)

    response = client.post("/api/scenarios/", {
        "title": "Run 2 batch 2", "vehicle": bmw.pk,
        "inputs": {"tenure_months": 60, "mileage_band": "standard", "downpayment": "26580.00", "include_tco": True,
                   "scoring": None},
    }, format="json")

    assert response.status_code == 201, response.content
    saved = SavedScenario.objects.get(user=regular_user).payload
    live = tco(client, bmw)
    assert saved["tco"]["resale_views_note"] == live["resale_views_note"] and live["resale_views_note"]
    assert saved["tco"]["resale_forecast_note"] == live["resale_forecast_note"] and live["resale_forecast_note"]
    assert saved["comparison"]["gfv_leasing"]["resale_note"] == GFV_RESALE_NOTE


def test_an_older_snapshot_without_the_keys_still_opens(client, bmw, regular_user):
    old_tco = {"tco_net": "245367.80", "monthly_forecast": []}  # frozen before these keys existed
    scenario = SavedScenario.objects.create(
        user=regular_user, title="Saved before run 2 batch 2", vehicle=bmw, payload={"tco": old_tco},
    )

    response = client.get(f"/api/scenarios/{scenario.pk}/")

    assert response.status_code == 200
    assert response.data["payload"]["tco"] == old_tco  # returned exactly as saved, nothing added
