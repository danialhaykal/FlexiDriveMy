"""Run 3 fix batch 6: the recalibrated mileage bands.

  low        up to 10,000 km a year
  standard   10,001 to 15,000
  high       15,001 to 25,000
  very_high  above 25,000 (modelled and sold up to 35,000)

Keys unchanged; ONE definition (apps.policy.mileage, reading the subscription
policy's four limits); the residual grid re-derived by policy migration 0028 (a
straight line through the old grid, read at the new representative km); the
resale model capped at the mileage its training data has seen. Every value here
is a planning assumption, editable in Django admin.
"""

import importlib
import math
from decimal import Decimal

import joblib
import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.comparisons.services import build_comparison
from apps.depreciation import inference
from apps.ml.features import capped_mileage
from apps.ml.models import MLTrainingRun, ModelType, PredictionTarget, ProductionModel, TrainingRunStatus
from apps.policy import mileage
from apps.policy.admin_forms import PlainConstraintMessagesForm
from apps.policy.models import (
    BAND_KM_ASCENDING_MESSAGE,
    InterestRate,
    MileageBand,
    ResidualBaseline,
    SubscriptionPolicy,
)
from apps.policy.residuals import resolve_residual_ratio
from apps.scenarios.models import SavedScenario
from apps.vehicles.models import Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal
BANDS = list(MileageBand.values)
TENURES = [12, 24, 36, 48, 60]
migration_0028 = importlib.import_module("apps.policy.migrations.0028_recalibrate_mileage_bands")

OLD_GRID = {
    12: ["0.80", "0.77", "0.74", "0.70"], 24: ["0.64", "0.61", "0.57", "0.52"], 36: ["0.55", "0.50", "0.45", "0.40"],
    48: ["0.47", "0.42", "0.38", "0.33"], 60: ["0.40", "0.35", "0.31", "0.27"],
}
NEW_GRID = {
    12: ["0.8000", "0.7807", "0.7550", "0.7200"], 24: ["0.6400", "0.6207", "0.5900", "0.5450"],
    36: ["0.5500", "0.5179", "0.4750", "0.4250"], 48: ["0.4700", "0.4379", "0.4000", "0.3550"],
    60: ["0.4000", "0.3679", "0.3300", "0.2900"],
}


def grid():
    return {
        t: [str(ResidualBaseline.objects.get(tenure_months=t, mileage_band=b, is_active=True).ratio) for b in BANDS]
        for t in TENURES
    }


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


# --- the one definition --------------------------------------------------------------------------------------------


def test_the_definition_has_the_new_ranges_and_the_unchanged_keys():
    bands = mileage.band_definitions()

    assert [b.key for b in bands] == ["low", "standard", "high", "very_high"]
    assert [(b.lower_km, b.upper_km) for b in bands] == [(0, 10000), (10000, 15000), (15000, 25000), (25000, 35000)]
    assert [b.included_km for b in bands] == [10000, 15000, 25000, 35000]
    assert [b.representative_km for b in bands] == [D("8000"), D("12500"), D("20000"), D("30000")]


@pytest.mark.parametrize("km, band", [
    (0, "low"), (10000, "low"), (10001, "standard"), (15000, "standard"), (15001, "high"),
    (25000, "high"), (25001, "very_high"), (35000, "very_high"), (60000, "very_high"),
])
def test_each_limit_is_up_to_and_including(km, band):
    assert mileage.band_for_km(km) == band
    assert inference.mileage_band_for_km(D(km)) == band  # the TCO's declared-mileage path uses the same rule


def test_each_representative_km_lies_inside_its_own_band():
    for b in mileage.band_definitions():
        assert b.lower_km < b.representative_km <= b.upper_km
        assert mileage.band_for_km(b.representative_km) == b.key


def test_editing_the_policy_moves_every_band_with_no_deploy():
    SubscriptionPolicy.objects.update(low_km_cap=12000, standard_km_cap=18000, high_km_cap=28000, very_high_km_cap=40000)

    assert mileage.band_for_km(12000) == "low" and mileage.band_for_km(12001) == "standard"
    assert [b.representative_km for b in mileage.band_definitions()] == [D("9600"), D("15000"), D("23000"), D("34000")]
    assert mileage.mileage_band_label("high") == "High — 18,001 to 28,000 km/year"


# --- (b) a car added later gets the new bands --------------------------------------------------------------------------


