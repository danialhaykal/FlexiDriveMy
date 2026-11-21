"""Run 3 fix batch 5 (F-03): the 'Why this predicted value?' amounts are 2-dp strings
on the wire, like every other money field (they were JSON floats). The figures and
the exact-sum rule are unchanged; the PDF block reads a number (an older saved
snapshot) and a string the same way."""

import io
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.depreciation.tests.test_explanation import _deploy, fit_log_price_estimator
from apps.exports import comparison_rows as rows
from apps.ml.log_linear import LogLinearDepreciationModel
from apps.policy.models import InterestRate
from apps.scenarios.models import SavedScenario
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

TWO_DP = Decimal("0.01")


@pytest.fixture(autouse=True)
def patient_explainer(settings):
    settings.ML_INFERENCE_TIMEOUT_SECONDS = 120


@pytest.fixture
def car():
    brand = Brand.objects.create(name="StringsBrand", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="2.8000")
    return VehicleModel.objects.create(
        brand=brand, name="Saloon", trim="X", body_segment=BodySegment.SEDAN, msrp="267800.00",
        engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998,
    )


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


def tco(client, car, tenure=36):
    response = client.get("/api/depreciation/tco/", {
        "vehicle": car.pk, "tenure_months": tenure, "mileage_band": "standard", "downpayment": "26780.00",
    })
    assert response.status_code == 200, response.data
    return response.data


@pytest.mark.parametrize("tenure", [12, 36, 60])
def test_the_amounts_are_2dp_strings_that_add_up_exactly(client, car, tmp_path, tenure):
    _deploy(tmp_path, fit_log_price_estimator(LogLinearDepreciationModel))

    report = tco(client, car, tenure)
    explanation = report["resale_value_explanation"]

    values = [explanation["base_value"], explanation["predicted_value"], *explanation["contributions"].values()]
    assert all(isinstance(v, str) and Decimal(v) == Decimal(v).quantize(TWO_DP) and "." in v for v in values)
    assert explanation["base_value"] == "267800.00"
    total = Decimal(explanation["base_value"]) + sum(Decimal(v) for v in explanation["contributions"].values())
    assert total == Decimal(explanation["predicted_value"])
    # and it is still the curve's own value at that month, to the sen
    assert explanation["predicted_value"] == report["monthly_forecast"][tenure]["predicted_resale_value"]


def as_numbers(explanation):
    return {
        "base_value": float(explanation["base_value"]),
        "contributions": {k: float(v) for k, v in explanation["contributions"].items()},
        "predicted_value": float(explanation["predicted_value"]),
    }


def test_the_pdf_block_reads_numbers_and_strings_the_same(client, car, tmp_path):
    _deploy(tmp_path, fit_log_price_estimator(LogLinearDepreciationModel))
    explanation = tco(client, car)["resale_value_explanation"]

    with_strings = rows.build_explanation_section({"model_degraded": False, "resale_value_explanation": explanation})
    with_numbers = rows.build_explanation_section(
        {"model_degraded": False, "resale_value_explanation": as_numbers(explanation)})

    assert with_strings == with_numbers
    assert with_strings["new_price"] == "RM 267,800.00"


def test_the_pdf_export_prints_the_explanation(client, car, tmp_path):
    try:
        import weasyprint  # noqa: F401
    except Exception as exc:  # native libraries missing (OSError, not ImportError)
        pytest.skip(f"weasyprint is not usable in this environment: {exc}")
    pypdf = pytest.importorskip("pypdf")
    _deploy(tmp_path, fit_log_price_estimator(LogLinearDepreciationModel))
    explanation = tco(client, car)["resale_value_explanation"]

    response = client.post("/api/exports/pdf/", {
        "vehicle": car.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "26780.00", "chart_svg": "",
    }, format="json")

    assert response.status_code == 200
    text = " ".join(" ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(response.content)).pages).split())
    assert "Why this predicted value?" in text
    predicted = Decimal(explanation["predicted_value"])
    assert f"RM {predicted:,.2f}" in text


def test_an_older_snapshot_with_number_amounts_still_opens_as_saved(client, car, regular_user):
    old = {"tco": {"model_degraded": False, "resale_value_explanation": {
        "base_value": 267800.0,
        "contributions": {"vehicle_age": -108726.02, "mileage": -23405.48, "brand_code": 0.0, "engine_litres": 0.0,
                          "body_type": 0.0, "recond": 0.0},
        "predicted_value": 135668.5,
    }}}
    scenario = SavedScenario.objects.create(user=regular_user, title="Before batch 5", vehicle=car, payload=old)

    response = client.get(f"/api/scenarios/{scenario.pk}/")

    assert response.status_code == 200
    assert response.data["payload"] == old
