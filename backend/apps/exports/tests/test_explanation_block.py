"""Run 2 fix batch 3 (ML-3, A11, G6): the PDF's 'Why this predicted value?' block
lists the factors in the fixed order, leaves out any that round to 0.00, prints
whole sen and adds up exactly - whatever key order the figures arrive in (a saved
or JSON-round-tripped report does not keep it)."""

from decimal import Decimal

import pytest

from apps.depreciation.services import build_tco_report
from apps.depreciation.tests.test_explanation import _deploy, fit_log_price_estimator
from apps.exports.comparison_rows import EXPLANATION_FACTOR_LABELS, build_explanation_section
from apps.ml.log_linear import LogLinearDepreciationModel
from apps.policy.models import InterestRate, MileageBand
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

ORDER = ["Age", "Mileage", "Brand tier", "Engine size", "Body type", "Recond import"]


def signed(text):
    """'-RM 1,234.50' / '+RM 20.00' -> Decimal."""
    sign = -1 if text.startswith("-") else 1
    return sign * Decimal(text[1:].replace("RM", "").replace(",", "").strip())


def money(text):
    return Decimal(text.replace("RM", "").replace(",", "").strip())


def report_with(contributions, base=100000.0, predicted=99000.0):
    return {
        "model_degraded": False,
        "resale_value_explanation": {"base_value": base, "contributions": contributions, "predicted_value": predicted},
    }


def test_the_labels_are_in_the_documented_order():
    assert list(EXPLANATION_FACTOR_LABELS.values()) == ORDER


def test_rows_follow_the_fixed_order_whatever_order_the_figures_arrive_in():
    # Alphabetical, as a JSON column returns it - not the order the card is read in.
    arrived = {"body_type": -1.0, "brand_code": -2.0, "engine_litres": -3.0, "mileage": -4.0, "recond": -5.0,
               "vehicle_age": -6.0}

    section = build_explanation_section(report_with(arrived, 100.0, 79.0))

    assert [row["label"] for row in section["rows"]] == ORDER


def test_factors_that_round_to_zero_are_left_out():
    section = build_explanation_section(
        report_with({"vehicle_age": -900.0, "mileage": -100.0, "brand_code": 0.0, "engine_litres": 0.004,
                     "body_type": -0.004, "recond": 0.0})
    )

    assert [row["label"] for row in section["rows"]] == ["Age", "Mileage"]
    assert section["rows"][0]["value"] == "-RM 900.00"


def test_a_missing_factor_is_skipped_not_an_error():
    section = build_explanation_section(report_with({"mileage": -1000.0}))

    assert [row["label"] for row in section["rows"]] == ["Mileage"]


def test_the_block_on_a_real_report_adds_up_to_the_sen(tmp_path):
    brand = Brand.objects.create(name="PdfBlockBrand", tier_code="3")
    InterestRate.objects.create(brand=brand, rate_percent="2.8000")
    car = VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN, msrp="267800.00",
        engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    car.refresh_from_db()
    _deploy(tmp_path, fit_log_price_estimator(LogLinearDepreciationModel))

    for tenure in (36, 48, 60):
        report = build_tco_report(
            vehicle=car, tenure_months=tenure, mileage_band=MileageBand.STANDARD, downpayment=Decimal("26780.00"),
            ncd_percent=Decimal("0"),
        )
        section = build_explanation_section(report)

        assert section["rows"], "a 3-year-old+ car has factors that moved the value"
        labels = [row["label"] for row in section["rows"]]
        assert labels == [label for label in ORDER if label in labels]
        total = money(section["new_price"]) + sum(signed(row["value"]) for row in section["rows"])
        assert total == money(section["predicted"])
        # and it is the figure the TCO curve shows at that month
        assert money(section["predicted"]) == report["monthly_forecast"][tenure]["predicted_resale_value"]
