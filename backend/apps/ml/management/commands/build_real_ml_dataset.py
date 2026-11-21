"""Builds apps/ml/data/real_historical_pricing.csv from a real Kaggle
used-car listing dataset - the dataset F012 is retrained against (the
SYNTHETIC placeholder, synthetic_historical_pricing.csv, is left untouched -
see apps/ml/data/README.md and apps/ml/data/README_real_data.md).

Version 2 (ML batch 1): the model now predicts the resale price itself (log
scale) from the car's own attributes, so this build adds engine size, body
type and the recond flag, recovers the rows it used to drop for a blank
Model, and no longer builds msrp_proxy (a used price standing in for a new
price - the root cause of the old ratio target's mismatch).

Reads ONLY apps/ml/data/raw/resale_car.csv (1,004 rows, mixed-brand real
used-car listings). apps/ml/data/raw/Malaysia_Final_CarList_Compiled.csv
(6,000 rows) is deliberately NOT read by this command: every one of its
rows is brand "Perodua", which doesn't offer GFV leasing - this
platform's actual target niche - so those 6,000 rows would swamp the
mixed-brand rows without adding anything for the brands that matter.

resale_car.csv's raw columns (confirmed by direct inspection, not
assumed): Description, Monthly_Installment, List_Price, Model, Milleage
(sic - that typo is the actual header), Gear_Type, Location, and (ML batch 2)
Listing_Year.
Monthly_Installment is never used: it is always exactly 1.2965% of the
price (the target in disguise).

Steps, in order (each drop is counted in the returned stats):

1. Exact duplicate rows are dropped.
2. resale_price <- List_Price ("RM 87,888" -> 87888.0); a blank price drops
   the row.
3. A blank Model is recovered from Description: the words after the leading
   "YYYY" or "YYYY/YYYY"; the brand is the first word ("Land Rover" is two),
   the model is the brand plus the next word. Recovered ONLY when that brand
   already appears among the rows that do have a Model; otherwise the row
   stays dropped.
4. model_key <- Model cut at its first engine-size token ("\\d.\\d"):
   "Porsche Macan 2.0" -> "Porsche Macan". Used only for the within-model
   metric, never as a feature.
5. vehicle_age <- the row's own Listing_Year minus the leading (model) year
   of Description (ML batch 2; apps/ml/listing_year.py added the column:
   2022 for the Kaggle snapshot, 2026 for the hand-collected rows). A blank
   or unparseable Listing_Year drops the row - one reference year for the
   whole file made the Kaggle cars a year too old and the 2026 ones three
   years too young. recond = 1 when Description starts with "YYYY/YYYY"
   (made in the first year, first registered in Malaysia in the second: an
   imported used car), else 0.
6. mileage <- Milleage: a band "145 - 150K KM" takes its midpoint x 1000; a
   plain reading "118777 KM" is used as is.
7. brand_code <- a data-driven 1-5 price tier per brand (median resale price
   split into 5 quantile buckets, 1 = priciest), computed here over every
   row that reached this step.
8. engine_litres <- the Description token " d.d "; body_type <- the listing's
   body word via apps.ml.features.body_type_for_listing. A row missing either
   is dropped.
9. Numeric sanity: resale_price > 0, mileage >= 0, vehicle_age >= 0.

Output columns, in order: OUTPUT_COLUMNS below.
"""

import re
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand

from apps.ml.features import BODY_TYPES, body_type_for_listing
from apps.ml.listing_year import LISTING_YEAR_COLUMN

RAW_INPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "resale_car.csv"
OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "real_historical_pricing.csv"

OUTPUT_COLUMNS = [
    "vehicle_age", "mileage", "resale_price", "brand_code", "engine_litres", "body_type", "recond", "model_key",
]
NUM_TIERS = 5

_PRICE_PATTERN = re.compile(r"RM\s*([\d,]+)")
_MILEAGE_RANGE_PATTERN = re.compile(r"^\s*(\d+)\s*-\s*(\d+)K\s*KM\s*$", re.IGNORECASE)
_MILEAGE_PLAIN_PATTERN = re.compile(r"^\s*(\d+)\s*KM\s*$", re.IGNORECASE)
_LEADING_YEARS_PATTERN = re.compile(r"^(\d{4})(?:/(\d{4}))?")
_LEADING_YEARS_PREFIX = re.compile(r"^\d{4}(?:/\d{4})?\s+")
_ENGINE_LITRES_PATTERN = re.compile(r"\s(\d\.\d)\s")
_ENGINE_TOKEN = re.compile(r"\d\.\d")


