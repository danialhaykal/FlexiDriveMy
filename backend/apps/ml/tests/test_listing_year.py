"""ML batch 2: the one-off Listing_Year column (apps/ml/listing_year.py) - the
asserts, the years written, and that every old byte is unchanged."""

import csv
import io
from pathlib import Path

import pandas as pd
import pytest

from apps.ml.listing_year import (
    HAND_COLLECTED_LISTING_YEAR,
    KAGGLE_LISTING_YEAR,
    ListingYearError,
    add_listing_year_column,
)

RAW_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "resale_car.csv"
HEADER = "Description,Monthly_Installment,List_Price,Model,Milleage,Gear_Type,Location"


def raw_file(kaggle_rows=2, hand_rows=30, hand_last=True):
    """A small raw file in resale_car.csv's own layout: CRLF record ends, quoted
    cells with commas, and a multi-line (bare LF) quoted description."""
    kaggle = [
        '"2017 Honda Civic 1.8 Sedan - line one\nline two","RM 1,139 / month","RM 87,888",Honda Civic,'
        '145 - 150K KM,Automatic,"Selangor, Puchong"'
        for _ in range(kaggle_rows)
    ]
    hand = [
        f'"2023 Lexus ES 250 2.5 Luxury Sedan - row {i}",,"RM 220,800",Lexus ES250 2.5 Luxury,35 - 40K KM,'
        f'Automatic,"Kuala Lumpur, Cheras"'
        for i in range(hand_rows)
    ]
    rows = kaggle + hand if hand_last else hand[:1] + kaggle + hand[1:]
    return ("\r\n".join([HEADER] + rows) + "\r\n").encode("utf-8")


def records(data):
    return list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))


def test_the_years_are_appended_and_every_old_cell_is_unchanged():
    raw = raw_file()

    new, report = add_listing_year_column(raw)

    old_records, new_records = records(raw), records(new)
    assert new_records[0] == old_records[0] + ["Listing_Year"]
    assert [r[:-1] for r in new_records] == old_records
    assert [r[-1] for r in new_records[1:]] == [str(KAGGLE_LISTING_YEAR)] * 2 + [str(HAND_COLLECTED_LISTING_YEAR)] * 30
    assert "assert ok: removing the new column gives back the original file byte for byte" in report
    assert report[-1] == "Listing_Year: 2 rows = 2022, 30 rows = 2026"


def test_removing_the_new_column_gives_back_the_original_bytes_including_multi_line_cells():
    raw = raw_file()
    new, _ = add_listing_year_column(raw)

    restored = new.replace(b",Listing_Year\r\n", b"\r\n").replace(b",2022\r\n", b"\r\n").replace(b",2026\r\n", b"\r\n")

    assert restored == raw
    assert b"line one\nline two" in new  # the bare LF inside a quoted cell is not a record end


def test_it_refuses_when_the_hand_collected_rows_are_not_the_last_30():
    with pytest.raises(ListingYearError, match="exactly the last 30"):
        add_listing_year_column(raw_file(hand_last=False))
    with pytest.raises(ListingYearError, match="exactly the last 30"):
        add_listing_year_column(raw_file(hand_rows=29))


def test_a_second_run_refuses_and_writes_nothing():
    new, _ = add_listing_year_column(raw_file())

    with pytest.raises(ListingYearError, match="already present"):
        add_listing_year_column(new)


def test_the_real_raw_file_carries_the_listing_year_for_every_row():
    df = pd.read_csv(RAW_PATH)

    assert len(df) == 1004
    assert list(df.columns)[-1] == "Listing_Year"
    hand = df["Monthly_Installment"].isna()
    assert set(df.loc[hand, "Listing_Year"]) == {2026} and hand.sum() == 30 and hand.iloc[-30:].all()
    assert set(df.loc[~hand, "Listing_Year"]) == {2022}
