"""Run 3 fix batch 4 (F-10): a GFV residual override above 60 months (an admin may
key one for any tenure 12-108) made the TCO tab, the PDF export and the Arena fail
with HTTP 500 - the GFV pathway TCO read the resale curve at month t, and the curve
covers 61 points (months 0-60). Now those two entries are unavailable with a plain
reason, and the rest of the report is what it was.

The horizon is NOT extended: the forecast still stops at month 60.
"""

import importlib
import io
import math
from decimal import Decimal

import joblib
import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient

from apps.depreciation.services import GFV_TCO_BEYOND_FORECAST_MESSAGE, build_tco_report
from apps.ml.models import ModelType, PredictionTarget, ProductionModel
from apps.policy.models import InterestRate, MileageBand, ResidualValueMatrix
from apps.policy.residuals import unavailable_message
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")

DOWNPAYMENT = "40000.00"
GFV_KEYS = ("gfv_retain", "gfv_return")


class StubLogCurve:
    """A fitted-model stand-in on the LOG price scale (module-level so joblib can load it)."""

    def predict(self, rows):
        return [math.log(max(1.0 - 0.12 * age, 1e-9)) for age in rows["vehicle_age"]]


@pytest.fixture
def deployed(tmp_path):
    path = tmp_path / "stub.joblib"
    joblib.dump(StubLogCurve(), path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.LOG_LINEAR
    production.model_file_path = str(path)
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.r2_score = 0.9124
    production.mae = 0.1473
    production.save()


@pytest.fixture
def brand():
    brand = Brand.objects.create(name="Horizon Motors", tier_code="3")
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=brand, rate_percent="3.0000", is_active=True)
    return brand


@pytest.fixture
def car(brand):
    vehicle = VehicleModel.objects.create(
        brand=brand, name="Saloon", trim="2.0", body_segment=BodySegment.SEDAN, msrp="400000.00",
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    vehicle.refresh_from_db()
    return vehicle


@pytest.fixture
def other_car():
    other = Brand.objects.create(name="Other Motors", tier_code="2")
    InterestRate.objects.create(brand=other, rate_percent="2.8000", is_active=True)
    vehicle = VehicleModel.objects.create(
        brand=other, name="Sedan", trim="1.5", body_segment=BodySegment.SEDAN, msrp="250000.00",
        engine_capacity_kw="120.00", powertrain="petrol", engine_capacity_cc=1498,
    )
    vehicle.refresh_from_db()
    return vehicle


@pytest.fixture
def overrides(brand):
    return {
        tenure: ResidualValueMatrix.objects.create(
            brand=brand, tenure_months=tenure, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.3000",
        )
        for tenure in (72, 108)
    }


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


def get_tco(client, vehicle, tenure):
    response = client.get("/api/depreciation/tco/", {
        "vehicle": vehicle.pk, "tenure_months": tenure, "mileage_band": "standard", "downpayment": DOWNPAYMENT,
    })
    assert response.status_code == 200, getattr(response, "data", response.content[:300])
    return response.data


def report(vehicle, tenure):
    return build_tco_report(vehicle=vehicle, tenure_months=tenure, mileage_band="standard",
                            downpayment=Decimal(DOWNPAYMENT))


# --- TCO ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("with_model", [False, True], ids=["estimated-curve", "ml-model"])
@pytest.mark.parametrize("tenure", [72, 108])
def test_tco_with_an_override_above_60_months_answers_with_gfv_unavailable(
    client, car, overrides, tenure, with_model, request
):
    if with_model:
        request.getfixturevalue("deployed")

    data = get_tco(client, car, tenure)

    for key in GFV_KEYS:
        entry = data["pathway_tco"][key]
        assert entry["available"] is False
        assert entry["unavailable_reason"] == GFV_TCO_BEYOND_FORECAST_MESSAGE
        assert entry["gross"] is None and entry["net"] is None
    hire_purchase = data["pathway_tco"]["hire_purchase"]
    assert hire_purchase["available"] is True
    assert (hire_purchase["gross"], hire_purchase["net"]) == (data["tco_gross"], data["tco_net"])
    assert len(data["monthly_forecast"]) == 61  # the horizon is not extended


def test_the_message_is_the_one_asked_for():
    assert GFV_TCO_BEYOND_FORECAST_MESSAGE == (
        "The resale forecast covers 60 months, so the total cost of this pathway cannot be worked out for a longer "
        "term."
    )


def test_the_comparison_still_offers_gfv_at_72_months(client, car, overrides):
    response = client.get("/api/comparisons/", {
        "vehicle": car.pk, "tenure_months": 72, "mileage_band": "standard", "downpayment": DOWNPAYMENT,
    })

    assert response.status_code == 200
    assert response.data["gfv_leasing"]["balloon_payment"] == "120000.00"  # 30% of RM 400,000, unchanged


# --- the PDF --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tenure", [72, 108])
def test_the_pdf_exports_with_an_override_above_60_months(client, car, overrides, tenure):
    try:
        import weasyprint  # noqa: F401
    except Exception as exc:  # native libraries missing (OSError, not ImportError)
        pytest.skip(f"weasyprint is not usable in this environment: {exc}")

    response = client.post("/api/exports/pdf/", {
        "vehicle": car.pk, "tenure_months": tenure, "mileage_band": "standard", "downpayment": DOWNPAYMENT,
        "chart_svg": "",
    }, format="json")

    assert response.status_code == 200, getattr(response, "data", response.content[:300])
    assert response.content.startswith(b"%PDF-")
    pypdf = pytest.importorskip("pypdf")
    text = " ".join(" ".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(response.content)).pages)
                    .split())
    assert GFV_TCO_BEYOND_FORECAST_MESSAGE in text


