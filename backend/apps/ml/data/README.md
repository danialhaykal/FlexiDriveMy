# SYNTHETIC PLACEHOLDER DATA - NOT REAL TRANSACTIONS

`synthetic_historical_pricing.csv` is generated data, not real historical
used-car pricing. It exists solely so F012's training pipeline (and its
tests) can be developed and exercised end-to-end without a real dataset.

**This must be replaced with real historical used-car transaction data
before any model trained on it is trusted for actual depreciation
predictions.**

## How it was generated

`python manage.py generate_synthetic_ml_dataset` (see
`apps/ml/management/commands/generate_synthetic_ml_dataset.py`). Fixed
random seed (42), so it's reproducible byte-for-byte.

For 5 synthetic "brands" (`brand_code` 1-5, each with an assumed new-car
MSRP), it generates rows with:

- `vehicle_age`: uniform 0-10 years
- `mileage`: cumulative odometer reading correlated with age
  (`age * random_annual_rate + noise`) - **not** an annual rate; see the
  note in `apps/ml/training.py` about the mismatch between this and
  the project spec's "Annual Mileage" inference feature name.
- `resale_price`: `base_msrp * 0.85^age * mileage_penalty * noise`
  (~15%/year compounding depreciation, a mileage penalty, and ±3% price
  noise) - a deliberately learnable pattern so RandomForest/
  GradientBoosting can reach the R² ≥ 0.80 deployment threshold.

## Known deviation from the project spec's feature vector

the project spec's ML section specifies 5 features: `[Vehicle Age, Annual
Mileage, MSRP, Brand Tier Code, Engine Capacity/kW]`. This SYNTHETIC
dataset only carries 4 columns - no MSRP or engine capacity per row - so
it only ever exercised the 3-feature (`vehicle_age`, `mileage`,
`brand_code`) pipeline that predated Sprint 9.

**Cosmetic correction - this paragraph was stale**: Sprint 9 added a 4th
feature, `msrp_proxy` (see `apps/ml/data/README_real_data.md`), to the
REAL dataset and the live training pipeline
(`apps/ml/training.py::FEATURE_COLUMNS`) - the pipeline itself has used 4
features, not 3, since then. This file's own synthetic dataset was
deliberately left unmodified as historical bootstrap-phase documentation
(predates Sprint 9 entirely) rather than regenerated, so it's correct
that IT still only has 4 raw columns / 3 usable features - the paragraph
above was just describing that historical fact as if it were still the
CURRENT pipeline's limitation, which it no longer is.

**ML batch 1 (15 Oct 2026):** the live pipeline no longer uses
`msrp_proxy`. It predicts the log resale price from vehicle age, mileage,
brand tier, engine size (litres), body type and recond - the columns are
defined once in `apps/ml/features.py`; see
`apps/ml/data/README_real_data.md` for the dataset and the two metrics.
