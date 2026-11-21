import math
import time
from decimal import Decimal

import joblib
import pytest

from apps.depreciation import formulas, inference
from apps.ml.features import FEATURE_COLUMNS
from apps.ml.models import ModelType, PredictionTarget, ProductionModel
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db

LOG = PredictionTarget.LOG_RESALE_PRICE


class WorkingEstimator:
    """A fake 'model' with a predictable output on the LOG price scale (ML
    batch 1): log price falls by 0.2 a year of age, so the curve is
    msrp x exp(-0.2 x m / 12) - easy to tell apart from the fallback."""

    def predict(self, feature_rows):
        return [math.log(80000) - 0.2 * age for age in feature_rows["vehicle_age"]]


def make_car(brand, **fields):
    defaults = dict(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN, msrp="100000.00",
        engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    defaults.update(fields)
    vehicle = VehicleModel.objects.create(**defaults)
    # Real callers always get `vehicle` via a fresh DB fetch, which
    # normalizes msrp to Decimal.
    vehicle.refresh_from_db()
    return vehicle


@pytest.fixture
def vehicle():
    # tier_code must be a real, parseable value - inference degrades for a
    # blank/unparseable one (tested below).
    return make_car(Brand.objects.create(name="InferenceBrand", tier_code="3"))


def deploy(tmp_path, estimator=None, target=LOG):
    model_path = tmp_path / "model.joblib"
    joblib.dump(estimator if estimator is not None else WorkingEstimator(), model_path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = str(model_path)
    production.prediction_target = target
    production.save()


# Audit batch 4: the fallback is anchored to the same residuals GFV uses. These
# vehicles have no residual override, no brand adjustment and a petrol
# powertrain (0 points), and a 15,000 km/year mileage (standard band - up to and
# including its limit), so their anchors are the plain standard-band baseline:
# month 0 = 100%, then 78.07 / 62.07 / 51.79 / 43.79 / 36.79% at months 12 / 24 / 36 /
# 48 / 60 (Run 3 fix batch 6; were 77 / 61 / 50 / 42 / 35%), straight-line between.
BASELINE_STANDARD_ANCHORS = [
    (0, "1.00"), (12, "0.7807"), (24, "0.6207"), (36, "0.5179"), (48, "0.4379"), (60, "0.3679"),
]


def expected_fallback_curve(msrp):
    anchors = [(month, Decimal(ratio)) for month, ratio in BASELINE_STANDARD_ANCHORS]
    curve = []
    for month in range(formulas.HORIZON_MONTHS + 1):
        (m0, r0), (m1, r1) = next((a, b) for a, b in zip(anchors, anchors[1:]) if month <= b[0])
        ratio = r0 + (r1 - r0) * (month - m0) / (m1 - m0)
        curve.append((msrp * ratio).quantize(Decimal("0.01")))
    return curve


def test_the_fallback_is_anchored_to_the_gfv_baseline_not_a_flat_straight_line(vehicle):
    values, degraded, _ = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert values[0] == Decimal("100000.00")
    assert values[6] == Decimal("89035.00")   # 1.00 + (0.7807 - 1.00) x 6/12 = 0.89035 (was 88,500.00)
    assert values[12] == Decimal("78070.00")  # was 77,000.00
    assert values[30] == Decimal("56930.00")  # 0.6207 + (0.5179 - 0.6207) x 6/12 = 0.5693 (was 55,500.00)
    assert values[36] == Decimal("51790.00")  # was 50,000.00
    assert values[60] == Decimal("36790.00")  # was 35,000.00


# --- Falls back when there is nothing to call -------------------------------


def test_no_production_model_deployed_falls_back(vehicle):
    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert reason == inference.DEGRADED_MESSAGE
    assert values == expected_fallback_curve(vehicle.msrp)


def test_model_file_missing_on_disk_falls_back(vehicle):
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = "/this/path/does/not/exist.joblib"
    # A compatible model on paper, so this exercises "the file fails to load",
    # not the prediction_target gate.
    production.prediction_target = LOG
    production.save()

    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert reason == inference.MODEL_FAILED_MESSAGE
    assert values == expected_fallback_curve(vehicle.msrp)


# --- Only the log resale-price target is compatible ----------------------------


@pytest.mark.parametrize(
    "target", ["", PredictionTarget.RAW_RESALE_PRICE, PredictionTarget.VALUE_RETENTION_RATIO]
)
def test_any_other_prediction_target_degrades_even_though_the_file_loads_fine(vehicle, tmp_path, target):
    """A blank target (unknown), the legacy raw price and the old
    value-retention ratio are all refused - WorkingEstimator loads and
    predicts fine, so this degrades because of the target check alone."""
    deploy(tmp_path, target=target)

    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert reason == inference.DEGRADED_MESSAGE
    assert values == expected_fallback_curve(vehicle.msrp)
    assert inference.forecast_is_switched_off() is True


# --- Falls back on prediction failure / timeout (UC006 exception flow) ----


def test_prediction_exception_falls_back(vehicle, tmp_path, monkeypatch):
    deploy(tmp_path)

    def _raise(model, feature_rows):
        raise RuntimeError("could not parse feature inputs")

    monkeypatch.setattr(inference, "_run_model_prediction", _raise)

    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert reason == inference.MODEL_FAILED_MESSAGE
    assert values == expected_fallback_curve(vehicle.msrp)


def test_a_non_finite_prediction_falls_back(vehicle, tmp_path, monkeypatch):
    deploy(tmp_path)
    monkeypatch.setattr(inference, "_run_model_prediction", lambda model, rows: [float("nan")] * len(rows))

    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert reason == inference.MODEL_FAILED_MESSAGE
    assert values == expected_fallback_curve(vehicle.msrp)


def test_prediction_timeout_falls_back_without_waiting_for_the_full_hang(vehicle, tmp_path, monkeypatch, settings):
    deploy(tmp_path)
    settings.ML_INFERENCE_TIMEOUT_SECONDS = 0.05

    def _hang(model, feature_rows):
        time.sleep(2)
        return [1.0 for _ in range(len(feature_rows))]

    monkeypatch.setattr(inference, "_run_model_prediction", _hang)

    started = time.monotonic()
    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))
    elapsed = time.monotonic() - started

    assert degraded is True
    assert reason == inference.MODEL_FAILED_MESSAGE
    assert values == expected_fallback_curve(vehicle.msrp)
    assert elapsed < 1.0


