import math
from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import InterestRate, MileageBand, RoadTaxCcBand
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


class DecliningResaleEstimator:
    """A fake 'model' whose predicted value-retention RATIO (QA audit C8:
    inference.py now scales every raw prediction by the vehicle's own
    msrp, never feeds/expects an absolute RM figure from the model)
    declines linearly with vehicle age, at a chosen rate steeper than the
    straight-line fallback's fixed 1%/month - lets a test construct an
    exact, hand-verifiable negative-equity crossover with full control,
    since (after the 10% minimum downpayment fix - C6) no valid
    downpayment/tenure combination can produce a genuine crossover against
    the fallback's own 1%/month curve at all (see
    test_negative_equity_crossover_reported_through_the_endpoint's own
    docstring for the worked proof). Module-level (not nested in a test
    function) because joblib/pickle can't serialize a locally-defined
    class, same reasoning as test_inference_fallback.py's own
    WorkingEstimator.

    `initial_value`/`monthly_decline` are RATIOS (e.g. 1.0 / 0.015), not
    RM amounts - predict_resale_curve multiplies by msrp afterward, so a
    vehicle priced at msrp=100000.00 reproduces the exact same RM-scale
    curve (100000 - 1500*month) this test's docstring derives by hand.

    feature_rows[i][0] is age_years (see inference._build_feature_row).
    """

    def __init__(self, initial_value, monthly_decline):
        self.initial_value = initial_value
        self.monthly_decline = monthly_decline

    def predict(self, feature_rows):
        # ML batch 1: the model works on the LOG price, and the curve is
        # msrp x exp(f_m - f_0) - so returning log(ratio_m) reproduces the
        # same linear ratio curve exactly.
        return [
            math.log(max(self.initial_value - self.monthly_decline * age * 12, 1e-9))
            for age in feature_rows["vehicle_age"]
        ]


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def brand():
    # tier_code must be a real, parseable value: a real model is deployed
    # in test_resale_value_explanation_present_when_a_real_model_is_deployed
    # below, and inference.py now degrades (same as "no model deployed")
    # for a blank/unparseable tier_code.
    return Brand.objects.create(name="TCOBrand", tier_code="3")


@pytest.fixture
def vehicle(brand):
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SUV,
        msrp="100000.00", engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1498,
    )


@pytest.fixture
def interest_rate(brand):
    return InterestRate.objects.create(brand=brand, rate_percent="3.0000")


def request_tco(client, vehicle, tenure_months=36, mileage_band=MileageBand.STANDARD, downpayment="10000.00"):
    return client.get(
        "/api/depreciation/tco/",
        {
            "vehicle": vehicle.id,
            "tenure_months": tenure_months,
            "mileage_band": mileage_band,
            "downpayment": downpayment,
        },
    )


def test_requires_authentication(vehicle, interest_rate):
    client = APIClient()
    response = request_tco(client, vehicle)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Missing config -> clear 4xx, never a 500 -------------------------------


def test_missing_interest_rate_returns_400(user_client, vehicle):
    # The operating-cost rate tables exist (seeded by migration); only the
    # interest rate is missing.
    response = request_tco(user_client, vehicle)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "financing rate hasn't been set up" in response.data["detail"]


def test_a_vehicle_with_incomplete_specs_returns_a_plain_400_never_a_guess(user_client, brand, interest_rate):
    legacy = VehicleModel.objects.create(
        brand=brand, name="Legacy", trim="X", body_segment=BodySegment.SUV,
        msrp="100000.00", engine_capacity_kw="90.00",  # no powertrain / cc
    )

    response = request_tco(user_client, legacy)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "is missing its specs (powertrain / engine capacity)" in response.data["detail"]
    assert "Complete them in Fleet Management." in response.data["detail"]


def test_no_active_road_tax_band_for_the_vehicles_cc_returns_400(user_client, vehicle, interest_rate):
    RoadTaxCcBand.objects.filter(min_cc__lte=vehicle.engine_capacity_cc, max_cc__gte=vehicle.engine_capacity_cc).update(
        is_active=False
    )

    response = request_tco(user_client, vehicle)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    # The fixture is an SUV, so it reads the non-saloon table only.
    assert "No active non-saloon road tax band covers an engine capacity of 1,498 cc" in response.data["detail"]


# --- Comparison completes with a degraded ML forecast (no model deployed) --


