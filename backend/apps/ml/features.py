"""ML batch 1: the ONE definition of the depreciation model's features.

The dataset build (build_real_ml_dataset), training and upload validation
(apps/ml/training.py) and inference (apps/depreciation/inference.py) all
import these names, so the column order the model was fitted on and the row
inference builds can never drift apart.

What is deliberately NOT a feature:
- msrp_proxy: a used price standing in for a new price (see
  apps/ml/data/README_real_data.md); dropped with the ratio target.
- Monthly_Installment (raw listing column): always exactly 1.2965% of the
  asking price, i.e. the target in disguise - it would fake a near-perfect R².
"""

import re

import pandas as pd

from apps.vehicles.models import BodySegment

BODY_TYPES = ["sedan", "hatchback", "suv", "mpv", "pickup", "coupe"]
BODY_COLUMNS = [f"body_{body}" for body in BODY_TYPES]
NUMERIC_COLUMNS = ["vehicle_age", "mileage", "brand_code", "engine_litres", "recond"]
FEATURE_COLUMNS = NUMERIC_COLUMNS + BODY_COLUMNS

# The advert word (Carlist listing titles) -> body type.
_LISTING_BODY_MAP = {
    "sedan": "sedan",
    "hatchback": "hatchback",
    "suv": "suv",
    "crossover": "suv",
    "mpv": "mpv",
    "van": "mpv",
    "pickup truck": "pickup",
    "coupe": "coupe",
    "convertible": "coupe",
    "wagon": "hatchback",
}
_LISTING_BODY_RE = re.compile(
    r"\b(Sedan|Hatchback|SUV|MPV|Pickup Truck|Coupe|Convertible|Wagon|Van|Crossover)\b", re.IGNORECASE
)

# The catalog's body segment -> body type. A segment added later that is not
# listed here maps to None, so that car uses the fallback curve - never a guess.
_SEGMENT_BODY_MAP = {
    BodySegment.SEDAN: "sedan",
    BodySegment.HATCHBACK: "hatchback",
    BodySegment.SUV: "suv",
    BodySegment.MPV: "mpv",
    BodySegment.PICKUP: "pickup",
    BodySegment.COUPE: "coupe",
    BodySegment.CROSSOVER: "suv",
    BodySegment.VAN: "mpv",
}


def body_type_for_listing(text):
    """The body type named in a listing's text (the first body word found,
    case-insensitive), e.g. "Sedan" -> "sedan", "Pickup Truck" -> "pickup",
    "Convertible" -> "coupe". None when no known body word appears."""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return None
    match = _LISTING_BODY_RE.search(str(text))
    return _LISTING_BODY_MAP[match.group(1).lower()] if match else None


def body_type_for_segment(segment):
    """The body type for a catalog BodySegment value; None when unmapped."""
    return _SEGMENT_BODY_MAP.get(segment)


def capped_mileage(annual_mileage_km, year, mileage_caps=None):
    """annual km x age, capped at the highest total mileage the training data has
    at that age when `mileage_caps` ({age: km}) is given (Run 3 fix batch 6: the
    model is never read beyond the mileage it has seen)."""
    km = float(annual_mileage_km) * year
    if mileage_caps and year in mileage_caps:
        km = min(km, float(mileage_caps[year]))
    return km


def car_feature_frame(car, annual_mileage_km, years, mileage_caps=None):
    """The model's input rows for one catalog car at the given ages in whole
    years (ML batch 2: the data records age in whole years, so a curve is read
    at whole years and the months are interpolated - see
    apps/depreciation/inference.py). `car` = {"brand_code", "engine_litres",
    "body_type"}; mileage = annual km x age (capped - see capped_mileage);
    recond = 0 (catalog cars are new)."""
    rows = [
        {
            "vehicle_age": float(year),
            "mileage": capped_mileage(annual_mileage_km, year, mileage_caps),
            "brand_code": float(car["brand_code"]),
            "engine_litres": float(car["engine_litres"]),
            "recond": 0.0,
            "body_type": car["body_type"],
        }
        for year in years
    ]
    return feature_frame(pd.DataFrame(rows))


def feature_frame(df):
    """The model's input frame, columns exactly FEATURE_COLUMNS (floats): the
    numeric columns as they are, plus one 0/1 column per BODY_TYPES entry, in
    that order. `df` needs the NUMERIC_COLUMNS and a `body_type` column."""
    frame = df[NUMERIC_COLUMNS].astype(float).copy()
    for body, column in zip(BODY_TYPES, BODY_COLUMNS):
        frame[column] = (df["body_type"] == body).astype(float)
    return frame[FEATURE_COLUMNS]