def parse_price(raw_price) -> float:
    """'RM 87,888' -> 87888.0. NaN/unparseable -> float('nan')."""
    if pd.isna(raw_price):
        return float("nan")
    match = _PRICE_PATTERN.search(str(raw_price))
    if not match:
        return float("nan")
    return float(match.group(1).replace(",", ""))


def parse_mileage(raw_mileage) -> float:
    """'145 - 150K KM' -> 147500.0 (midpoint of the band, x1000).
    '118777 KM' -> 118777.0 (already an absolute reading - no range, no
    "K" multiplier). NaN/unparseable -> float('nan')."""
    if pd.isna(raw_mileage):
        return float("nan")
    text = str(raw_mileage)

    range_match = _MILEAGE_RANGE_PATTERN.match(text)
    if range_match:
        low, high = int(range_match.group(1)), int(range_match.group(2))
        return (low + high) / 2 * 1000

    plain_match = _MILEAGE_PLAIN_PATTERN.match(text)
    if plain_match:
        return float(plain_match.group(1))

    return float("nan")


def extract_year(description) -> int | None:
    """The leading year of Description: '2013/2014 BMW 528i ...' -> 2013
    (the first of a dual-year pair). None when Description doesn't start
    with a 4-digit year."""
    if pd.isna(description):
        return None
    match = _LEADING_YEARS_PATTERN.match(str(description))
    return int(match.group(1)) if match else None


def is_recond(description) -> int:
    """1 when Description starts with 'YYYY/YYYY' (made in one year, first
    registered in Malaysia in the next: an imported used car), else 0."""
    if pd.isna(description):
        return 0
    match = _LEADING_YEARS_PATTERN.match(str(description))
    return int(bool(match and match.group(2)))


def extract_brand(model) -> str | None:
    """First word of Model, e.g. 'BMW 528i' -> 'BMW', except
    'Land Rover ...', which is two words. None for a null/blank Model."""
    if pd.isna(model):
        return None
    words = str(model).split()
    if not words:
        return None
    if words[0] == "Land" and len(words) > 1 and words[1] == "Rover":
        return "Land Rover"
    return words[0]


def recover_model(description, known_brands) -> str | None:
    """A blank Model rebuilt from Description: the words after the leading
    year(s); brand = first word ('Land Rover' = two), model = brand + next
    word. None unless that brand is in `known_brands` (the brands of rows
    that do have a Model) - an unknown first word is never guessed to be a
    brand."""
    if pd.isna(description):
        return None
    words = _LEADING_YEARS_PREFIX.sub("", str(description)).split()
    if len(words) >= 3 and words[0] == "Land" and words[1] == "Rover":
        brand, model = "Land Rover", " ".join(words[:3])
    elif len(words) >= 2:
        brand, model = words[0], " ".join(words[:2])
    else:
        return None
    return model if brand in known_brands else None


def model_key(model) -> str:
    """Model cut at its first engine-size token: 'Porsche Macan 2.0' ->
    'Porsche Macan', 'Lexus ES250 2.5 Luxury' -> 'Lexus ES250'."""
    kept = []
    for word in str(model).split():
        if _ENGINE_TOKEN.fullmatch(word):
            break
        kept.append(word)
    return " ".join(kept)


def extract_engine_litres(description) -> float:
    """The ' d.d ' engine-size token of Description, e.g. ' 2.0 ' -> 2.0;
    NaN when there is none."""
    if pd.isna(description):
        return float("nan")
    match = _ENGINE_LITRES_PATTERN.search(str(description))
    return float(match.group(1)) if match else float("nan")