def test_completes_with_degraded_flag_when_no_model_is_deployed(user_client, vehicle, interest_rate):
    response = request_tco(user_client, vehicle)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["model_degraded"] is True
    # Run 1 fix batch 5: no model is serving forecasts, said plainly.
    assert response.data["degraded_reason"] == (
        "Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast is "
        "switched off until a model passes the accuracy check."
    )
    assert len(response.data["monthly_forecast"]) == 61
    assert response.data["monthly_forecast"][0]["predicted_resale_value"] == "100000.00"
    # No real deployed model to explain, so this stays null too - never a
    # separate error, same graceful-degradation pattern as degraded_reason.
    assert response.data["resale_value_explanation"] is None


def test_resale_value_explanation_present_when_a_real_model_is_deployed(
    user_client, vehicle, interest_rate, tmp_path
):
    import joblib
    from sklearn.ensemble import RandomForestRegressor

    from apps.depreciation.tests.test_explanation import fit_log_price_estimator
    from apps.ml.models import ModelType, PredictionTarget, ProductionModel

    # ML batch 1: a real forest on the shared features and the LOG price.
    model_path = tmp_path / "model.joblib"
    joblib.dump(fit_log_price_estimator(RandomForestRegressor), model_path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = str(model_path)
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.save()

    response = request_tco(user_client, vehicle, tenure_months=36)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["model_degraded"] is False
    assert response.data["monthly_forecast"][0]["predicted_resale_value"] == "100000.00"
    explanation = response.data["resale_value_explanation"]
    assert explanation is not None
    assert set(explanation["contributions"].keys()) == {
        "vehicle_age", "mileage", "brand_code", "engine_litres", "body_type", "recond",
    }
    # Run 3 fix batch 5 (F-03): 2-dp strings like every other money field, adding up exactly.
    assert explanation["base_value"] == "100000.00"
    reconstructed = Decimal(explanation["base_value"]) + sum(Decimal(v) for v in explanation["contributions"].values())
    assert reconstructed == Decimal(explanation["predicted_value"])


def test_response_includes_operating_costs_and_tco(user_client, vehicle, interest_rate):
    response = request_tco(user_client, vehicle)

    assert Decimal(response.data["road_tax_annual"]) > 0
    assert Decimal(response.data["insurance_annual"]) > 0
    assert Decimal(response.data["maintenance_annual"]) > 0
    assert Decimal(response.data["tco_gross"]) > Decimal(response.data["tco_net"])


def test_operating_costs_come_from_the_vehicles_own_specs_with_a_basis_for_each(user_client, vehicle, interest_rate):
    """msrp 100,000 / 1,498 cc / petrol SUV, by hand:
      road tax    = JPJ NON-SALOON band 1,401-1,600 cc, flat RM120.00 (an SUV
                    since run 1 fix batch 3; the saloon table's RM90 before)
      insurance   = 1.8% x 100,000       = RM1,800.00 (no profile, so no NCD)
      maintenance = max(1.0% x 100,000 = 1,000, floor 1,200) = RM1,200.00
    """
    response = request_tco(user_client, vehicle)

    assert Decimal(response.data["road_tax_annual"]) == Decimal("120.00")
    assert Decimal(response.data["insurance_annual"]) == Decimal("1800.00")
    assert Decimal(response.data["maintenance_annual"]) == Decimal("1200.00")
    assert response.data["ncd_percent"] == "0.00"
    assert response.data["operating_cost_basis"] == {
        "road_tax": "1,498 cc petrol, non-saloon - JPJ cc schedule",
        "insurance": "1.8% of RM 100,000.00",
        "maintenance": "floor RM 1,200 (1.0% of price is lower)",
    }


# --- Negative equity crossover, through the real endpoint -------------------


def test_negative_equity_crossover_reported_through_the_endpoint(user_client, brand, interest_rate, tmp_path):
    """price=100000, downpayment=10000.00 (exactly the new 10% minimum -
    C6), tenure=108 -> principal=90000, HP balance(m) = 90000*(1-m/108).
    The crossover search only ever looks at months 0-60 regardless of
    tenure (HORIZON_MONTHS caps both resale_values and
    outstanding_balances at 61 entries).

    The old version of this test used a 5% downpayment, now rejected by
    the 10% minimum. Hand-checking the formulas shows *no* valid (>=10%)
    downpayment can ever produce a genuine crossover against the
    straight-line 1%/month fallback within months 0-60 either: at the
    most favourable case (exactly 10% down, the full 108-month tenure),
    resale and balance meet at *exactly* month 60 (both 40,000.00)
    without resale ever dipping below balance - surplus the whole
    window, by construction of the 10%-minimum rule itself. So this test
    deploys a declining-but-fully-controlled resale curve instead (a
    steeper 1.5%-of-price/month decline, vs. the fallback's 1%/month), to
    still prove the crossover/shortfall calculation is correct with a
    genuinely valid downpayment:

    resale(m) = 100000 - 1500*m. balance(m) = 90000*(1 - m/108).
    Setting them equal: 100000-1500m = 90000-833.333m -> 10000 = 666.667m
    -> m = 15 exactly - both equal 77,500.00, a tie, not a crossover
    (strictly "resale < balance").
    m=16: balance = 90000*(92/108) = 76,666.666... -> 76,666.67
    (round_currency); resale = 100000-1500*16 = 76,000.00. 76,000.00 <
    76,666.67 -> the first crossover. shortfall = 76,666.67 - 76,000.00
    = 666.67. (m=14 confirmed NOT a crossover: resale 79,000.00 >
    balance 78,333.33 - still a surplus.)

    Verified below against the real formulas.hp_outstanding_balance and
    formulas.find_negative_equity_crossover directly, as an independent
    oracle for this same hand-derivation.

    Run 1: the balance is now the reducing-balance amount to settle at the
    3% flat rate's effective rate (not principal x (1 - m/108)). Re-derived
    independently outside the app: month 11 resale 83,500.00 > balance
    82,729.54 (still a surplus); month 12 resale 82,000.00 < balance
    82,050.28 -> the first crossover, shortfall 50.28. (The straight line
    above gave month 16 / 666.67.)
    """
    import joblib

    from apps.depreciation import formulas
    from apps.ml.models import ModelType, PredictionTarget, ProductionModel

    model_path = tmp_path / "model.joblib"
    # Ratio-scale: 1.0 / 0.015 -> (after x msrp=100000.00) the exact same
    # 100000 - 1500*month RM curve this test's docstring derives by hand.
    joblib.dump(DecliningResaleEstimator(initial_value=1.0, monthly_decline=0.015), model_path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = str(model_path)
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.save()

    vehicle = VehicleModel.objects.create(
        brand=brand, name="Crossover", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1498,
    )

    expected_resale_values = [
        formulas.round_currency(Decimal(str(max(100000.00 - 1500.00 * m, 0.0)))) for m in range(61)
    ]
    expected_balances = [
        formulas.hp_outstanding_balance(Decimal("100000.00"), Decimal("10000.00"), 108, m, Decimal("0.03"))
        for m in range(61)
    ]
    expected_month, expected_shortfall = formulas.find_negative_equity_crossover(
        expected_resale_values, expected_balances
    )
    assert expected_month == 12
    assert expected_shortfall == Decimal("50.28")

    response = request_tco(user_client, vehicle, tenure_months=108, downpayment="10000.00")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["model_degraded"] is False
    assert response.data["negative_equity_crossover_month"] == expected_month
    assert Decimal(response.data["negative_equity_shortfall_amount"]) == expected_shortfall


def test_no_crossover_reported_when_downpayment_is_large(user_client, brand, interest_rate):
    vehicle = VehicleModel.objects.create(
        brand=brand, name="SafeEquity", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1498,
    )

    response = request_tco(user_client, vehicle, tenure_months=36, downpayment="60000.00")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["negative_equity_crossover_month"] is None
    assert response.data["negative_equity_shortfall_amount"] is None


# --- H10: net TCO credits net equity at month 60, not the raw resale value -


def test_net_tco_for_a_108_month_tenure_accounts_for_the_still_outstanding_loan_balance(
    user_client, vehicle, interest_rate
):
    """QA audit H10: msrp=100000.00, downpayment=10000.00 (10%, the
    minimum), rate=3.0000%, no model deployed (estimated fallback curve).

    Audit batch 4: the fallback's month-60 value is now the vehicle's GFV
    residual, not a flat 40%. This brand/powertrain has no adjustment, so at
    the standard mileage band month 60 retains the baseline 0.35: 100000 *
    0.35 = 35000.00. hp_outstanding_balance(100000,
    10000, tenure_months=108, month=60) = 90000 * (1 - 60/108) = 90000 *
    4/9 = 40000.00 EXACTLY - the loan is NOT repaid by month 60 for a
    108-month tenure, so net equity at month 60 is 35000.00 - 40000.00 =
    -5000.00 (the car is worth RM 5,000 less than is still owed), not the
    full resale value the old (buggy) formula credited.

    Run 1: the amount still owed at month 60 is now the reducing-balance
    settlement amount at the 3% flat rate's effective rate, 45,508.39
    (re-derived independently; the straight line above gave 40,000.00), so
    net equity is 35,000.00 - 45,508.39 = -10,508.39 and net TCO =
    88,949.80 + 10,508.39 = 99,458.19. Gross is unchanged.

    hp_monthly(108mo) = (90000/108) + (90000*0.03/12) = 833.33 + 225.00,
    rounds to 1058.33. gross = 10000 + 1058.33*60 (payment_months capped
    at the 60-month horizon) + (90/12)*60 + (1800/12)*60 + (1200/12)*60
    (1,498 cc petrol: JPJ RM90, insurance 1.8%, maintenance floor RM1,200 -
    RM3,090/yr = RM15,450 over the 5-year horizon) = 73499.80 + 15450.00 =
    88949.80 (independently verified via apps.depreciation.formulas
    directly, not just read off whatever the endpoint happened to
    return). net = gross - (-5000.00) = 88949.80 + 5000.00 = 93949.80 - a
    real RM 35,000 MORE than the old formula would have reported (gross -
    full resale = 53949.80), and no longer artificially far below the
    equivalent 60-month tenure's own net TCO (93950.00 - see the
    comparison test below) despite the 108-month loan accruing far more
    interest overall.

    Run 1 fix batch 3: the fixture is an SUV, so its road tax is the
    non-saloon table's flat RM120 (not RM90): +RM30 a year, +RM150 over the
    60-month horizon. Gross 88,949.80 -> 89,099.80; net 99,458.19 ->
    99,608.19. Nothing else moves.

    Run 3 fix batch 6: the standard band's 60-month residual is 0.3679 (was
    0.35), so the month-60 resale is 36,790.00 (+1,790.00) and the net falls by
    exactly that: 99,608.19 -> 97,818.19. Gross and the balance are unchanged.
    """
    response = request_tco(user_client, vehicle, tenure_months=108, downpayment="10000.00")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["model_degraded"] is True  # estimated fallback curve, as assumed above
    assert Decimal(response.data["tco_gross"]) == Decimal("89099.80")
    assert Decimal(response.data["tco_net"]) == Decimal("97818.19")


def test_108_month_net_tco_is_no_longer_misleadingly_cheaper_than_60_months(user_client, vehicle, interest_rate):
    """Same vehicle/downpayment, the only difference is tenure - 108
    months racks up far more interest overall (hp_monthly is lower per
    month, but the loan runs for 108 months instead of 60, and TCO's own
    60-month horizon still only credits whatever equity is real at month
    60). Before H10's fix, a 108-month net TCO of 53949.80 (see the
    docstring above) would have made it look RM 40,000 cheaper than the
    60-month tenure below - backwards, since 108 months is strictly the
    worse deal (same car, same downpayment, far more interest paid). The
    fix brings the two back in line with each other (93949.80 vs
    93950.00 - genuinely comparable, not one falsely appearing far
    cheaper).
    """
    response_108 = request_tco(user_client, vehicle, tenure_months=108, downpayment="10000.00")
    response_60 = request_tco(user_client, vehicle, tenure_months=60, downpayment="10000.00")

    assert response_108.status_code == status.HTTP_200_OK
    assert response_60.status_code == status.HTTP_200_OK

    tco_net_108 = Decimal(response_108.data["tco_net"])
    tco_net_60 = Decimal(response_60.data["tco_net"])

    # 60 months: hp = 90000/60 + 90000*0.03/12 = 1725.00 -> 10000 + 1725*60
    # + 15450 operating = 128950.00 gross; net = 128950 - 35000 resale (the
    # 0.35 month-60 residual) = 93950.00.
    # Run 1 fix batch 3: +RM150 on both (the SUV's non-saloon road tax, RM120
    # not RM90 a year, x 5 years) - 93,950.00 -> 94,100.00.
    # Run 3 fix batch 6: resale(60) 36,790.00 (0.3679, was 0.35), so both nets fall by 1,790.00.
    assert tco_net_60 == Decimal("92310.00")  # was 94,100.00
    # Run 1: reducing balance owes 45,508.39 at month 60 (not 40,000.00), so
    # the 108-month net is 99,608.19 (99,458.19 + 150) - now DEARER than 60
    # months, which is right: same car and downpayment, far more interest paid.
    assert tco_net_108 == Decimal("97818.19")  # was 99,608.19
    assert tco_net_108 > tco_net_60


# --- Request validation ----------------------------------------------------


@pytest.mark.parametrize("tenure_months", [11, 109])
def test_tenure_outside_range_rejected(user_client, vehicle, interest_rate, tenure_months):
    response = request_tco(user_client, vehicle, tenure_months=tenure_months)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_downpayment_must_be_less_than_price(user_client, vehicle, interest_rate):
    response = request_tco(user_client, vehicle, downpayment="100000.00")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
