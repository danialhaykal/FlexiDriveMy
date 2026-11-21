"""ML batch 2: the curve check - a deploy rule next to the 0.80 R² gate.

A model can score well on held-out prices and still draw a depreciation curve
no buyer should see (run 9's Gradient Boosting kept 100% of the price for the
first ten months, and the Alphard for 34). Before a run can be deployed, the
winning candidate's curve is read at whole years 0..5 for every catalog car
the model covers, and any of these is a problem:

- the value rises from one year to the next by more than CURVE_RISE_TOLERANCE
  on the log scale (about 1%);
- more than MAX_RETAINED_AFTER_12_MONTHS of the new price is kept after 12
  months;
- after 60 months the car keeps less than MIN_RETAINED_AFTER_60_MONTHS or more
  than MAX_RETAINED_AFTER_60_MONTHS (a later rise is ignored here - the clamp
  holds the curve at the year-0 level - and reported by the first rule).

These limits are SANITY LIMITS that catch a broken curve, not market claims
about how fast any car loses value; they are deliberately wide.

Framework-free: the caller (apps/ml/tasks.py) reads the catalog and passes
the reference cars in.
"""

import math

import numpy as np

from .features import car_feature_frame

CURVE_YEARS = range(6)
CURVE_RISE_TOLERANCE = 0.01
MAX_RETAINED_AFTER_12_MONTHS = 0.95
MIN_RETAINED_AFTER_60_MONTHS = 0.20
MAX_RETAINED_AFTER_60_MONTHS = 0.75
NO_REFERENCE_CAR = "no catalog car to check"


def yearly_log_prices(model, car, annual_mileage_km):
    """The model's log-price prediction at whole years 0..5 for one car."""
    return np.asarray(model.predict(car_feature_frame(car, annual_mileage_km, CURVE_YEARS)), dtype=float)


def curve_problems(model, reference_cars, annual_mileage_km):
    """Every problem found, as plain strings; [] means the check passed.
    `reference_cars` is a list of (name, car features) pairs; none at all is
    itself a failure (there is nothing to show the curve is sane)."""
    if not reference_cars:
        return [NO_REFERENCE_CAR]
    problems = []
    for name, car in reference_cars:
        logs = yearly_log_prices(model, car, annual_mileage_km)
        for year in range(len(logs) - 1):
            if logs[year + 1] > logs[year] + CURVE_RISE_TOLERANCE:
                problems.append(f"{name}: value rises from year {year} to {year + 1}")
        kept_12 = math.exp(logs[1] - logs[0])
        kept_60 = math.exp(min(logs[5], logs[0]) - logs[0])
        # One decimal: a value just over a limit must not read as the limit itself.
        if kept_12 > MAX_RETAINED_AFTER_12_MONTHS:
            problems.append(
                f"{name}: keeps {kept_12:.1%} after 12 months (limit {MAX_RETAINED_AFTER_12_MONTHS:.0%})"
            )
        if not MIN_RETAINED_AFTER_60_MONTHS <= kept_60 <= MAX_RETAINED_AFTER_60_MONTHS:
            problems.append(
                f"{name}: keeps {kept_60:.1%} after 60 months (allowed {MIN_RETAINED_AFTER_60_MONTHS:.0%}-"
                f"{MAX_RETAINED_AFTER_60_MONTHS:.0%})"
            )
    return problems


def rejection_reason(problems):
    """"Curve check failed: <first problem> (+N more)"."""
    more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
    return f"Curve check failed: {problems[0]}{more}"