def compute_brand_tiers(median_price_by_brand: pd.Series) -> dict:
    """Data-driven 1-5 price tier per brand: split each brand's median
    resale_price into up to NUM_TIERS quantile buckets, tier 1 =
    highest-price bucket .. tier NUM_TIERS = lowest - the same
    "1 = priciest" convention generate_synthetic_ml_dataset.py uses for
    its assumed-MSRP brand_code.

    duplicates="drop" + labels=False (rather than fixed 1..NUM_TIERS
    labels) is deliberate: with too few distinct median prices to form
    NUM_TIERS clean quantile buckets (either because there are fewer
    than NUM_TIERS brands, or two brands tie on median price), qcut
    collapses to fewer effective buckets - a fixed-length labels list
    would then raise a length-mismatch error instead of degrading
    gracefully.
    """
    if len(median_price_by_brand) <= 1:
        # qcut can't form any quantile boundary from a single value (no
        # other brand to compare against) - there's nothing meaningful
        # to tier against, so the lone brand just gets tier 1.
        return {brand: 1 for brand in median_price_by_brand.index}

    codes = pd.qcut(median_price_by_brand, NUM_TIERS, labels=False, duplicates="drop")
    # qcut's raw codes are 0-based ascending by value (0 = lowest-price
    # bucket) - invert relative to however many effective buckets
    # resulted, so 1 always means "highest-price bucket" regardless.
    max_code = int(codes.max())
    tiers = max_code - codes + 1
    return {brand: int(tier) for brand, tier in tiers.items()}


