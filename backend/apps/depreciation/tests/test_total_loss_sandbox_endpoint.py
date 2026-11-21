import math
from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.depreciation import formulas
from apps.depreciation.inference import DEGRADED_MESSAGE
from apps.policy.models import InterestRate, MileageBand, ResidualValueMatrix
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db

SANDBOX_URL = "/api/depreciation/total-loss-sandbox/"


class DecliningResaleEstimator:
    """A fake 'model' whose predicted value-retention RATIO (QA audit C8:
    inference.py now scales every raw prediction by the vehicle's own
    msrp, never feeds/expects an absolute RM figure from the model)
    declines linearly with vehicle age, at a chosen rate - lets a test
    construct an exact, hand-verifiable shortfall with full control,
    since (after the 10% minimum downpayment fix - C6) no valid
    downpayment can produce a genuine HP shortfall against the
    straight-line fallback's fixed 1%/month curve at all (same reasoning as
    test_tco_endpoint.py::test_negative_equity_crossover_reported_through_the_endpoint,
    which hits the identical issue). Module-level because joblib/pickle
    can't serialize a locally-defined class.
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
    return Brand.objects.create(name="TotalLossBrand", tier_code="3")


@pytest.fixture
def vehicle(brand):
    return VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SUV,
        msrp="100000.00", engine_capacity_kw="90.00",
    )


@pytest.fixture
def interest_rate(brand):
    return InterestRate.objects.create(brand=brand, rate_percent="3.0000")


@pytest.fixture
def residual_ratio_36(brand):
    return ResidualValueMatrix.objects.create(
        brand=brand, tenure_months=36, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.5000"
    )


@pytest.fixture
def residual_ratio_108(brand):
    return ResidualValueMatrix.objects.create(
        brand=brand, tenure_months=108, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.3000"
    )


@pytest.fixture
def fully_configured(vehicle, interest_rate, residual_ratio_36):
    return vehicle


def sandbox_params(vehicle, **overrides):
    # downpayment is exactly 10% of the 100000.00 fixture vehicle's msrp
    # - the new C6 minimum, not an arbitrary round number.
    params = {
        "vehicle": vehicle.id,
        "tenure_months": 36,
        "mileage_band": MileageBand.STANDARD,
        "downpayment": "10000.00",
        "loss_month": 18,
    }
    params.update(overrides)
    return params


def test_requires_authentication(fully_configured):
    client = APIClient()
    response = client.get(SANDBOX_URL, sandbox_params(fully_configured))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Reference case: HP/GFV balances verified against the formulas directly


def test_reference_case_matches_hp_and_gfv_formulas_directly(user_client, fully_configured):
    """price=100000, downpayment=10000, tenure=36, residual=50% -> balloon=50000.
    No model deployed, so resale falls back to the estimated curve anchored
    to the GFV residuals (audit batch 4). At month 18 (standard mileage, no
    adjustments) that is the interpolation between the month-12 anchor
    (0.7807) and the month-24 anchor (0.6207): 0.7807 - 0.16 x 6/12 = 0.7007, so
    100000 x 0.7007 = 70070.00 (Run 3 fix batch 6: the recalibrated standard band;
    it was 0.77 / 0.61 -> 69,000.00, and the old straight line gave 82000.00).

    Run 1: the balances are the reducing-balance amounts to settle at the
    3% flat rate's effective rate (formulas fed annual_rate=0.03, as the
    endpoint does): HP 46,911.79 and GFV 70,569.89 at month 18, re-derived
    independently outside the app (the old straight line gave 45,000.00 and
    70,000.00).
    """
    response = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, loss_month=18))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["model_degraded"] is True

    expected_resale = Decimal("70070.00")

    expected_hp_balance = formulas.hp_outstanding_balance(
        Decimal("100000.00"), Decimal("10000.00"), 36, 18, Decimal("0.03")
    )
    expected_gfv_balance = formulas.gfv_outstanding_balance(
        price=Decimal("100000.00"), downpayment=Decimal("10000.00"), tenure_months=36, month=18,
        gfv_balloon=Decimal("50000.00"), annual_rate=Decimal("0.03"),
    )
    assert (expected_hp_balance, expected_gfv_balance) == (Decimal("46911.79"), Decimal("70569.89"))

    hp = response.data["hire_purchase"]
    gfv = response.data["gfv_leasing"]
    assert Decimal(hp["insurance_payout"]) == expected_resale
    assert Decimal(hp["outstanding_balance"]) == expected_hp_balance
    assert Decimal(hp["net_position"]) == expected_resale - expected_hp_balance

    assert Decimal(gfv["insurance_payout"]) == expected_resale
    assert Decimal(gfv["outstanding_balance"]) == expected_gfv_balance
    assert Decimal(gfv["net_position"]) == expected_resale - expected_gfv_balance


# --- Both directions: a surplus case and a shortfall case ------------------


def test_surplus_case_both_hp_and_gfv_show_a_positive_net_position(user_client, fully_configured):
    # Run 1: the reducing-balance amount to settle is front-loaded with
    # interest, so GFV's month-12 surplus (+333.33 under the old straight
    # line) became a -170.04 shortfall; the surplus case moves to month 6.
    # Resale 100000 x (1 - 0.2193 x 6/12) = 89,035.00 (Run 3 fix batch 6; was 88,500.00
    # on the 0.77 month-12 anchor); amounts to settle at the 3% flat rate's effective
    # rate, re-derived independently: HP 76,042.32, GFV 83,645.96.
    response = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, loss_month=6))

    assert Decimal(response.data["hire_purchase"]["net_position"]) == Decimal("12992.68")
    assert Decimal(response.data["gfv_leasing"]["net_position"]) == Decimal("5389.04")


def test_shortfall_case_negative_net_position(user_client, brand, interest_rate, residual_ratio_108, tmp_path):
    """price=100000, downpayment=10000.00 (exactly the new 10% minimum -
    C6), tenure=108, residual=30% -> balloon=30000.00. The old version of
    this test used a 5% downpayment to force a shortfall against the
    straight-line fallback - no longer possible at all once downpayment
    is floored at 10% (see test_tco_endpoint.py's own crossover test for
    the full worked proof), so this deploys the same controlled,
    declining fake resale curve that test uses.

    ML batch 2: the model is read at whole years and month 16 is interpolated
    on the log scale between year 1 (0.82) and year 2 (0.64): resale(16) =
    100000 x 0.82 x (0.64 / 0.82)^(4/12) = 75,498.08 (was 100000 - 1500 x 16 =
    76,000.00 when every month was read directly).
    Run 1: the balances are the reducing-balance amounts to settle at the
    3% flat rate's effective rate, re-derived independently: HP 79,301.97
    (was 76,666.67 straight-line) -> net -3,301.97, a real shortfall; GFV
    82,517.43 (was 81,111.11) -> net -6,517.43 - a bigger shortfall, since
    GFV's balloon is still owed in full.
    """
    import joblib

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

    # ML batch 1: the model covers only cars with an engine cc (no EVs).
    vehicle = VehicleModel.objects.create(
        brand=brand, name="Shortfall", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1498,
    )

    expected_hp_balance = formulas.hp_outstanding_balance(
        Decimal("100000.00"), Decimal("10000.00"), 108, 16, Decimal("0.03")
    )
    expected_gfv_balance = formulas.gfv_outstanding_balance(
        price=Decimal("100000.00"), downpayment=Decimal("10000.00"), tenure_months=108, month=16,
        gfv_balloon=Decimal("30000.00"), annual_rate=Decimal("0.03"),
    )
    assert expected_hp_balance == Decimal("79301.97")
    assert expected_gfv_balance == Decimal("82517.43")

    response = user_client.get(
        SANDBOX_URL,
        sandbox_params(vehicle, tenure_months=108, downpayment="10000.00", loss_month=16),
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.data["model_degraded"] is False

    hp = response.data["hire_purchase"]
    gfv = response.data["gfv_leasing"]
    assert Decimal(hp["insurance_payout"]) == Decimal("75498.08")
    assert Decimal(hp["outstanding_balance"]) == expected_hp_balance
    assert Decimal(hp["net_position"]) == Decimal("75498.08") - expected_hp_balance
    assert Decimal(hp["net_position"]) < 0

    assert Decimal(gfv["outstanding_balance"]) == expected_gfv_balance
    assert Decimal(gfv["net_position"]) == Decimal("75498.08") - expected_gfv_balance
    assert Decimal(gfv["net_position"]) < Decimal(hp["net_position"])  # GFV's balloon makes it worse


# --- excess_amount is a self-declared input that changes the real result ---


def test_excess_amount_reduces_payout_and_can_flip_a_surplus_into_a_shortfall(user_client, fully_configured):
    # Month 6 (see the surplus test above): payout 89035.00, GFV net +5,389.04.
    # Run 3 fix batch 6: the payout rose by 535.00 (recalibrated standard band), so a
    # RM 5,000 excess no longer flips GFV (it was 88,500 - 5,000 - 83,645.96 = -145.96);
    # RM 6,000 does.
    baseline = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, loss_month=6))
    assert Decimal(baseline.data["gfv_leasing"]["net_position"]) == Decimal("5389.04")

    with_excess = user_client.get(
        SANDBOX_URL, sandbox_params(fully_configured, loss_month=6, excess_amount="6000.00")
    )
    assert with_excess.status_code == status.HTTP_200_OK

    # payout: 89035 - 6000 = 83035.00.
    assert Decimal(with_excess.data["hire_purchase"]["insurance_payout"]) == Decimal("83035.00")
    # GFV: 83035 - 83645.96 = -610.96 (flipped from the +5,389.04 surplus).
    assert Decimal(with_excess.data["gfv_leasing"]["net_position"]) == Decimal("-610.96")
    # HP: 83035 - 76042.32 = 6992.68 (still a surplus - its balance is much lower).
    assert Decimal(with_excess.data["hire_purchase"]["net_position"]) == Decimal("6992.68")


def test_excess_amount_defaults_to_zero_when_omitted(user_client, fully_configured):
    params = sandbox_params(fully_configured, loss_month=18)
    assert "excess_amount" not in params

    response = user_client.get(SANDBOX_URL, params)

    assert response.status_code == status.HTTP_200_OK
    assert Decimal(response.data["excess_amount"]) == Decimal("0.00")
    assert Decimal(response.data["hire_purchase"]["insurance_payout"]) == Decimal("70070.00")


# --- Subscription: no ownership exposure, always ----------------------------


@pytest.mark.parametrize(
    # Month 1, not 0: run 1 fix batch 5 refuses month 0 ("Choose a month from 1 to {tenure}.").
    "overrides", [{}, {"loss_month": 1, "excess_amount": "50000.00"}, {"loss_month": 36}]
)
def test_subscription_always_reports_no_ownership_exposure(user_client, fully_configured, overrides):
    response = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, **overrides))
    assert response.status_code == status.HTTP_200_OK
    subscription = response.data["subscription"]
    assert subscription["has_ownership_exposure"] is False
    assert subscription["outstanding_balance"] is None
    assert subscription["net_position"] is None

    assert response.data["hire_purchase"]["has_ownership_exposure"] is True
    assert response.data["gfv_leasing"]["has_ownership_exposure"] is True


# --- Request validation ------------------------------------------------


def test_loss_month_greater_than_tenure_is_rejected(user_client, fully_configured):
    response = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, loss_month=37))
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    # Run 2 fix batch 3: the same sentence as month 0, with the real tenure in it.
    assert response.data["loss_month"] == ["Choose a month from 1 to 36."]


@pytest.mark.parametrize("loss_month, tenure", [(0, 36), (37, 36), (13, 12), (-1, 48), (109, 108)])
def test_a_month_outside_the_term_gets_one_sentence_with_the_tenure(user_client, fully_configured, loss_month, tenure):
    response = user_client.get(
        SANDBOX_URL, sandbox_params(fully_configured, loss_month=loss_month, tenure_months=tenure)
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["loss_month"] == [f"Choose a month from 1 to {tenure}."]


def test_loss_month_equal_to_tenure_is_accepted(user_client, fully_configured):
    # "During the active contract" is inclusive of the final month.
    response = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, loss_month=36))
    assert response.status_code == status.HTTP_200_OK
    assert Decimal(response.data["hire_purchase"]["outstanding_balance"]) == Decimal("0.00")


def test_downpayment_must_be_less_than_price(user_client, fully_configured):
    response = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, downpayment="100000.00"))
    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- C6: 10% minimum downpayment -------------------------------------------


def test_downpayment_below_10_percent_is_rejected(user_client, fully_configured):
    response = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, downpayment="9999.99"))
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Minimum downpayment is 10%" in str(response.data["downpayment"])


# --- Missing F011 config -> that pathway only, never a blanket failure -----


def test_missing_interest_rate_only_disables_hp_and_gfv(user_client, vehicle, residual_ratio_36):
    response = user_client.get(SANDBOX_URL, sandbox_params(vehicle))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["hire_purchase"] is None
    assert response.data["gfv_leasing"] is None
    assert response.data["subscription"] is not None
    assert "financing rate hasn't been set up" in response.data["unavailable"]["hire_purchase"]


def test_a_tenure_with_no_baseline_only_disables_gfv(user_client, vehicle, interest_rate):
    """The raw admin-facing error text must never reach an ordinary user
    here either - same plain-wording fix as F005's own comparison endpoint
    (apps.comparisons.services.gfv_residual_ratio_user_message), not just
    the "don't hide HP/Subscription" part. 40 months is not a 12-month
    step, so it has neither a baseline nor an override."""
    response = user_client.get(SANDBOX_URL, sandbox_params(vehicle, tenure_months=40))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["gfv_leasing"] is None
    assert response.data["hire_purchase"] is not None
    assert response.data["subscription"] is not None
    assert response.data["unavailable"]["gfv_leasing"] == (
        "GFV leasing isn't offered for 40 months - it is offered for 12 to 60 months in 12-month steps."
    )


def test_no_residual_override_still_prices_gfv_from_the_estimate(user_client, vehicle, interest_rate):
    # Audit batch 4: nothing keyed for this brand, yet GFV is priced - from
    # the 36-month / standard baseline (0.5179 since Run 3 fix batch 6; was 0.50),
    # balloon 100000 x 0.5179 = 51,790.00.
    response = user_client.get(SANDBOX_URL, sandbox_params(vehicle))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["gfv_leasing"] is not None
    assert "gfv_leasing" not in response.data["unavailable"]
    expected_gfv_balance = formulas.gfv_outstanding_balance(
        price=Decimal("100000.00"), downpayment=Decimal("10000.00"), tenure_months=36, month=18,
        gfv_balloon=Decimal("51790.00"), annual_rate=Decimal("0.03"),
    )
    # reducing balance at 3% flat's effective rate, re-derived independently (was 70,569.89 on 50,000.00)
    assert expected_gfv_balance == Decimal("71432.96")
    assert Decimal(response.data["gfv_leasing"]["outstanding_balance"]) == expected_gfv_balance


# --- Degraded ML forecast still returns a complete, usable result ----------


def test_completes_with_degraded_flag_and_full_pathway_data_when_no_model_is_deployed(
    user_client, fully_configured
):
    response = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, loss_month=18))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["model_degraded"] is True
    assert response.data["degraded_reason"] == DEGRADED_MESSAGE
    # QA audit L8: Subscription's own insurance_payout is null - no
    # ownership stake means no insurance claim that's theirs to receive.
    for pathway in ("hire_purchase", "gfv_leasing"):
        assert response.data[pathway]["insurance_payout"] is not None
    assert response.data["subscription"]["insurance_payout"] is None


# --- L8: Subscription has no ownership stake, so no insurance claim --------


def test_subscription_insurance_payout_is_null_not_the_same_payout_hp_and_gfv_get(
    user_client, fully_configured
):
    response = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, loss_month=18))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["subscription"]["insurance_payout"] is None
    # HP/GFV still get the real, computed payout - this isn't a blanket
    # "subscription pathway is unavailable" change.
    assert Decimal(response.data["hire_purchase"]["insurance_payout"]) == Decimal("70070.00")
    assert Decimal(response.data["gfv_leasing"]["insurance_payout"]) == Decimal("70070.00")


# --- L8: resale_value_is_plateaued flags reuse of month-60's value ---------


def test_resale_value_is_plateaued_false_within_the_60_month_forecast_horizon(user_client, fully_configured):
    response = user_client.get(SANDBOX_URL, sandbox_params(fully_configured, loss_month=18))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["resale_value_is_plateaued"] is False


def test_resale_value_is_plateaued_true_past_the_60_month_forecast_horizon(user_client, brand, interest_rate):
    """tenure=108 allows a loss_month up to 108, well past
    predict_resale_curve's own 60-month horizon - the resale value used
    for a loss past month 60 is reused from month 60 itself (see
    build_total_loss_sandbox's own docstring), which this flag makes
    explicit rather than silent.
    """
    vehicle = VehicleModel.objects.create(
        brand=brand, name="LongTenure", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00",
    )

    response = user_client.get(
        SANDBOX_URL, sandbox_params(vehicle, tenure_months=108, downpayment="10000.00", loss_month=75)
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["resale_value_is_plateaued"] is True
    # The plateaued value is exactly month 60's fallback figure (100000 *
    # 0.3679, the standard-band 60-month residual; 0.35 before Run 3 fix batch 6)
    # - not a fabricated extrapolation past it.
    assert Decimal(response.data["hire_purchase"]["insurance_payout"]) == Decimal("36790.00")


def test_resale_value_is_plateaued_false_exactly_at_the_60_month_boundary(user_client, brand, interest_rate):
    vehicle = VehicleModel.objects.create(
        brand=brand, name="ExactlySixty", trim="X", body_segment=BodySegment.SEDAN,
        msrp="100000.00", engine_capacity_kw="90.00",
    )

    response = user_client.get(
        SANDBOX_URL, sandbox_params(vehicle, tenure_months=108, downpayment="10000.00", loss_month=60)
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["resale_value_is_plateaued"] is False
