"""ML batch 2: the curve check (apps/ml/curve_check.py) - a deploy rule next to
the 0.80 gate. Sanity limits, not market claims."""

import math

import pytest

from apps.ml import curve_check

CAR = {"brand_code": 2, "engine_litres": 2.0, "body_type": "sedan"}
CARS = [("BMW 320i", CAR), ("Alphard", {"brand_code": 1, "engine_litres": 2.4, "body_type": "mpv"})]


class YearlyModel:
    """Predicts log price from a per-year retained share: kept[y] at age y."""

    def __init__(self, kept):
        self.kept = kept

    def predict(self, rows):
        return [math.log(100000 * self.kept[int(age)]) for age in rows["vehicle_age"]]


HEALTHY = [1.0, 0.88, 0.78, 0.68, 0.59, 0.51]


def test_the_limits_are_the_documented_sanity_limits():
    assert curve_check.CURVE_RISE_TOLERANCE == 0.01
    assert curve_check.MAX_RETAINED_AFTER_12_MONTHS == 0.95
    assert (curve_check.MIN_RETAINED_AFTER_60_MONTHS, curve_check.MAX_RETAINED_AFTER_60_MONTHS) == (0.20, 0.75)


def test_a_healthy_curve_passes_for_every_car():
    assert curve_check.curve_problems(YearlyModel(HEALTHY), CARS, 15000) == []


def test_the_model_is_read_at_whole_years_0_to_5_with_the_annual_mileage():
    seen = []

    class Recording(YearlyModel):
        def predict(self, rows):
            seen.append(rows[["vehicle_age", "mileage", "recond"]].to_dict("records"))
            return super().predict(rows)

    curve_check.curve_problems(Recording(HEALTHY), CARS[:1], 15000)

    assert seen[0] == [{"vehicle_age": float(y), "mileage": 15000.0 * y, "recond": 0.0} for y in range(6)]


def test_a_rise_from_one_year_to_the_next_fails():
    problems = curve_check.curve_problems(YearlyModel([1.0, 0.85, 0.88, 0.68, 0.59, 0.51]), CARS[:1], 15000)

    assert problems == ["BMW 320i: value rises from year 1 to 2"]


def test_a_rise_within_the_tolerance_is_not_a_problem():
    # +0.5% on the log scale (under 0.01)
    assert curve_check.curve_problems(YearlyModel([1.0, 0.85, 0.854, 0.68, 0.59, 0.51]), CARS[:1], 15000) == []


def test_keeping_too_much_after_12_months_fails_with_one_decimal():
    problems = curve_check.curve_problems(YearlyModel([1.0, 0.953, 0.78, 0.68, 0.59, 0.51]), CARS[:1], 15000)

    assert problems == ["BMW 320i: keeps 95.3% after 12 months (limit 95%)"]


@pytest.mark.parametrize("kept_60, shown", [(0.80, "80.0%"), (0.15, "15.0%")])
def test_keeping_too_much_or_too_little_after_60_months_fails(kept_60, shown):
    kept = [1.0, 0.88, 0.78, 0.68, 0.59, kept_60]
    if kept_60 > 0.59:
        kept = [1.0, 0.92, 0.88, 0.85, 0.82, kept_60]

    problems = curve_check.curve_problems(YearlyModel(kept), CARS[:1], 15000)

    assert problems == [f"BMW 320i: keeps {shown} after 60 months (allowed 20%-75%)"]


def test_a_stair_step_curve_like_run_9_fails_and_every_car_is_reported():
    flat_first_year = [1.0, 1.0, 0.89, 0.89, 0.68, 0.53]

    problems = curve_check.curve_problems(YearlyModel(flat_first_year), CARS, 15000)

    assert problems == [
        "BMW 320i: keeps 100.0% after 12 months (limit 95%)",
        "Alphard: keeps 100.0% after 12 months (limit 95%)",
    ]
    assert curve_check.rejection_reason(problems) == (
        "Curve check failed: BMW 320i: keeps 100.0% after 12 months (limit 95%) (+1 more)"
    )


def test_one_problem_has_no_more_suffix():
    assert curve_check.rejection_reason(["X: value rises from year 0 to 1"]) == (
        "Curve check failed: X: value rises from year 0 to 1"
    )


def test_no_reference_car_fails_the_check():
    assert curve_check.curve_problems(YearlyModel(HEALTHY), [], 15000) == ["no catalog car to check"]
