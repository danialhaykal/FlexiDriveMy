"""build_real_ml_dataset v2 (ML batch 1): duplicates dropped, a blank Model
recovered from Description only for a known brand, model_key cut at the engine
token, recond from a "YYYY/YYYY" pair, engine litres and body type from the
listing text (a row missing either is dropped), no msrp_proxy."""

import math

import pandas as pd
import pytest

from apps.ml.management.commands.build_real_ml_dataset import (
    OUTPUT_COLUMNS,
    build_dataset,
    compute_brand_tiers,
    extract_brand,
    extract_engine_litres,
    extract_year,
    is_recond,
    model_key,
    parse_mileage,
    parse_price,
    recover_model,
)

# --- parse_price -------------------------------------------------------------


def test_parse_price_strips_rm_prefix_and_commas():
    assert parse_price("RM 87,888") == 87888.0


def test_parse_price_handles_no_thousands_separator():
    assert parse_price("RM 9800") == 9800.0


def test_parse_price_null_is_nan():
    assert math.isnan(parse_price(None))
    assert math.isnan(parse_price(float("nan")))


def test_parse_price_unparseable_is_nan():
    assert math.isnan(parse_price("N/A"))


# --- parse_mileage -------------------------------------------------------------


def test_parse_mileage_range_takes_midpoint_times_1000():
    assert parse_mileage("145 - 150K KM") == 147500.0


def test_parse_mileage_plain_reading_has_no_k_multiplier():
    # A plain absolute reading with no range and no "K" - "118777 KM" means
    # 118777 km, not 118,777,000.
    assert parse_mileage("118777 KM") == 118777.0


def test_parse_mileage_null_is_nan():
    assert math.isnan(parse_mileage(None))


def test_parse_mileage_unparseable_is_nan():
    assert math.isnan(parse_mileage("unknown"))


# --- years and recond ------------------------------------------------------------


def test_extract_year_single_year():
    assert extract_year("2017 Honda Civic 1.8 S i-VTEC Sedan - (A) NO PROCESSING CHARGE") == 2017


def test_extract_year_dual_year_takes_the_first():
    assert extract_year("2013/2014 BMW 528i 2.0 Sedan - M Sport service record F10 full spec") == 2013


def test_extract_year_no_leading_year_is_none():
    assert extract_year("No year here at all") is None
    assert extract_year(None) is None


def test_recond_is_a_leading_year_pair_only():
    assert is_recond("2013/2014 BMW 528i 2.0 Sedan") == 1
    assert is_recond("2017 Honda Civic 1.8 Sedan") == 0
    assert is_recond("2017 Honda Civic 1.8 Sedan 2018/2019 spec") == 0  # a pair later in the text doesn't count
    assert is_recond(None) == 0


# --- brand, Model recovery and model_key ------------------------------------------------


def test_extract_brand_single_word_hyphenated_and_land_rover():
    assert extract_brand("BMW 528i") == "BMW"
    assert extract_brand("Mercedes-Benz C200") == "Mercedes-Benz"
    assert extract_brand("Land Rover Range Rover Sport") == "Land Rover"
    assert extract_brand(None) is None


def test_recover_model_takes_brand_and_next_word_after_the_years():
    known = {"Mercedes-Benz", "Land Rover", "Volvo"}
    assert recover_model("2019 Mercedes-Benz S400L 3.0 Sedan", known) == "Mercedes-Benz S400L"
    assert recover_model("2018/2019 Volvo XC40 2.0 SUV", known) == "Volvo XC40"
    assert recover_model("2017 Land Rover Range Rover 3.0 SUV", known) == "Land Rover Range"


def test_recover_model_never_guesses_an_unknown_brand():
    assert recover_model("2019 Chery Tiggo 1.5 SUV", {"BMW"}) is None
    assert recover_model("2019", {"BMW"}) is None
    assert recover_model(None, {"BMW"}) is None


def test_model_key_is_cut_at_the_first_engine_token():
    assert model_key("Porsche Macan 2.0") == "Porsche Macan"
    assert model_key("Lexus ES250 2.5 Luxury") == "Lexus ES250"
    assert model_key("BMW 528i") == "BMW 528i"


