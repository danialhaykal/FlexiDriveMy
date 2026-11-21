# Real historical pricing data for F012

`real_historical_pricing.csv` replaces `synthetic_historical_pricing.csv`
as the dataset F012's model is actually retrained against.
`synthetic_historical_pricing.csv` and its generator are left in place,
unmodified - the report's methodology section still references that
earlier bootstrap phase.

Since ML batch 1 (15 Oct 2026) the model predicts the **resale price
itself, on a log scale**, from the car's own attributes, and every run
reports **two** R² values. The sections below describe that version; the
history of the earlier targets is kept at the end because the report
discusses it.

## Source dataset

**Used:** ["Malaysia Resale Carlist"](https://www.kaggle.com/datasets/tanshihjen/malaysia-resale-carlist),
Kaggle user `tanshihjen`. Downloaded 2026-09-04 as `resale_car.csv`
(1,004 rows). This is real used-car-for-financing listing data, not
synthetic. (Earlier versions of this file said 974 rows; the file on
disk has 1,004, confirmed intact during the ML week review.)

**License:** stated on the dataset's Kaggle page, but that page is
JavaScript-rendered and could not be confirmed by automated fetch for
this document (the same category of limitation the FYP1 report already
cites as a reason live scraping was rejected in favour of static,
admin-managed data). Please note the license shown on the page itself
(you were logged in when you downloaded it) and fill it in here before
this goes in the report - do not state a license here that hasn't been
read directly off the page.

**Downloaded but deliberately not used:**
["Malaysia Car List Price"](https://www.kaggle.com/datasets/norazrinnatasha/malaysia-car-list-price),
Kaggle user `norazrinnatasha` (`Malaysia_Final_CarList_Compiled.csv`,
6,000 rows). Every row in this file is brand `"Perodua"`. Perodua
doesn't offer GFV leasing - this platform's actual target niche - so
those 6,000 single-brand rows would do nothing for the brands that
matter and would badly skew a combined dataset. The file is still present
in `apps/ml/data/raw/` for reference; it's never read by
`build_real_ml_dataset`.

## Columns (build v2)

`real_historical_pricing.csv` has, in this order:

| Column | From | How |
|---|---|---|
| `vehicle_age` | `Listing_Year`, `Description` | the row's own **listing year** minus its leading (model) year ("2013/2014 ..." -> 2013); see "Listing year" below. Not wall-clock "today", so a re-run reproduces the file byte-for-byte |
| `mileage` | `Milleage` (sic) | a band "145 - 150K KM" -> its midpoint x 1,000 (147,500); the 11 plain readings like "118777 KM" are used as is |
| `resale_price` | `List_Price` | "RM 87,888" -> 87888.0. An asking price, not a sale price |
| `brand_code` | brand | a data-driven 1-5 price tier: each brand's median resale price split into 5 quantile buckets, 1 = priciest (table below). Brand = first word of `Model`, except "Land Rover" |
| `engine_litres` | `Description` | the " d.d " engine-size token, e.g. " 2.0 " -> 2.0 |
| `body_type` | `Description` | the listing's body word via `apps/ml/features.py::body_type_for_listing`: Sedan, Hatchback, SUV, Crossover (-> suv), MPV, Van (-> mpv), Pickup Truck (-> pickup), Coupe, Convertible (-> coupe), Wagon (-> hatchback) |
| `recond` | `Description` | 1 when it starts with "YYYY/YYYY" (made in the first year, first registered in Malaysia in the second: an imported used car), else 0 |
| `model_key` | `Model` | the model cut at its first engine-size token: "Porsche Macan 2.0" -> "Porsche Macan", "Lexus ES250 2.5 Luxury" -> "Lexus ES250". **Not a feature** - used only for the within-model metric |

`msrp_proxy` is no longer built (see "Why the target changed").

**`Monthly_Installment` must never be a feature.** It is always exactly
1.2965% of `List_Price` (correlation 0.99999997): the price in disguise,
so using it would fake a near-perfect R². `apps/ml/tests/test_features.py`
fails if it (or `msrp_proxy`) ever appears in `FEATURE_COLUMNS`.
`Gear_Type` and `Location` are not used (no gain, or a loss, in the ML
week experiments).

The model's feature columns are defined once, in `apps/ml/features.py`
(`FEATURE_COLUMNS`): `vehicle_age, mileage, brand_code, engine_litres,
recond` and one 0/1 column per body type (`body_sedan, body_hatchback,
body_suv, body_mpv, body_pickup, body_coupe`). The build, training, the
upload validation and inference all import it.

## Listing year (ML batch 2)

A car's age is the year it was **listed** minus its model year. The raw file
mixes two snapshots:

- the 974 Kaggle rows, listed around **2022** (the newest model year among
  them is 2022);
- 30 rows hand-collected from Carlist in **October 2026** (they include 2023
  cars). They are the last 30 rows of the file and the only ones with a blank
  `Monthly_Installment`.

Until ML batch 2 the build aged every row against **one** reference year, the
newest model year in the whole file. The 2023 cars in the hand-collected rows
made that 2023, so every Kaggle car was a year too old and every
hand-collected car three years too young; the only "age 0" rows were 3-year-old
Macans and an ES with 22,000-62,000 km - exactly the anchor the depreciation
curve divides by.

`python manage.py add_listing_year_column` (one-off, `apps/ml/listing_year.py`)
added a `Listing_Year` column to `resale_car.csv` in place: 2022 for the Kaggle
rows, 2026 for the hand-collected ones. It first asserts the 30 blank-instalment
rows are exactly the last 30, and proves every old cell is byte-identical
(removing the column gives back the original file). **Rows added later must
carry their own listing year**: the build drops a row with a blank or
unparseable one ("Dropped (no listing year)") and refuses a file without the
column.

The Kaggle snapshot reflects the **2022 market, a period of high used-car
prices** (supply shortages after the pandemic), so the retention it teaches may
be a little optimistic compared with a normal year.

Ages after the fix: 0:14, 1:35, 2:42, 3:92, 4:119, 5:133, 6:135, 7:162, 8:127,
9:101, 10:15, 11:3, 12:3, 14:2.

## Row accounting (build v2, listing years)

| Step | Rows |
|---|---|
| Raw rows read (`resale_car.csv`) | 1,004 |
| Dropped - exact duplicate | 1 |
| Dropped - blank `List_Price` | 5 |
| Blank `Model` recovered from `Description` (brand already known from other rows) | 66 recovered |
| Dropped - blank `Model`, brand not known (never guessed) | 14 |
| Dropped - leading year unparseable | 0 |
| Dropped - no listing year | 0 |
| Dropped - no engine size or body type in the listing | 1 |
| Dropped - numeric sanity (price <= 0, mileage < 0, age < 0) | 0 |
| **Final row count** | **983** (954 listed in 2022, 29 in 2026) |

Recond rows: 98. Body types: sedan 349, suv 314, mpv 119, hatchback 104,
pickup 49, coupe 48. The 66 recovered rows matter: many are premium
(S400L, XC40, Range Rover) and were all dropped before.

## Brand -> tier table

| Tier | Brands |
|---|---|
| 1 (highest median resale price) | Land Rover, Lexus, MINI, Porsche, Toyota |
| 2 | BMW, Ford, Mercedes-Benz, Mitsubishi, Volvo |
| 3 | Audi, Honda, Mazda, Suzuki, Volkswagen |
| 4 | Haval, Hyundai, Isuzu, Nissan, Subaru |
| 5 (lowest median resale price) | Kia, Perodua, Peugeot, Proton, Ssangyong |

Unchanged by the v2 build (the same 25 brands in the same tiers). The
build prints this table and compares it with `Brand.tier_code` for every
active catalog brand (read-only): BMW 2, Lexus 1, Mercedes-Benz 2,
Porsche 1, Toyota 1, Volvo 2 - all equal.

Worth naming plainly in the report:

- **Toyota in tier 1** alongside Porsche/Lexus is data-driven, not an
  error: this sample's Toyota listings skew to Alphard/Vellfire/Harrier.
  The tier is "price of the cars listed", not brand prestige.
- **Small samples for some premium brands** (Porsche, Land Rover, Volvo
  in single or low double digits), so their tiers are more sensitive to
  individual listings.
- **Catalog coverage**: BMW 3 Series, Mercedes C-Class, Toyota Alphard,
  Porsche Macan and Lexus ES have between about 17 and 32 listings each;
  Volvo XC60/XC90 a handful; **Porsche 911 and every electric car: none**.
  Young listings are few (14 at age 0, 35 at age 1) and mostly expensive
  models (Alphard, Land Cruiser, Range Rover).

## The model and its two metrics

- **Target:** `log(resale_price)`. Features: `feature_frame(df)` (the
  columns above). Same 80/20 split (`random_state=42`), the same
  `GridSearchCV` grids and cv=3 as before. R² and MAE are on the log
  scale; a log MAE is a relative error, so the ML page shows it as
  "typical error ≈ X% of price" with X = (e^MAE - 1) x 100.
- **R² (held-out, log price)** is what the unchanged 0.80 deployment gate
  checks.
- **Depreciation-shape R² (within the same model)**: on the same held-out
  rows, keep those whose `model_key` has at least 2 held-out rows,
  subtract each key's own mean from both the actual and the predicted log
  price, and take R² of the two. It measures how well the model explains
  price differences *between listings of the same car model* - the part
  the depreciation curve uses. It is recorded and shown, never gating.
  Null when the upload has no `model_key` or fewer than 10 rows qualify.

Why both: most of the held-out R² comes from telling a Porsche from a
Perodua (price level). The app only uses the curve's shape (value at
month m relative to month 0, scaled to the car's real catalog price), so
the within-model number is the honest measure of what buyers see.

### Three candidates (ML batch 2)

Every run trains and compares:

- **Random Forest** and **Gradient Boosting** (the FYP1 report's two, with
  their unchanged grid searches);
- a **log-linear (hedonic) model** (`apps/ml/log_linear.py`): log price =
  a level per car model (`model_key`) + age + age² + age x brand tier +
  km/10,000 + engine size + recond + tier + body, fitted by ridge regression
  with the alpha chosen by `RidgeCV` on the training split. It is the standard
  econometric model for car depreciation.

All three are scored on the same held-out rows; the highest R² wins (the
0.80 gate and the same-target gate unchanged), and the winner must also pass
the **curve check** (`apps/ml/curve_check.py`) to be deploy-eligible: for every
catalog car the forecast covers, at the standard band's representative mileage
(12,500 km a year since Run 3 fix batch 6; run 10 was checked at 15,000), read at whole years
0..5, the value must not rise from one year to the next (beyond 1% on the log
scale), must keep at most 95% after 12 months, and must keep 20%-75% after 60
months. Those limits are sanity limits that catch a broken curve, not market
claims.

Why a third candidate: young listings are mostly expensive models, so a tree
cannot tell "young" from "pricey model" and flattens years 1-2 (run 9 kept
100% of the price for about 10 months, and 34 months for the Alphard). Giving
each car model its own price level separates model mix from age, so one
age/mileage effect is learned across models. Its limit: every catalog car gets
nearly the same shape (about 12% a year); the model-specific part is a level,
not a slope.

### Run 10 (ML batch 2, 15 Oct 2026; sklearn 1.9.0)

| Model | R² (log price) | MAE (log) | Typical error | Depreciation-shape R² | Best params |
|---|---|---|---|---|---|
| Random Forest | 0.8603 | 0.2012 | ≈ 22.3% of price | 0.5132 | max_depth 16, n_estimators 100 |
| Gradient Boosting | 0.8776 | 0.2005 | ≈ 22.2% of price | 0.5871 | learning_rate 0.1, max_depth 3, n_estimators 100 |
| **Log-linear (hedonic)** | **0.9124** | **0.1473** | **≈ 15.9% of price** | **0.7199** | alpha ≈ 0.3857 |

The log-linear model wins on both R² values, passes the curve check and the
run is **deploy-eligible, not deployed** (deployment stays a separate admin
action on the ML page). Random Forest and Gradient Boosting would both fail
the curve check (RF's value rises in year 1; GB keeps over 95% after 12 months
for the BMW, Lexus and C200). Run 10's curve, 15,000 km a year, at months
12/24/36/48/60: tier-2 cars (BMW 320i, C200, XC60, XC90) 88.5/77.8/67.9/58.8/50.7%;
tier-1 cars (Lexus ES, Macan, 911, Alphard) 88.2/77.3/67.2/58.1/49.9%. For
comparison, the residual-anchored fallback for the BMW was 77/61/50/42/35% (the
standard band before Run 3 fix batch 6; now 78.07/62.07/51.79/43.79/36.79%).

Run 3 fix batch 6 (no retrain): the bands were recalibrated, so the standard band
is now read at 12,500 km a year (was 15,000), and every year's total mileage is
capped at the highest mileage this training data has at that age (ages 0-5:
62,500 / 92,500 / 107,500 / 117,500 / 147,500 / 147,500 km) - the model is never
read beyond what it has seen. Only the very high band (30,000 km a year) reaches
the cap, at year 5; the TCO tab then says "The forecast is capped at the mileage
the model has seen."

Within one model, asking prices still spread by about ±11% for the same year
and recond status (dealer pricing and condition we cannot see), and the best
depreciation-shape R² possible from age alone is about 0.86.

Run 9 (ML batch 1: GB R² 0.8789, depreciation-shape 0.6489) was trained on
the mis-aged data and is retired ("Retired: trained on mis-aged data (one
reference year for 2022 and 2026 listings); superseded by the listing-year
rebuild (ML batch 2).", audit row #168).

### What inference does with it

`apps/depreciation/inference.py` reads the model at **whole years** 0..5
(the data records age in whole years): age = y, mileage = annual km x y,
`brand_code` from `Brand.tier_code`, `engine_litres` = `engine_capacity_cc`
/ 1000 rounded to one decimal, `recond` = 0 (catalog cars are new), body
one-hots from `body_type_for_segment` (crossover -> suv, van -> mpv). The
log-linear model is called with no model key (its car-model level would cancel
anyway). Month m uses f interpolated linearly between its two whole years
(weight (m - 12y) / 12; month 60 is year 5). The curve is
msrp x exp(f(m) - f(0)), so month 0 is the car's own price by construction,
then `_clamp_resale_curve` keeps it at or below msrp and non-increasing.

**Electric cars are not covered**: the training data has none (and the
engine-size feature needs a displacement), so a BEV - or any car with no
engine cc - always gets the labelled fallback curve: "The machine-learning
forecast does not cover electric cars yet: the training data has none."
A brand with no tier also falls back, and a body segment with no body type
falls back with "The machine-learning forecast does not cover this body type
yet." - never guessed.

## Why the target changed (history)

1. **Sprint 8**: age, mileage and brand tier on the raw resale price:
   R² 0.68/0.69 (rf/gb). Below the gate.
2. **Sprint 9**: added `msrp_proxy` (the highest other listing of the same
   model, else the brand median, leave-one-out after a found leak): raw
   price R² 0.8920/0.8909, deployed as run 5. But `msrp_proxy` is a *used*
   price, while inference put the real *new* price in the same slot - the
   model extrapolated (values above the car's price, rising with age).
3. **QA audit C8**: target changed to resale_price / msrp_proxy (clipped at
   1.0) so the scale mismatch cancels: R² 0.61/0.64 (runs 6 and 8). Below
   the gate. The ML week then found why: the newest listing of a model is
   on average **4.3 years old**, so that "retention ratio" measured "this
   car vs a 4-year-old example", not "vs new"; 14.5% of rows sat above
   their proxy. The best honest result on that target, with every listing
   feature added, was about 0.77.
4. **ML batch 1 (option c)**: predict the resale price itself, on a log
   scale, from attributes only, and drop `msrp_proxy` - as the FYP1 report
   describes ("predicted vehicle residual market values"; UC012 columns
   Age, Mileage, Resale Price, Brand Code). The mismatch disappears at its
   root because no feature stands in for a price. Run 5 was retired
   (`retire_incompatible_production_model`, audit rows #164-#167), and the
   gate that compares a candidate with production now compares only R²
   measured on the same target.
5. **ML batch 2**: per-row listing year (the ages were wrong - see "Listing
   year"), the log-linear (hedonic) third candidate, whole-year anchors with
   months interpolated, and the curve check before deploy. Run 9 retired;
   run 10's log-linear model wins (R² 0.9124, depreciation-shape 0.7199).

The earlier L19 note still applies in a smaller form: `brand_code` (median
resale price per brand) is computed over the whole file before the split,
a small leak through the tier assignment. Computing tiers per fold would
remove it; it is left as a documented limitation.

## Schema note: synthetic_historical_pricing.csv

`synthetic_historical_pricing.csv` and its generator predate both
`msrp_proxy` and the v2 columns and are deliberately **not** regenerated -
they document the bootstrap phase. Feeding that file through
`load_and_validate_csv` raises "Missing required columns" (see
`test_legacy_synthetic_dataset_is_incompatible_with_current_schema`). An
old 5-column `msrp_proxy` CSV is refused the same way.

## Reproducing this file

```
python manage.py add_listing_year_column   # one-off; already applied, a re-run refuses
python manage.py build_real_ml_dataset
python manage.py run_real_retrain          # records a run; never deploys
```

Deterministic given a fixed `resale_car.csv` - there's no random
sampling anywhere in the build, so a re-run reproduces
`real_historical_pricing.csv` byte-for-byte.