def test_a_car_added_later_gets_the_new_bands_with_nothing_keyed(admin_user):
    admin = APIClient()
    admin.force_authenticate(user=admin_user)
    brand = Brand.objects.create(name="LaterBrand", tier_code="3")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000", is_active=True)
    created = admin.post("/api/vehicles/models/", {
        "brand": brand.pk, "name": "Later", "trim": "One", "body_segment": "sedan", "msrp": "200000.00",
        "engine_capacity_kw": "120.00", "powertrain": "petrol", "engine_capacity_cc": 1798,
    }, format="json")
    assert created.status_code == 201, created.data
    vehicle = VehicleModel.objects.get(pk=created.data["id"])

    for band, expected_ratio, km in zip(BANDS, NEW_GRID[36], [10000, 15000, 25000, 35000]):
        comparison = build_comparison(vehicle=vehicle, tenure_months=36, mileage_band=band, downpayment=D("20000.00"))
        assert comparison["gfv_leasing"]["residual_value_ratio"] == D(expected_ratio)
        assert comparison["subscription"]["included_km_per_year"] == km == mileage.included_km(band)


# --- (c) the residual falls band by band at every tenure ---------------------------------------------------------------


def test_the_seeded_grid_is_the_documented_new_grid():
    assert grid() == NEW_GRID
    assert {t: [str(v) for v in row] for t, row in migration_0028.new_grid().items()} == NEW_GRID


@pytest.mark.parametrize("tenure", TENURES)
def test_the_residual_strictly_falls_from_low_to_very_high(tenure):
    row = [D(v) for v in grid()[tenure]]

    assert row == sorted(row, reverse=True) and len(set(row)) == 4


@pytest.mark.parametrize("brand_name, powertrain", [("BMW", "petrol"), ("Toyota", "hybrid"), ("Volvo", "phev")])
def test_a_cars_resolved_residual_falls_band_by_band_at_every_tenure(brand_name, powertrain):
    seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")
    brand = Brand.objects.create(name=brand_name, tier_code="2")
    seed.seed_brand_adjustments(django_apps)
    car = VehicleModel.objects.create(
        brand=brand, name="M", trim="X", body_segment="sedan", msrp="300000.00", engine_capacity_kw="150.00",
        powertrain=powertrain, engine_capacity_cc=1998,
    )

    for tenure in TENURES:
        ratios = [resolve_residual_ratio(car, tenure, band).ratio for band in BANDS]
        assert ratios == sorted(ratios, reverse=True) and len(set(ratios)) == 4, (tenure, ratios)


def test_the_method_invents_no_slope_low_is_unchanged_and_every_value_lies_between_two_old_ones():
    for tenure in TENURES:
        old, new = [D(v) for v in OLD_GRID[tenure]], [D(v) for v in NEW_GRID[tenure]]
        assert new[0] == old[0]  # low keeps its representative km (8,000)
        # standard 12,500 lies between low 8,000 and old standard 15,000; high 20,000 between old
        # standard 15,000 and old high 25,000; very high 30,000 between old high 25,000 and old very high 35,000
        assert old[1] <= new[1] <= old[0]
        assert old[2] <= new[2] <= old[1]
        assert old[3] <= new[3] <= old[2]


# --- the data migration is reversible and never overwrites an admin edit -----------------------------------------------


def test_migration_0028_is_reversible():
    assert grid() == NEW_GRID
    assert SubscriptionPolicy.objects.get(is_active=True).very_high_km_cap == 35000

    migration_0028.backwards(django_apps, None)
    assert grid() == {t: [str(D(v).quantize(D("0.0001"))) for v in row] for t, row in OLD_GRID.items()}
    assert SubscriptionPolicy.objects.get(is_active=True).very_high_km_cap == 40000

    migration_0028.forwards(django_apps, None)
    assert grid() == NEW_GRID
    assert SubscriptionPolicy.objects.get(is_active=True).very_high_km_cap == 35000

    migration_0028.forwards(django_apps, None)  # idempotent
    assert grid() == NEW_GRID


def test_migration_0028_leaves_an_admin_edited_row_and_policy_alone_both_ways():
    ResidualBaseline.objects.filter(tenure_months=48, mileage_band="high").update(ratio=D("0.3999"))
    SubscriptionPolicy.objects.update(very_high_km_cap=38000)

    migration_0028.backwards(django_apps, None)
    migration_0028.forwards(django_apps, None)

    assert ResidualBaseline.objects.get(tenure_months=48, mileage_band="high").ratio == D("0.3999")
    assert SubscriptionPolicy.objects.get(is_active=True).very_high_km_cap == 38000