def test_engine_litres_from_the_description_token():
    assert extract_engine_litres("2017 Honda Civic 1.8 S i-VTEC Sedan") == 1.8
    assert math.isnan(extract_engine_litres("2017 Honda Civic Sedan"))
    assert math.isnan(extract_engine_litres("2017 Honda Civic 1.8"))  # the token needs a space after it


# --- compute_brand_tiers -----------------------------------------------------------


def test_compute_brand_tiers_highest_price_gets_tier_1():
    median_price_by_brand = pd.Series(
        {"Porsche": 248500.0, "Toyota": 129888.0, "BMW": 87844.0, "Nissan": 48999.0, "Perodua": 32800.0}
    )

    tiers = compute_brand_tiers(median_price_by_brand)

    assert tiers["Porsche"] == 1  # highest median price
    assert tiers["Perodua"] == 5  # lowest median price
    assert tiers["Toyota"] < tiers["Nissan"]
    assert set(tiers.values()) == {1, 2, 3, 4, 5}


# --- build_dataset (the full pipeline) on a small fixture ------------------------------------


def _raw_row(description, list_price, model, milleage="100 - 105K KM", listing_year=2021):
    return {
        "Description": description,
        "Monthly_Installment": "RM 500 / month",
        "List_Price": list_price,
        "Model": model,
        "Milleage": milleage,
        "Gear_Type": "Automatic",
        "Location": "Selangor, Puchong",
        "Listing_Year": listing_year,
    }


FIXTURE = [
    _raw_row("2017 Honda Civic 1.8 S i-VTEC Sedan - (A)", "RM 70,800", "Honda Civic"),
    _raw_row("2017 Honda Civic 1.8 S i-VTEC Sedan - (A)", "RM 70,800", "Honda Civic"),  # exact duplicate
    _raw_row("2013/2014 BMW 528i 2.0 Sedan - M Sport", "RM 87,888", "BMW 528i", "145 - 150K KM"),
    _raw_row("2020 BMW X5 3.0 xDrive45e SUV", "RM 350,000", None, "10 - 15K KM"),  # recovered: BMW is known
    _raw_row("2019 Chery Tiggo 1.5 SUV", "RM 60,000", None),  # Chery is not known: dropped
    _raw_row("2021 Porsche Macan 2.0 SUV", "RM 400,000", "Porsche Macan 2.0", "20 - 25K KM"),
    _raw_row("2018 Toyota Vios Sedan no engine size", "RM 50,000", "Toyota Vios"),  # no engine token: dropped
    _raw_row("2018 Toyota Hilux 2.4 Pickup Truck", "RM 90,000", "Toyota Hilux 2.4 G"),
    _raw_row("2015 Toyota Vellfire 2.5 MPV", None, "Toyota Vellfire"),  # no price: dropped
]


def build_fixture():
    return build_dataset(pd.DataFrame(FIXTURE))


def test_build_writes_the_v2_columns_in_order_and_no_msrp_proxy():
    final_df, _ = build_fixture()

    assert list(final_df.columns) == OUTPUT_COLUMNS == [
        "vehicle_age", "mileage", "resale_price", "brand_code", "engine_litres", "body_type", "recond", "model_key",
    ]
    assert "msrp_proxy" not in final_df.columns
    assert "Monthly_Installment" not in final_df.columns


def test_build_counts_every_drop_and_recovery():
    final_df, stats = build_fixture()

    assert stats["raw_row_count"] == 9
    assert stats["dropped_duplicates"] == 1
    assert stats["dropped_null_price"] == 1
    assert stats["model_recovered"] == 1
    assert stats["dropped_null_model"] == 1
    assert stats["dropped_missing_engine_or_body"] == 1
    assert stats["final_row_count"] == len(final_df) == 5


def test_build_recovers_the_known_brand_and_keys_models_without_the_engine():
    final_df, _ = build_fixture()

    assert set(final_df["model_key"]) == {"Honda Civic", "BMW 528i", "BMW X5", "Porsche Macan", "Toyota Hilux"}


