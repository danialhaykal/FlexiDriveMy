"""Run 2 fix batch 3 (ML-3, A11, G6): the explanation card's figures are whole sen,
in the fixed order Age, Mileage, Brand tier, Engine size, Body type, Recond import,
and add up EXACTLY (base + parts == predicted, in sen) - on the TCO response that
the screen, the saved snapshot and the PDF all read."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor

from apps.depreciation.explanation import round_explanation
from apps.depreciation.inference import EXPLANATION_FACTORS
from apps.depreciation.tests.test_explanation import _deploy, fit_log_price_estimator
from apps.exports.comparison_rows import EXPLANATION_FACTOR_LABELS
from apps.ml.log_linear import LogLinearDepreciationModel
from apps.policy.models import InterestRate, MileageBand
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

FIXED_ORDER = ["vehicle_age", "mileage", "brand_code", "engine_litres", "body_type", "recond"]


def sen(value):
    return Decimal(str(value))


def assert_adds_up(explanation):
    total = sen(explanation["base_value"]) + sum(sen(v) for v in explanation["contributions"].values())
    assert total == sen(explanation["predicted_value"])


# --- the rounding, on hand-made numbers --------------------------------------------------------------------------


def raw(base, predicted, **parts):
    contributions = {factor: 0.0 for factor in FIXED_ORDER}
    contributions.update(parts)
    return {"base_value": base, "contributions": contributions, "predicted_value": predicted}


def test_the_fixed_order_is_one_list_shared_by_the_screen_and_the_pdf():
    assert EXPLANATION_FACTORS == FIXED_ORDER
    assert list(EXPLANATION_FACTOR_LABELS) == FIXED_ORDER


def test_values_are_rounded_half_up_to_whole_sen():
    result = round_explanation(raw(100000.0, 99890.004, vehicle_age=-100.004, mileage=-9.996))

    assert result["predicted_value"] == 99890.0
    assert result["contributions"]["vehicle_age"] == -100.0
    assert result["contributions"]["mileage"] == -10.0
    assert_adds_up(result)


def test_a_rounding_gap_goes_on_the_last_factor_that_is_not_zero():
    # 10.005 + 20.005 + 30.005 = 60.015: the parts round to 10.01 + 20.01 + 30.01 = 60.03 but the
    # whole rounds to 60.02, so one sen comes off the LAST non-zero factor (Brand tier), not the first.
    result = round_explanation(raw(1000.0, 1060.015, vehicle_age=10.005, mileage=20.005, brand_code=30.005))

    assert result["contributions"]["vehicle_age"] == 10.01
    assert result["contributions"]["mileage"] == 20.01
    assert result["contributions"]["brand_code"] == 30.0
    assert_adds_up(result)


def test_factors_after_the_adjusted_one_that_are_zero_stay_zero():
    result = round_explanation(raw(1000.0, 1030.014, vehicle_age=15.004, mileage=15.004))

    assert result["contributions"]["recond"] == 0.0
    assert result["contributions"]["body_type"] == 0.0
    assert_adds_up(result)


def test_when_every_part_rounds_to_zero_the_gap_goes_on_the_factor_that_moved_most():
    result = round_explanation(raw(1000.0, 1000.01, vehicle_age=0.004, mileage=0.002, brand_code=0.0004))

    assert result["contributions"]["vehicle_age"] == 0.01
    assert all(result["contributions"][f] == 0.0 for f in FIXED_ORDER if f != "vehicle_age")
    assert_adds_up(result)


def test_a_zero_change_stays_all_zero():
    result = round_explanation(raw(100000.0, 100000.0))

    assert set(result["contributions"].values()) == {0.0}
    assert_adds_up(result)


def test_none_stays_none():
    assert round_explanation(None) is None


def test_the_result_is_in_the_fixed_order_whatever_order_it_came_in():
    shuffled = {"recond": 0.0, "body_type": -1.0, "engine_litres": 0.0, "brand_code": -2.0, "mileage": -3.0,
                "vehicle_age": -4.0}

    result = round_explanation({"base_value": 100.0, "contributions": shuffled, "predicted_value": 90.0})

    assert list(result["contributions"]) == FIXED_ORDER
    assert_adds_up(result)


@pytest.mark.parametrize("seed", range(40))
def test_random_explanations_always_add_up_exactly(seed):
    import random

    rng = random.Random(seed)
    parts = {factor: rng.uniform(-30000, 3000) * rng.choice([0, 1, 1, 1]) for factor in FIXED_ORDER}
    base = round(rng.uniform(80000, 600000), 2)
    predicted = base + sum(parts.values())

    result = round_explanation({"base_value": base, "contributions": parts, "predicted_value": predicted})

    assert_adds_up(result)
    assert list(result["contributions"]) == FIXED_ORDER
    # Each part moved by at most the rounding gap plus half a sen from its exact value.
    for factor in FIXED_ORDER:
        assert abs(sen(result["contributions"][factor]) - Decimal(str(parts[factor]))) <= Decimal("0.04")


# --- on the real TCO response -----------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def patient_explainer(settings):
    """SHAP's very first call in a fresh process imports and compiles for several
    seconds; the production timeout is for requests, not for a cold test run."""
    settings.ML_INFERENCE_TIMEOUT_SECONDS = 120


@pytest.fixture
def car():
    brand = Brand.objects.create(name="RoundingBrand", tier_code="3")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN,
        msrp="265800.00", engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1998,
    )


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


def tco(client, car, tenure):
    response = client.get("/api/depreciation/tco/", {
        "vehicle": car.pk, "tenure_months": tenure, "mileage_band": MileageBand.STANDARD, "downpayment": "26580.00",
    })
    assert response.status_code == 200, response.data
    return response.data


@pytest.mark.parametrize("estimator_cls", [RandomForestRegressor, GradientBoostingRegressor, LogLinearDepreciationModel])
@pytest.mark.parametrize("tenure", [12, 30, 36, 48, 60])
def test_the_tco_explanation_adds_up_to_the_sen_for_every_model_type(user_client, car, tmp_path, estimator_cls, tenure):
    _deploy(tmp_path, fit_log_price_estimator(estimator_cls))

    explanation = tco(user_client, car, tenure)["resale_value_explanation"]

    assert explanation is not None
    assert list(explanation["contributions"]) == FIXED_ORDER
    assert_adds_up(explanation)
    # Whole sen: nothing beyond two decimals anywhere.
    for value in (explanation["base_value"], explanation["predicted_value"], *explanation["contributions"].values()):
        assert sen(value) == sen(value).quantize(Decimal("0.01"))


@pytest.mark.parametrize("tenure", [12, 24, 30, 36, 48, 60])
def test_the_predicted_value_equals_the_tco_curve_at_that_month_to_the_sen(user_client, car, tmp_path, tenure):
    _deploy(tmp_path, fit_log_price_estimator(LogLinearDepreciationModel))

    report = tco(user_client, car, tenure)

    curve_value = Decimal(report["monthly_forecast"][tenure]["predicted_resale_value"])
    assert sen(report["resale_value_explanation"]["predicted_value"]) == curve_value
