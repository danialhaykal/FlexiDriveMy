"""ML batch 1: apps/ml/features.py is the one definition of the model's
features, shared by the dataset build, training, upload validation and
inference."""

import pandas as pd
import pytest

from apps.ml import features, training
from apps.ml.management.commands import build_real_ml_dataset
from apps.vehicles.models import BodySegment


def test_the_feature_columns_in_their_exact_order():
    assert features.FEATURE_COLUMNS == [
        "vehicle_age", "mileage", "brand_code", "engine_litres", "recond",
        "body_sedan", "body_hatchback", "body_suv", "body_mpv", "body_pickup", "body_coupe",
    ]
    assert features.BODY_TYPES == ["sedan", "hatchback", "suv", "mpv", "pickup", "coupe"]


def test_leaky_columns_are_never_features():
    """Monthly_Installment is always exactly 1.2965% of the asking price (the
    target in disguise); msrp_proxy was a used price posing as a new one."""
    for leaky in ("Monthly_Installment", "monthly_installment", "msrp_proxy", "resale_price", "model_key"):
        assert leaky not in features.FEATURE_COLUMNS


def test_every_user_of_the_features_imports_the_one_definition():
    from apps.depreciation import inference

    assert inference.FEATURE_COLUMNS is features.FEATURE_COLUMNS
    # ML batch 2: inference builds its yearly rows through car_feature_frame,
    # the same function the curve check uses.
    from apps.ml import curve_check, log_linear

    assert inference.car_feature_frame is features.car_feature_frame
    assert curve_check.car_feature_frame is features.car_feature_frame
    assert log_linear.FEATURE_COLUMNS is features.FEATURE_COLUMNS
    assert training.feature_frame is features.feature_frame
    assert build_real_ml_dataset.body_type_for_listing is features.body_type_for_listing


@pytest.mark.parametrize(
    "word, body",
    [
        ("Sedan", "sedan"), ("Hatchback", "hatchback"), ("SUV", "suv"), ("Crossover", "suv"),
        ("MPV", "mpv"), ("Van", "mpv"), ("Pickup Truck", "pickup"), ("Coupe", "coupe"),
        ("Convertible", "coupe"), ("Wagon", "hatchback"), ("sedan", "sedan"),
    ],
)
def test_body_type_for_listing_maps_the_advert_word(word, body):
    assert features.body_type_for_listing(word) == body
    assert features.body_type_for_listing(f"2017 Some Car 2.0 {word} - full spec") == body


@pytest.mark.parametrize("text", ["Pickup", "Cabriolet", "Truck", "", None, float("nan"), "Vanguard 2.0"])
def test_body_type_for_listing_never_guesses(text):
    assert features.body_type_for_listing(text) is None


def test_body_type_for_segment_covers_all_eight_catalog_segments():
    assert {segment: features.body_type_for_segment(segment) for segment in BodySegment.values} == {
        "sedan": "sedan", "hatchback": "hatchback", "suv": "suv", "mpv": "mpv",
        "pickup": "pickup", "coupe": "coupe", "crossover": "suv", "van": "mpv",
    }


def test_a_segment_added_later_is_not_guessed():
    assert features.body_type_for_segment("roadster") is None
    assert features.body_type_for_segment(None) is None


def test_feature_frame_one_hot_encodes_the_body_in_body_types_order():
    df = pd.DataFrame([
        {"vehicle_age": 1, "mileage": 15000, "brand_code": 2, "engine_litres": 2.0, "recond": 0, "body_type": "suv"},
        {"vehicle_age": 3, "mileage": 45000, "brand_code": 1, "engine_litres": 2.5, "recond": 1, "body_type": "coupe"},
    ])

    frame = features.feature_frame(df)

    assert list(frame.columns) == features.FEATURE_COLUMNS
    assert frame.iloc[0].tolist() == [1.0, 15000.0, 2.0, 2.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    assert frame.iloc[1].tolist() == [3.0, 45000.0, 1.0, 2.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