# --- (d) the subscription fee never falls with more km -----------------------------------------------------------------


@pytest.mark.parametrize("tenure", [12, 24, 36])
def test_the_fee_rises_from_low_to_very_high(tenure):
    from apps.policy.subscription_pricing import resolve_subscription_fee

    brand = Brand.objects.create(name="FeeBrand", tier_code="2")
    car = VehicleModel.objects.create(
        brand=brand, name="F", trim="X", body_segment="suv", msrp="250000.00", engine_capacity_kw="130.00",
        powertrain="petrol", engine_capacity_cc=1998,
    )
    car.refresh_from_db()  # as every real caller gets it (msrp as Decimal)

    fees = [resolve_subscription_fee(car, tenure, band).fee_monthly for band in BANDS]

    assert fees == sorted(fees) and len(set(fees)) == 4


# --- the limits must rise band by band ---------------------------------------------------------------------------------


def test_a_policy_whose_limits_do_not_rise_is_refused_plainly_and_by_the_database():
    policy = SubscriptionPolicy.objects.get(is_active=True)
    policy.standard_km_cap = policy.low_km_cap

    with pytest.raises(ValidationError) as excinfo:
        policy.full_clean()
    assert BAND_KM_ASCENDING_MESSAGE in str(excinfo.value)
    assert BAND_KM_ASCENDING_MESSAGE == "Each mileage band's km a year must be higher than the band below it."

    with pytest.raises(IntegrityError), transaction.atomic():
        SubscriptionPolicy.objects.filter(pk=policy.pk).update(high_km_cap=14000)


# --- admin help text is generated from the definition -------------------------------------------------------------------


def test_admin_help_text_comes_from_the_definition_and_follows_an_edit():
    class BaselineForm(PlainConstraintMessagesForm):
        class Meta:
            model = ResidualBaseline
            fields = ["tenure_months", "mileage_band", "ratio"]

    class PolicyForm(PlainConstraintMessagesForm):
        class Meta:
            model = SubscriptionPolicy
            fields = ["low_km_cap", "standard_km_cap", "high_km_cap", "very_high_km_cap"]

    help_text = BaselineForm().fields["mileage_band"].help_text
    assert help_text == (
        "Bands: Low — up to 10,000 km/year; Standard — 10,001 to 15,000 km/year; "
        "High — 15,001 to 25,000 km/year; Very high — above 25,000 km/year."
    )
    assert "Today: Standard — 10,001 to 15,000 km/year." in PolicyForm().fields["standard_km_cap"].help_text

    SubscriptionPolicy.objects.update(standard_km_cap=16000)
    assert "Standard — 10,001 to 16,000 km/year" in BaselineForm().fields["mileage_band"].help_text


# --- the resale model is never read beyond the mileage it has seen ------------------------------------------------------


class StubLogCurve:
    """Log price falls 12% of the new price a year; reads only age (module-level for joblib)."""

    def predict(self, rows):
        return [math.log(max(1.0 - 0.12 * age, 1e-9)) for age in rows["vehicle_age"]]


# The real training data's highest mileage per age (apps/ml/data/real_historical_pricing.csv).
TRAINED_MAX = {0: 62500, 1: 92500, 2: 107500, 3: 117500, 4: 147500, 5: 147500}


def deploy_with_training_data(tmp_path, rows=None):
    dataset = tmp_path / "training.csv"
    rows = rows if rows is not None else [(age, km) for age, km in TRAINED_MAX.items()] + [(5, 40000), (2, 9000)]
    dataset.write_text("vehicle_age,mileage,resale_price\n" + "".join(f"{a},{k},50000\n" for a, k in rows))
    model_path = tmp_path / "stub.joblib"
    joblib.dump(StubLogCurve(), model_path)
    run = MLTrainingRun.objects.create(status=TrainingRunStatus.SUCCEEDED, dataset_path=str(dataset))
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.LOG_LINEAR
    production.model_file_path = str(model_path)
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.training_run = run
    production.save()


def test_capped_mileage_caps_each_year_at_the_trained_maximum():
    assert capped_mileage(30000, 5, TRAINED_MAX) == 147500.0  # 150,000 is beyond what the data has seen
    assert capped_mileage(30000, 4, TRAINED_MAX) == 120000.0  # inside the data: unchanged
    assert capped_mileage(12500, 5, TRAINED_MAX) == 62500.0
    assert capped_mileage(30000, 5) == 150000.0  # no caps known: nothing capped