def test_build_sets_recond_engine_and_body():
    final_df, stats = build_fixture()
    by_key = final_df.set_index("model_key")

    assert by_key.loc["BMW 528i", "recond"] == 1
    assert by_key.loc["Honda Civic", "recond"] == 0
    assert stats["recond_count"] == 1
    assert by_key.loc["BMW 528i", "engine_litres"] == 2.0
    assert by_key.loc["Toyota Hilux", "body_type"] == "pickup"
    assert by_key.loc["Porsche Macan", "body_type"] == "suv"
    assert stats["body_type_counts"] == {"sedan": 2, "hatchback": 0, "suv": 2, "mpv": 0, "pickup": 1, "coupe": 0}


def test_a_convertible_listing_is_a_coupe():
    final_df, _ = build_dataset(pd.DataFrame([
        _raw_row("2016 Mini Cooper 2.0 Convertible", "RM 120,000", "Mini Cooper"),
        _raw_row("2017 Honda Civic 1.8 Sedan", "RM 70,800", "Honda Civic"),
    ]))

    assert final_df.set_index("model_key").loc["Mini Cooper", "body_type"] == "coupe"


def test_build_ages_each_row_from_its_own_listing_year():
    """ML batch 2: age = the row's Listing_Year - its model year, never one
    reference year for the whole file."""
    final_df, stats = build_dataset(pd.DataFrame([
        _raw_row("2021 Porsche Macan 2.0 SUV", "RM 400,000", "Porsche Macan 2.0", listing_year=2022),
        _raw_row("2013/2014 BMW 528i 2.0 Sedan", "RM 87,888", "BMW 528i", listing_year=2022),
        _raw_row("2023 Lexus ES 250 2.5 Sedan", "RM 220,800", "Lexus ES250 2.5 Luxury", listing_year=2026),
    ]))
    by_key = final_df.set_index("model_key")

    assert "reference_year" not in stats
    assert by_key.loc["Porsche Macan", "vehicle_age"] == 1   # 2022 - 2021 (one reference year 2023 said 2)
    assert by_key.loc["BMW 528i", "vehicle_age"] == 9        # 2022 - 2013, the first year of the pair
    assert by_key.loc["Lexus ES250", "vehicle_age"] == 3     # 2026 - 2023 (one reference year said 0)
    assert stats["listing_years"] == {2022: 2, 2026: 1}
    assert stats["age_counts"] == {1: 1, 3: 1, 9: 1}


@pytest.mark.parametrize("missing", [None, "", "not a year", 2021.5])
def test_a_row_without_a_usable_listing_year_is_dropped_and_counted(missing):
    final_df, stats = build_dataset(pd.DataFrame([
        _raw_row("2017 Honda Civic 1.8 Sedan", "RM 70,800", "Honda Civic", listing_year=2022),
        _raw_row("2018 Toyota Vios 1.5 Sedan", "RM 50,000", "Toyota Vios", listing_year=missing),
    ]))

    assert stats["dropped_no_listing_year"] == 1
    assert list(final_df["model_key"]) == ["Honda Civic"]


def test_a_file_without_the_listing_year_column_is_refused_never_given_a_guessed_year():
    raw = pd.DataFrame([_raw_row("2017 Honda Civic 1.8 Sedan", "RM 70,800", "Honda Civic")]).drop(
        columns=["Listing_Year"]
    )

    with pytest.raises(ValueError, match="no Listing_Year column"):
        build_dataset(raw)


def test_build_drops_rows_with_a_non_positive_price():
    final_df, stats = build_dataset(pd.DataFrame([
        _raw_row("2017 Honda Civic 1.8 Sedan", "RM 70,800", "Honda Civic"),
        _raw_row("2018 Toyota Vios 1.5 Sedan", "RM 0", "Toyota Vios"),
    ]))

    assert stats["dropped_numeric_sanity"] == 1
    assert (final_df["resale_price"] > 0).all()


def test_build_assigns_brand_tiers_by_median_price():
    final_df, _ = build_dataset(pd.DataFrame([
        _raw_row("2017 Porsche 911 3.0 Coupe", "RM 500,000", "Porsche 911", "10 - 15K KM"),
        _raw_row("2017 Perodua Myvi 1.5 Hatchback", "RM 30,000", "Perodua Myvi", "10 - 15K KM"),
    ]))

    by_price = final_df.set_index("resale_price")
    assert by_price.loc[500000.0, "brand_code"] == 1
    assert by_price.loc[30000.0, "brand_code"] == 5