# --- Uses the real model when it works ------------------------------------


def test_working_model_is_used_month_0_is_msrp_and_the_curve_follows_exp_of_the_change(vehicle, tmp_path):
    deploy(tmp_path)

    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is False
    assert reason is None
    assert len(values) == formulas.HORIZON_MONTHS + 1
    # value_m = msrp x exp(f_m - f_0); the model's own level (log 80,000) cancels.
    assert values[0] == Decimal("100000.00")
    assert values[12] == Decimal("81873.08")  # 100,000 x e^-0.2 = 81,873.0753
    assert values[60] == Decimal("36787.94")  # 100,000 x e^-1.0 = 36,787.9441
    assert all(values[m] >= values[m + 1] for m in range(len(values) - 1))


def test_the_feature_rows_follow_the_shared_columns_and_the_cars_own_specs(tmp_path, monkeypatch):
    # brand_code comes from tier_code, never the Django primary key.
    low_tier_brand = Brand.objects.create(name="LowTierBrand", tier_code="5")
    assert low_tier_brand.id != 5
    vehicle = make_car(low_tier_brand, msrp="55000.00", body_segment=BodySegment.CROSSOVER, engine_capacity_cc=2393)
    deploy(tmp_path)

    recorded_calls = []

    def _record(model, feature_rows):
        recorded_calls.append(feature_rows)
        return [11.0 for _ in range(len(feature_rows))]

    monkeypatch.setattr(inference, "_run_model_prediction", _record)

    inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert len(recorded_calls) == 1
    rows = recorded_calls[0]
    assert list(rows.columns) == FEATURE_COLUMNS
    # ML batch 2: read at whole years 0..5 only (the data records age in whole years).
    assert len(rows) == 6
    assert rows["vehicle_age"].tolist() == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    month_24 = rows.iloc[2].to_dict()
    assert month_24 == {
        "vehicle_age": 2.0, "mileage": 30000.0, "brand_code": 5.0, "engine_litres": 2.4, "recond": 0.0,
        "body_sedan": 0.0, "body_hatchback": 0.0, "body_suv": 1.0,  # a crossover is an SUV to the model
        "body_mpv": 0.0, "body_pickup": 0.0, "body_coupe": 0.0,
    }
    assert rows.iloc[0]["vehicle_age"] == 0.0 and rows.iloc[0]["mileage"] == 0.0


@pytest.mark.parametrize("cc, litres", [(1998, 2.0), (2393, 2.4), (2487, 2.5), (1050, 1.1), (1449, 1.4)])
def test_engine_litres_are_cc_over_1000_to_one_decimal_half_up(cc, litres):
    assert inference.engine_litres_for_cc(cc) == litres


# --- ML batch 1: cars the model does not cover always get the fallback -----------------


def test_an_electric_car_gets_the_fallback_with_its_own_message(tmp_path):
    brand = Brand.objects.create(name="EvBrand", tier_code="1")
    vehicle = make_car(brand, powertrain="bev", engine_capacity_cc=None, engine_capacity_kw="250.00")
    deploy(tmp_path)

    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert reason == (
        "Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast does "
        "not cover electric cars yet: the training data has none."
    )
    assert values[0] == vehicle.msrp and values[60] < values[0]