def test_the_caps_are_read_from_the_deployed_runs_training_data(tmp_path):
    deploy_with_training_data(tmp_path)

    assert inference.trained_mileage_caps() == {age: float(km) for age, km in TRAINED_MAX.items()}


def test_an_age_missing_from_the_data_takes_the_cap_of_the_nearest_younger_age(tmp_path):
    deploy_with_training_data(tmp_path, rows=[(0, 50000), (1, 90000), (3, 120000)])

    assert inference.trained_mileage_caps() == {0: 50000.0, 1: 90000.0, 2: 90000.0, 3: 120000.0, 4: 120000.0, 5: 120000.0}


def test_no_caps_without_a_recorded_dataset_so_nothing_is_capped():
    ProductionModel.objects.filter(pk=1).update(training_run=None)

    assert inference.trained_mileage_caps() is None
    assert inference.mileage_cap_applies(D("30000")) is False


def test_the_real_training_data_caps_only_the_very_high_band_at_year_five():
    from pathlib import Path

    import pandas as pd

    data = Path(__file__).resolve().parents[2] / "ml" / "data" / "real_historical_pricing.csv"
    by_age = pd.read_csv(data, usecols=["vehicle_age", "mileage"]).groupby("vehicle_age")["mileage"].max()
    assert {age: int(by_age[age]) for age in range(6)} == TRAINED_MAX

    over = {b.key: [y for y in range(6) if float(b.representative_km) * y > TRAINED_MAX[y]]
            for b in mileage.band_definitions()}
    assert over == {"low": [], "standard": [], "high": [], "very_high": [5]}


def tco(client, vehicle, band):
    response = client.get("/api/depreciation/tco/", {
        "vehicle": vehicle.pk, "tenure_months": 60, "mileage_band": band, "downpayment": "30000.00",
    })
    assert response.status_code == 200, response.data
    return response.data


@pytest.fixture
def petrol_car():
    brand = Brand.objects.create(name="CapBrand", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000", is_active=True)
    return VehicleModel.objects.create(
        brand=brand, name="C", trim="X", body_segment="sedan", msrp="300000.00", engine_capacity_kw="150.00",
        powertrain="petrol", engine_capacity_cc=1998,
    )


def test_the_cap_note_shows_only_when_a_cap_applied(client, petrol_car, tmp_path):
    deploy_with_training_data(tmp_path)

    notes = {band: tco(client, petrol_car, band)["forecast_cap_note"] for band in BANDS}

    assert notes == {"low": None, "standard": None, "high": None,
                     "very_high": "The forecast is capped at the mileage the model has seen."}


def test_no_cap_note_on_the_estimated_curve(client, petrol_car):
    data = tco(client, petrol_car, "very_high")  # no model deployed

    assert data["model_degraded"] is True
    assert data["forecast_cap_note"] is None


# --- (e) an old snapshot still opens -----------------------------------------------------------------------------------


def test_a_snapshot_saved_before_the_recalibration_opens_exactly_as_saved(client, regular_user, petrol_car):
    old = {
        "tenureMonths": 36, "mileageBand": "standard", "downpayment": "30000.00", "snapshotVersion": 2,
        "builtBy": "server",
        "inputs": {"tenure_months": 36, "mileage_band": "standard", "downpayment": "30000.00", "include_tco": True,
                   "ncd_percent": "0.00", "scoring": None},
        "comparison": {"subscription": {
            "included_km_per_year": 20000,
            "mileage_note": "Includes up to 20,000 km a year. Kilometres above that are billed per km "
                            "(RM 0.50/km under the default contract rule).",
        }, "gfv_leasing": {"residual_value_ratio": "0.5000", "balloon_payment": "150000.00"}},
        "tco": {"tco_net": "1.00", "mileage_band": "standard", "monthly_forecast": []},  # no forecast_cap_note key
        "scoring": None,
    }
    scenario = SavedScenario.objects.create(user=regular_user, title="Before batch 6", vehicle=petrol_car, payload=old)

    response = client.get(f"/api/scenarios/{scenario.pk}/")

    assert response.status_code == 200
    assert response.data["payload"] == old  # the old band figures are shown as saved, never recomputed
    assert "forecast_cap_note" not in response.data["payload"]["tco"]