def build_dataset(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Runs the full parse/clean/tier pipeline (see the module docstring for
    each step) and returns (final_df, stats). final_df has exactly
    OUTPUT_COLUMNS, in that order."""
    stats = {"raw_row_count": len(raw_df)}

    df = raw_df.drop_duplicates()
    stats["dropped_duplicates"] = len(raw_df) - len(df)

    df = df.copy()
    df["resale_price"] = df["List_Price"].apply(parse_price)
    before = len(df)
    df = df[df["resale_price"].notna()].copy()
    stats["dropped_null_price"] = before - len(df)

    known_brands = set(df["Model"].dropna().apply(extract_brand))
    blank_model = df["Model"].isna()
    df.loc[blank_model, "Model"] = df.loc[blank_model, "Description"].apply(
        lambda description: recover_model(description, known_brands)
    )
    still_blank = df["Model"].isna()
    stats["model_recovered"] = int((blank_model & ~still_blank).sum())
    stats["dropped_null_model"] = int(still_blank.sum())
    df = df[~still_blank].copy()

    df["model_key"] = df["Model"].apply(model_key)

    df["year"] = df["Description"].apply(extract_year)
    before = len(df)
    df = df[df["year"].notna()].copy()
    stats["dropped_unparseable_year"] = before - len(df)

    # ML batch 2: each row's own listing year (see apps/ml/listing_year.py) -
    # never one reference year for the whole file.
    if LISTING_YEAR_COLUMN not in df.columns:
        raise ValueError(
            f"The raw file has no {LISTING_YEAR_COLUMN} column - run `manage.py add_listing_year_column` first."
        )
    listing_year = pd.to_numeric(df[LISTING_YEAR_COLUMN], errors="coerce")
    listing_year = listing_year.where(listing_year.notna() & (listing_year % 1 == 0))
    before = len(df)
    keep = listing_year.notna()
    df = df[keep].copy()
    df["listing_year"] = listing_year[keep].astype(int)
    stats["dropped_no_listing_year"] = before - len(df)

    df["vehicle_age"] = df["listing_year"] - df["year"].astype(int)
    df["recond"] = df["Description"].apply(is_recond)

    df["brand"] = df["Model"].apply(extract_brand)
    df["mileage"] = df["Milleage"].apply(parse_mileage)

    median_price_by_brand = df.groupby("brand")["resale_price"].median()
    brand_tiers = compute_brand_tiers(median_price_by_brand)
    stats["brand_tiers"] = brand_tiers
    df["brand_code"] = df["brand"].map(brand_tiers)

    df["engine_litres"] = df["Description"].apply(extract_engine_litres)
    df["body_type"] = df["Description"].apply(body_type_for_listing)
    before = len(df)
    df = df[df["engine_litres"].notna() & df["body_type"].notna()].copy()
    stats["dropped_missing_engine_or_body"] = before - len(df)

    before = len(df)
    df = df[
        (df["resale_price"] > 0)
        & df["mileage"].notna()
        & (df["mileage"] >= 0)
        & (df["vehicle_age"] >= 0)
    ]
    stats["dropped_numeric_sanity"] = before - len(df)
    stats["final_row_count"] = len(df)
    stats["listing_years"] = {int(year): int(n) for year, n in sorted(df["listing_year"].value_counts().items())}
    stats["age_counts"] = {int(age): int(n) for age, n in sorted(df["vehicle_age"].value_counts().items())}
    stats["recond_count"] = int(df["recond"].sum())
    counts = df["body_type"].value_counts()
    stats["body_type_counts"] = {body: int(counts.get(body, 0)) for body in BODY_TYPES}

    final_df = df[OUTPUT_COLUMNS].reset_index(drop=True)
    return final_df, stats


def compare_with_catalog_tiers(brand_tiers: dict) -> list[str]:
    """One line per ACTIVE catalog brand comparing its Brand.tier_code with
    this build's tier (matched by name, case-insensitive). Read-only: nothing
    is written to Brand."""
    from apps.vehicles.models import Brand

    by_name = {name.lower(): tier for name, tier in brand_tiers.items()}
    lines = []
    for brand in Brand.objects.filter(is_active=True).order_by("name"):
        built = by_name.get(brand.name.lower())
        stored = (brand.tier_code or "").strip()
        if built is None:
            lines.append(f"  {brand.name}: catalog tier {stored or '(blank)'}; not in the training data")
        elif stored == str(built):
            lines.append(f"  {brand.name}: catalog tier {stored} = built tier {built}")
        else:
            lines.append(f"  {brand.name}: DIFFERS - catalog tier {stored or '(blank)'}, built tier {built}")
    return lines


class Command(BaseCommand):
    help = (
        "Build apps/ml/data/real_historical_pricing.csv (v2: engine size, body type, recond, model_key) from "
        "apps/ml/data/raw/resale_car.csv."
    )

    def handle(self, *args, **options):
        raw_df = pd.read_csv(RAW_INPUT_PATH)
        final_df, stats = build_dataset(raw_df)

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        final_df.to_csv(OUTPUT_PATH, index=False)

        out = self.stdout.write
        out(f"Raw rows read: {stats['raw_row_count']}")
        out(f"Dropped (exact duplicate): {stats['dropped_duplicates']}")
        out(f"Dropped (null List_Price): {stats['dropped_null_price']}")
        out(f"Model recovered from Description: {stats['model_recovered']}")
        out(f"Dropped (Model blank and not recoverable): {stats['dropped_null_model']}")
        out(f"Dropped (unparseable year): {stats['dropped_unparseable_year']}")
        out(f"Dropped (no listing year): {stats['dropped_no_listing_year']}")
        out(f"Dropped (no engine size or body type): {stats['dropped_missing_engine_or_body']}")
        out(f"Dropped (numeric sanity - price/mileage/age): {stats['dropped_numeric_sanity']}")
        out(self.style.SUCCESS(f"Final cleaned row count: {stats['final_row_count']}"))
        out("")
        out("Listing years used: " + ", ".join(f"{year} ({n} rows)" for year, n in stats["listing_years"].items()))
        out("Vehicle age (listing year - model year): "
            + ", ".join(f"{age}:{n}" for age, n in stats["age_counts"].items()))
        out(f"Recond (imported used) rows: {stats['recond_count']}")
        out("Body types: " + ", ".join(f"{body} {count}" for body, count in stats["body_type_counts"].items()))
        out("")
        out("Brand -> tier (1 = highest median resale price, 5 = lowest):")
        for brand, tier in sorted(stats["brand_tiers"].items(), key=lambda item: (item[1], item[0])):
            out(f"  {tier}  {brand}")
        out("")
        out("Catalog brands (Brand.tier_code, active) vs this build (read-only, nothing changed):")
        for line in compare_with_catalog_tiers(stats["brand_tiers"]):
            out(line)
        out("")
        out(self.style.SUCCESS(f"Wrote {stats['final_row_count']} rows to {OUTPUT_PATH}"))