def test_a_car_without_an_engine_cc_gets_the_ev_message(tmp_path):
    brand = Brand.objects.create(name="NoCcBrand", tier_code="2")
    vehicle = make_car(brand)
    VehicleModel.objects.filter(pk=vehicle.pk).update(engine_capacity_cc=None)  # a pre-contract row
    vehicle.refresh_from_db()
    deploy(tmp_path)

    _values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert reason == inference.NOT_COVERED_EV_MESSAGE


def test_a_body_segment_with_no_body_type_falls_back_never_guessed(tmp_path, vehicle):
    VehicleModel.objects.filter(pk=vehicle.pk).update(body_segment="roadster")  # a segment added later
    vehicle.refresh_from_db()
    deploy(tmp_path)

    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    # ML batch 2: its own message - "just now" is only for real runtime failures.
    assert reason == (
        "Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast does "
        "not cover this body type yet."
    )
    assert values == expected_fallback_curve(vehicle.msrp)


# --- ML batch 2: whole-year anchors, months interpolated on the log scale ---------------


class SteppedEstimator:
    """Log price at whole years: a big first-year drop, then gentler steps."""

    LOGS = [12.0, 11.8, 11.7, 11.6, 11.5, 11.4]

    def predict(self, feature_rows):
        return [self.LOGS[int(age)] for age in feature_rows["vehicle_age"]]


def test_months_are_interpolated_between_whole_years_in_log_space(tmp_path, vehicle):
    deploy(tmp_path, SteppedEstimator())

    values, degraded, _ = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is False
    # month 6 is halfway between year 0 (12.0) and year 1 (11.8) on the log scale:
    # 100,000 x e^-0.1 = 90,483.74 (not the straight-line 90,936.54 of the two RM values)
    assert values[6] == Decimal("90483.74")
    assert values[12] == Decimal("81873.08")   # e^-0.2
    assert values[15] == Decimal("79851.62")   # e^-(0.2 + 0.1 x 3/12) = e^-0.225
    assert values[60] == Decimal("54881.16")   # e^-0.6, month 60 = year 5 exactly


@pytest.mark.parametrize(
    "month, expected", [(0, (0, 1, 0.0)), (6, (0, 1, 0.5)), (12, (1, 2, 0.0)), (59, (4, 5, 11 / 12)), (60, (5, 5, 0.0))]
)
def test_month_weights(month, expected):
    year, next_year, weight = inference._month_weights(month)
    assert (year, next_year) == expected[:2]
    assert weight == pytest.approx(expected[2])


def test_with_no_model_deployed_an_electric_car_reads_as_switched_off(tmp_path):
    """No compatible model at all: the switched-off wording comes first."""
    vehicle = make_car(Brand.objects.create(name="EvBrand2", tier_code="1"), powertrain="bev",
                       engine_capacity_cc=None, engine_capacity_kw="250.00")

    _values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert reason == inference.DEGRADED_MESSAGE


# --- Graceful degrade: a brand with no valid tier_code ----------------------


@pytest.mark.parametrize("tier_code", ["", "nan", "not-a-number"])
def test_an_invalid_tier_code_degrades_even_with_a_working_model_deployed(tmp_path, tier_code):
    """QA audit M15: float("nan") parses without raising - checked too."""
    vehicle = make_car(Brand.objects.create(name=f"Tier{tier_code or 'Blank'}Brand", tier_code=tier_code))
    deploy(tmp_path)

    values, degraded, reason = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is True
    assert reason == inference.MODEL_FAILED_MESSAGE
    assert values == expected_fallback_curve(vehicle.msrp)


# --- QA audit C8: inference-time sanity clamp (defense in depth) ----------


class MisbehavingLogEstimator:
    """A deliberately out-of-distribution fake 'model' on the log scale (read
    at whole years - ML batch 2): year 1 drops, year 2 rises back ABOVE year 0
    (a ratio > 1, i.e. a value above the new price), years 3+ stay low.
    _clamp_resale_curve must hold every month at or below msrp and the running
    minimum."""

    def predict(self, feature_rows):
        return [{0: 11.0, 2: 11.3}.get(int(age), 10.5) for age in feature_rows["vehicle_age"]]


def test_sanity_clamp_keeps_every_month_at_or_below_msrp_and_never_rising(tmp_path, vehicle):
    deploy(tmp_path, MisbehavingLogEstimator())

    values, degraded, _ = inference.predict_resale_curve(vehicle=vehicle, annual_mileage_km=Decimal("15000"))

    assert degraded is False
    assert values[0] == vehicle.msrp
    assert all(value <= vehicle.msrp for value in values)
    assert all(values[month] >= values[month + 1] for month in range(len(values) - 1))
    # Raw month 24 would be 100,000 x e^0.3 = 134,985.88 - clamped to month 12's value.
    assert values[24] == values[12] == Decimal("60653.07")  # 100,000 x e^-0.5
