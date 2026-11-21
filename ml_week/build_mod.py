"""Builds apps/ml/data/real_historical_pricing.csv from a real Kaggle
used-car listing dataset - replaces the SYNTHETIC placeholder
(synthetic_historical_pricing.csv, left untouched - see
apps/ml/data/README.md and apps/ml/data/README_real_data.md) as the
dataset F012 is actually retrained against.

Reads ONLY apps/ml/data/raw/resale_car.csv (974 rows, mixed-brand real
used-car listings). apps/ml/data/raw/Malaysia_Final_CarList_Compiled.csv
(6,000 rows) is deliberately NOT read by this command: every one of its
rows is brand "Perodua", which doesn't offer GFV leasing - this
platform's actual target niche - so those 6,000 rows would swamp the
~974 mixed-brand rows without adding anything for the brands that
matter. This exclusion is a deliberate scope decision, not an oversight;
see apps/ml/data/README_real_data.md for the full accounting.

resale_car.csv's raw columns (confirmed by direct inspection, not
assumed): Description, Monthly_Installment, List_Price, Model, Milleage
(sic - that typo is the actual header), Gear_Type, Location. None of
these line up with training.py's REQUIRED_COLUMNS
(vehicle_age, mileage, resale_price, brand_code, msrp_proxy) directly -
this command derives all five:

- resale_price  <- List_Price, e.g. "RM 87,888" -> 87888.0
- mileage       <- Milleage. Confirmed by inspection: 963/974 rows are a
                   banded range "145 - 150K KM" (take the midpoint, x1000);
                   the remaining 11 are already a plain absolute reading
                   like "118777 KM" (no "K" multiplier, no range) - both
                   forms are real and both need parsing, not just the
                   range form.
- vehicle_age   <- the leading 4-digit year in Description (e.g.
                   "2013/2014 BMW 528i ..." -> 2013, "2017 Honda Civic
                   ..." -> 2017), subtracted from the MOST RECENT
                   extracted year anywhere in the dataset (2022 as of this
                   writing) - not wall-clock "today", so this
                   transformation reproduces byte-for-byte no matter when
                   it's re-run.
- brand_code    <- NOT one code per literal brand. A data-driven 1-5
                   price tier, mirroring generate_synthetic_ml_dataset's
                   brand_code convention (1 = highest assumed MSRP):
                   group by brand (the first word of Model, except
                   "Land Rover" which is two words), take each brand's
                   median resale_price, split into 5 quantile buckets,
                   tier 1 = highest-price bucket .. tier 5 = lowest.
- msrp_proxy    <- an honest approximation of "roughly what this specific
                   model would cost new" - NOT real MSRP data (resale_car.csv
                   never recorded each listing's original showroom price,
                   only its resale price). Group by the full Model string
                   (e.g. "BMW 528i", more specific than brand_code's
                   brand-level grouping): for a model with >= 3 listings,
                   use that model's MAXIMUM observed resale_price (a
                   higher resale price among the same model's listings
                   plausibly reflects a younger/lower-mileage example
                   closer to original value). For a model with fewer
                   listings (most are singletons), that model's own max
                   would just equal the row's own price - target leakage
                   in disguise - so it falls back to the brand-level
                   median instead (the same median brand_code's tiering
                   already computes). Computed at the same pipeline stage
                   as brand_code, before any train/test split exists (that
                   split happens later, inside train_and_evaluate) - the
                   same "no leakage across train/test" property brand_code
                   already has, not a new category of methodological
                   concern. At inference time (apps/depreciation/inference.py)
                   this proxy isn't needed at all: the vehicle's own real,
                   catalog-stored msrp is used directly instead.

Rows are dropped (never guessed/imputed) when: List_Price is null (5
rows), Model is null (82 rows - dropped rather than trying to recover a
brand from Description), the leading year can't be parsed (0 rows in
practice, checked defensively anyway), or after all parsing,
resale_price <= 0 / mileage < 0 / vehicle_age < 0 (0 rows in practice for
this dataset). See build_dataset()'s returned stats dict for the actual
counts on a given run, printed by this command.
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
BaseCommand=object

RAW_INPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "resale_car.csv"
OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "real_historical_pricing.csv"

OUTPUT_COLUMNS = ["vehicle_age", "mileage", "resale_price", "brand_code", "msrp_proxy"]
NUM_TIERS = 5
MIN_LISTINGS_FOR_MODEL_PROXY = 3

_PRICE_PATTERN = re.compile(r"RM\s*([\d,]+)")
_MILEAGE_RANGE_PATTERN = re.compile(r"^\s*(\d+)\s*-\s*(\d+)K\s*KM\s*$", re.IGNORECASE)
_MILEAGE_PLAIN_PATTERN = re.compile(r"^\s*(\d+)\s*KM\s*$", re.IGNORECASE)
_YEAR_PATTERN = re.compile(r"(\d{4})")


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
    """First 4-digit token in Description, e.g. '2013/2014 BMW 528i ...'
    -> 2013 (the first of a dual-year pair). None if no 4-digit year
    appears at all."""
    if pd.isna(description):
        return None
    match = _YEAR_PATTERN.search(str(description))
    return int(match.group(1)) if match else None


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


def compute_msrp_proxy(
    model: pd.Series, brand: pd.Series, resale_price: pd.Series, median_price_by_brand: pd.Series
) -> pd.Series:
    """Per-row 'roughly what this specific model would cost new' proxy -
    an honest approximation from real data, not invented, and not real
    MSRP (see this file's module docstring for the full reasoning).
    model / brand / resale_price must share the same index (e.g. three
    columns read from the same working dataframe).

    Model with >= MIN_LISTINGS_FOR_MODEL_PROXY listings: that model's
    maximum observed resale_price, EXCLUDING the row's own price
    (leave-one-out) - naively including it means the single row that
    happens to be its model's own top listing gets a proxy exactly equal
    to its own target value, real (if narrow) leakage caught by direct
    inspection of the built dataset: 109/888 rows had msrp_proxy ==
    resale_price before this fix (see
    apps/ml/data/README_real_data.md). Excluding self, a tied maximum
    (>1 row sharing the top price) still correctly resolves to that same
    top price for every row in the tie, since excluding just one of them
    leaves another at that price. Fewer than MIN_LISTINGS_FOR_MODEL_PROXY
    listings (most are singletons): even leave-one-out isn't enough
    (a 2-listing model's own leave-one-out max is just the OTHER
    listing's exact price - still leakage-adjacent for a group this
    small) - falls back to the brand-level median instead (reusing the
    same median compute_brand_tiers uses).
    """
    working = pd.DataFrame({"model": model, "brand": brand, "resale_price": resale_price})
    model_counts = working["model"].map(working["model"].value_counts())
    max_price_excluding_self = working.groupby("model")["resale_price"].transform(_max_excluding_self)
    brand_median = working["brand"].map(median_price_by_brand)
    return max_price_excluding_self.where(model_counts >= MIN_LISTINGS_FOR_MODEL_PROXY, brand_median)


def _max_excluding_self(group: pd.Series) -> pd.Series:
    """Per-element 'max of this group, excluding this element's own
    value' - a leave-one-out max. A tie for the top value resolves to
    that same top value for every tied row (excluding just one still
    leaves another row at the top)."""
    values = group.to_numpy(dtype=float)
    if len(values) <= 1:
        return group.copy()
    top1 = values.max()
    count_top1 = int((values == top1).sum())
    remaining = values[values != top1]
    top2 = remaining.max() if len(remaining) > 0 else top1
    result = np.where((values != top1) | (count_top1 > 1), top1, top2)
    return pd.Series(result, index=group.index)


def build_dataset(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Runs the full parse/clean/tier pipeline on resale_car.csv's raw
    columns and returns (final_df, stats). final_df has exactly
    OUTPUT_COLUMNS, in that order. stats records how many rows were
    dropped at each step, keyed the same way this command prints them.
    """
    stats = {"raw_row_count": len(raw_df)}

    df = raw_df.copy()
    df["resale_price"] = df["List_Price"].apply(parse_price)
    before = len(df)
    df = df[df["resale_price"].notna()]
    stats["dropped_null_price"] = before - len(df)

    before = len(df)
    df = df[df["Model"].notna()]
    stats["dropped_null_model"] = before - len(df)

    df["year"] = df["Description"].apply(extract_year)
    before = len(df)
    df = df[df["year"].notna()]
    stats["dropped_unparseable_year"] = before - len(df)

    reference_year = int(df["year"].max())
    stats["reference_year"] = reference_year
    df["vehicle_age"] = reference_year - df["year"]

    df["brand"] = df["Model"].apply(extract_brand)
    df["mileage"] = df["Milleage"].apply(parse_mileage)

    median_price_by_brand = df.groupby("brand")["resale_price"].median()
    brand_tiers = compute_brand_tiers(median_price_by_brand)
    stats["brand_tiers"] = brand_tiers
    df["brand_code"] = df["brand"].map(brand_tiers)

    df["msrp_proxy"] = compute_msrp_proxy(df["Model"], df["brand"], df["resale_price"], median_price_by_brand)
    model_counts = df["Model"].map(df["Model"].value_counts())
    stats["msrp_proxy_model_level_count"] = int((model_counts >= MIN_LISTINGS_FOR_MODEL_PROXY).sum())
    stats["msrp_proxy_brand_fallback_count"] = int((model_counts < MIN_LISTINGS_FOR_MODEL_PROXY).sum())

    before = len(df)
    df = df[
        df["resale_price"].notna()
        & (df["resale_price"] > 0)
        & df["mileage"].notna()
        & (df["mileage"] >= 0)
        & df["vehicle_age"].notna()
        & (df["vehicle_age"] >= 0)
        & df["msrp_proxy"].notna()
        & (df["msrp_proxy"] > 0)
    ]
    stats["dropped_numeric_sanity"] = before - len(df)
    stats["final_row_count"] = len(df)

    final_df = df[OUTPUT_COLUMNS].reset_index(drop=True)
    return final_df, stats


class Command(BaseCommand):
    help = (
        "Build apps/ml/data/real_historical_pricing.csv from "
        "apps/ml/data/raw/resale_car.csv (see this file's module "
        "docstring for why the other raw CSV is deliberately excluded)."
    )

    def handle(self, *args, **options):
        raw_df = pd.read_csv(RAW_INPUT_PATH)
        final_df, stats = build_dataset(raw_df)

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        final_df.to_csv(OUTPUT_PATH, index=False)

        self.stdout.write(f"Raw rows read: {stats['raw_row_count']}")
        self.stdout.write(f"Dropped (null List_Price): {stats['dropped_null_price']}")
        self.stdout.write(f"Dropped (null Model): {stats['dropped_null_model']}")
        self.stdout.write(f"Dropped (unparseable year): {stats['dropped_unparseable_year']}")
        self.stdout.write(f"Reference year (max extracted year): {stats['reference_year']}")
        self.stdout.write(
            f"Dropped (numeric sanity - price/mileage/age/msrp_proxy): {stats['dropped_numeric_sanity']}"
        )
        self.stdout.write(self.style.SUCCESS(f"Final cleaned row count: {stats['final_row_count']}"))
        self.stdout.write("")
        self.stdout.write(
            f"msrp_proxy: {stats['msrp_proxy_model_level_count']} rows used their model's own max price "
            f"(>= {MIN_LISTINGS_FOR_MODEL_PROXY} listings), "
            f"{stats['msrp_proxy_brand_fallback_count']} fell back to the brand median"
        )
        self.stdout.write("")
        self.stdout.write("Brand -> tier (1 = highest median resale price, 5 = lowest):")
        for brand, tier in sorted(stats["brand_tiers"].items(), key=lambda item: item[1]):
            self.stdout.write(f"  {tier}  {brand}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Wrote {stats['final_row_count']} rows to {OUTPUT_PATH}"))