# --- the Arena ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tenure", [72, 108])
def test_the_arena_answers_with_an_override_above_60_months(client, car, other_car, overrides, tenure):
    response = client.get("/api/comparisons/arena/", {
        "vehicles": [car.pk, other_car.pk], "tenure_months": tenure, "mileage_band": "standard",
        "downpayment": DOWNPAYMENT,
    })

    assert response.status_code == 200, response.data
    entry = next(e for e in response.data["results"] if e["vehicle_id"] == car.pk)
    assert entry["ok"] is True and entry["tco_unavailable_reason"] is None
    assert Decimal(entry["tco_net"]) == report(car, tenure)["tco_net"]
    assert entry["comparison"]["gfv_leasing"] is not None  # GFV itself is still offered


# --- archiving the override -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("tenure", [72, 108])
def test_archiving_the_override_changes_nothing_else(car, overrides, tenure):
    with_override = report(car, tenure)
    ResidualValueMatrix.objects.filter(pk=overrides[tenure].pk).update(is_active=False)
    archived = report(car, tenure)

    # GFV is no longer offered at all: the comparison's own reason, as for any tenure without one
    reason = unavailable_message(tenure, car.brand, "standard")
    for key in GFV_KEYS:
        assert archived["pathway_tco"][key]["available"] is False
        assert archived["pathway_tco"][key]["unavailable_reason"] == reason
    # everything that does not depend on GFV being offered is identical
    gfv_dependent = {"pathway_tco", "risk_radar", "radar_unavailable"}
    assert {k: v for k, v in with_override.items() if k not in gfv_dependent} == {
        k: v for k, v in archived.items() if k not in gfv_dependent}
    for key in ("hire_purchase", "subscription"):
        assert with_override["pathway_tco"][key] == archived["pathway_tco"][key]


def test_84_months_without_an_override_is_unchanged(car):
    """No override: GFV is not offered above 60 months, so its TCO entries carry the
    comparison's own reason - the path this fix does not touch."""
    data = report(car, 84)

    reason = unavailable_message(84, car.brand, "standard")
    for key in GFV_KEYS:
        assert data["pathway_tco"][key]["unavailable_reason"] == reason
    assert data["pathway_tco"]["hire_purchase"]["available"] is True
