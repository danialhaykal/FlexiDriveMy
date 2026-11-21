# FYP2 report: where the built system differs from the FYP1 report

A plain list to lift into the FYP2 report. Each item says what the FYP1 report
says, what the built system does, why, and where to find it in the code. Paths
are relative to the repository root. Last checked against the code on
19 October 2026 (Run 2 fix batch 2).

---

## 1. Background tasks: Celery + Redis

- **Report says:** background work (ML retraining, PDF compilation, the spec
  fetch) runs as Celery tasks on a Redis broker.
- **Built system does:** every task *is* a real Celery task (`@shared_task`,
  called with `.delay()`), but the development setup runs them **inline** in
  the web request: `CELERY_TASK_ALWAYS_EAGER=True` and no Redis server.
- **Why:** no Redis on the development machine; inline execution keeps the
  endpoints and the test suite working with no extra services. Run 1 batch 2
  capped the PDF chart (400,000 bytes, 5,000 elements) so an inline PDF can no
  longer hold a request for long or slow other users.
- **Both modes work (Run 1 batch 5 closed the gap):** with eager mode on, the
  PDF streams back in the same response, as before. With eager mode off, `POST
  /api/exports/pdf/` answers **202** `{job_id, status}`; the page polls `GET
  /api/exports/pdf/{job_id}/` every 2 seconds (for up to 60 seconds) and then
  fetches `GET /api/exports/pdf/{job_id}/download/`. Both are owner-only
  (another user's job is a 404). ML training and the spec fetch already
  reported their status for their pages to poll.
- **To demo it with Redis and a worker** (three terminals, from the repository
  root):
  1. Start Redis:
     `docker run -d --name flexidrivemy-redis -p 6379:6379 redis:7`
     (afterwards `docker stop flexidrivemy-redis` / `docker start flexidrivemy-redis`)
  2. Start a worker from `backend/`, with eager mode off in its environment:
     `$env:CELERY_TASK_ALWAYS_EAGER="False"; $env:REDIS_URL="redis://localhost:6379/0"; celery -A config worker --loglevel=info --pool=solo`
     (`--pool=solo` is needed on Windows; drop it on Linux/macOS, and use
     `CELERY_TASK_ALWAYS_EAGER=False REDIS_URL=redis://localhost:6379/0 celery -A config worker --loglevel=info` there.)
  3. Start the API from `backend/` with the same two settings:
     `$env:CELERY_TASK_ALWAYS_EAGER="False"; $env:REDIS_URL="redis://localhost:6379/0"; python manage.py runserver`
     (or put both lines in `backend/.env`), and the frontend as usual
     (`npm run dev` in `frontend/`).
  Export a PDF: the worker's terminal shows the task, and the page downloads
  the file when it is ready. Put the two settings back (or remove them) to
  return to inline mode.
- **Where in code:** `backend/config/settings.py` (Celery section),
  `backend/config/celery.py`, `backend/apps/exports/tasks.py`,
  `backend/apps/exports/views.py`, `backend/apps/ml/tasks.py`,
  `backend/apps/vehicles/tasks.py`.

## 2. Residual values: "verified manufacturer residual matrices" (UC005 Rule 2)

- **Report says:** GFV balloons come from verified manufacturer residual
  matrices.
- **Built system does:** a **labelled planning-estimate residual estimator**:
  a baseline by tenure and mileage band, plus brand and powertrain adjustment
  points, clamped to a safe range. An admin can key an **override** row for a
  brand, tenure and band when a real lender figure is known; that row is then
  used exactly. Every value carries a source note saying it is a planning
  assumption, and the GFV card shows the basis ("Estimate: 50% baseline for 36
  months / standard mileage, +6 points Toyota, 0 points petrol").
- **Why:** manufacturers and lenders do not publish their GFV residual tables;
  a "verified" claim could not be backed. The estimator prices any car added
  later with nothing keyed per car, and is honest about being an estimate.
- **Where in code:** `backend/apps/policy/residuals.py`
  (`resolve_residual_ratio`), `ResidualBaseline` / `ResidualAdjustment` /
  `ResidualValueMatrix` in `backend/apps/policy/models.py`, seeds in
  `backend/apps/policy/migrations/0018_*`.

## 3. Spec Draft and the no-scraping position

- **Report says:** live web scraping was evaluated and rejected (JS-rendered
  pages, anti-bot protection); all catalog data is admin-managed.
- **Built system does:** keeps that position for the catalog and the ML data.
  "Fetch Spec Draft" is an **admin-requested, human-approved** lookup: the
  admin picks one exact variant on paultan.org's Car Buyer's Guide, the page's
  specs are staged in a draft row, and nothing reaches the live catalog until
  the admin saves the normal Add Vehicle form (same validation and audit log
  as manual entry). It is one page per click, never a scheduled or bulk crawl.
  A failed fetch ends in a "failed" status with a plain message and an audit
  row (Run 1 batch 4).
- **Why:** it saves typing for a stable editorial source while keeping a human
  in charge of every catalog record - consistent with the report's reasons.
- **Where in code:** `backend/apps/vehicles/paultan_research.py`,
  `backend/apps/vehicles/tasks.py`, `VehicleSpecDraft` in
  `backend/apps/vehicles/models.py`.

## 4. Hire Purchase rate and early settlement

- **Report says:** Hire Purchase Act 1967 flat-rate interest.
- **Built system does:** instalments are still built from the dealer's
  **flat rate** (shown as "2.80% flat p.a."), and the **effective
  (reducing-balance) rate** is shown beside it. Every loan balance - early
  settlement, the negative-equity chart, the total-loss sandbox, TCO beyond 60
  months - uses the **reducing-balance** amount to settle, with no
  early-settlement penalty and no Rule of 78.
- **Why:** the Hire-Purchase (Amendment) Act 2026 moves new loans to
  effective-rate disclosure (by 31 March 2027) and reducing-balance
  settlement. The report's "Hire Purchase Act 1967 flat-rate" wording needs
  that update.
- **Where in code:** `backend/apps/comparisons/formulas.py`
  (`effective_annual_rate`, `settlement_balance`),
  `backend/apps/depreciation/services.py` (`build_early_settlement`).

## 5. Running costs (road tax, insurance, maintenance)

- **Report says:** road tax, insurance and maintenance are part of the TCO.
- **Built system does:** one engine derives all three from each car's own
  fields:
  - road tax from the **JPJ cc tables by registration class** (saloon /
    non-saloon; petrol and diesel use the same tables), and the **EV kW
    table** (from 1 Jan 2026, not split by class);
  - insurance as a **percentage of price** by powertrain, less the buyer's
    **No-Claim Discount** from their profile (owner costs only - never a
    subscription fee);
  - maintenance as a **percentage of price with a floor and a cap**.
  Insurance and maintenance percentages, the floor and the cap are labelled
  **planning assumptions**, not tariffs.
- **Maintenance does not change with the mileage band** (a planning assumption, not a defect): it is a
  percentage of the car's price a year with a floor and a cap (RM 8,000 a year today), the same for every
  band. Real servicing cost does rise with distance; per-km servicing data for these cars is not available,
  so the estimate is kept price-based and said so on the Total cost tab (FX-2).
- **Why:** insurers set their own rates since the 2017 liberalisation, and no
  per-car cost data exists to key in; deriving from the car's specs prices any
  car added later.
- **Where in code:** `backend/apps/policy/operating_costs.py`
  (`estimate_operating_costs`), `RoadTaxCcBand` / `EvRoadTaxGroup` /
  `OperatingCostRate` in `backend/apps/policy/models.py`,
  `FinancialProfile.ncd_percent` in `backend/apps/profiles/models.py`.

## 6. Total cost of ownership for every pathway (UC006 step 6)

- **Report says:** net TCO credits the predicted retained asset value for
  pathways ending in ownership.
- **Built system does:** exactly that, for four pathways: Hire Purchase and
  GFV-Retain over 60 months (resale value credited), GFV-Return and
  Subscription over the contract term (no resale; the subscription deposit is
  refunded). Because the horizons differ, the screen also shows **net cost per
  month of use**. Note: for a term of up to 60 months GFV-Retain's total
  equals Hire Purchase's on **any** depreciation curve - the machine-learning
  forecast or the estimated fallback - because the GFV instalments plus the
  balloon add up to exactly the Hire Purchase payments (the same flat rate on
  the same amount), and both keep the car and are credited the same resale
  value at month 60. Correct, and explained on the screen. (Only GFV's
  guarantee value depends on the curve: it is worth nothing on the fallback
  curve, which is anchored to the same residual as the balloon.)
- **Where in code:** `backend/apps/depreciation/services.py`
  (`build_pathway_tco`).

## 7. Smaller differences

- **Volvo** (XC60, XC90) is in the catalog although the report's scope is BMW,
  Mercedes-Benz, Lexus, Porsche and Toyota. A deliberate, flagged addition;
  the dev seed still holds the five report brands only.
- **Four mileage bands** (low / standard / high / very high) instead of three,
  shared by the compare screens and the Financial Profile.
- **Button names:** the Policy Configuration save button now reads **"Apply
  Policy Update"**, as in the report; the Fleet form keeps "Save Changes".
  ML training is one **"Upload & Train"** step that validates, then trains and
  evaluates; deployment stays a separate admin click gated at R² ≥ 0.80.
- **ML dataset, features and deployment:** see section 8.
- **Runtime errors** (UC013): unhandled errors are now written to the audit
  log as "Runtime error" rows (error type, a short message, path, status - no
  stack trace or secrets), at most one per error type and path per minute.
- **Session tokens (FX-1 X2b):** the 15-minute access token is kept per browser tab in
  `sessionStorage` (not only in memory), so reloading a page does not need a token refresh -
  a reload during a refresh used to lose the rotated refresh token and sign the buyer out.
  This reverses the earlier "access token in memory only" hardening (QA audit M22); the
  7-day refresh token was already in `localStorage`, and token refreshes are serialised
  across tabs (Web Locks).

## 8. ML target, features, candidates and the second metric

- **Report says:** a Random Forest / Gradient Boosting regressor predicts the
  vehicle's residual market value from [vehicle age, annual mileage, MSRP,
  brand tier code, power output (kW)]; new weights deploy only when the
  held-out R² is at least 0.80.
- **Built system does:**
  - **The gate is kept exactly**: R² ≥ 0.80 on the held-out 20% of resale
    values, the highest-R² candidate wins, and deployment is a separate admin
    action.
  - **A third candidate:** the report names Random Forest and Gradient
    Boosting; the build adds a **log-linear (hedonic) model** - the standard
    econometric model for car depreciation: log price = a price level per car
    model + one age/mileage effect shared across models (+ tier, engine, body,
    recond), fitted by ridge regression. Random Forest and Gradient Boosting are
    still trained and compared on every run. On the real data the log-linear
    model wins on both measures (run 10: held-out R² 0.9124 against 0.8776 GB /
    0.8603 RF; depreciation-shape R² 0.7199 against 0.5871 / 0.5132), because it
    separates model mix from age: young listings are mostly expensive models,
    which the trees mistake for "young cars keep their value" and so draw a
    curve that stays flat for the first year or more.
  - **A curve check before deploy:** besides the R² gate, the winner's
    depreciation curve for every catalog car it covers must fall from year to
    year, keep at most 95% after 12 months and keep 20%-75% after 60 months.
    These are sanity limits, not market claims; a run that fails is not
    deploy-eligible.
  - **Car ages from each listing's own year:** age = listing year - model
    year (2022 for the Kaggle snapshot, 2026 for hand-collected rows). An
    earlier single reference year for the whole file mis-aged every row.
  - **Target:** the resale price itself, on a log scale (relative errors, as
    prices span RM 20,000 to RM 1m+). The model is read at whole years (the
    data records age in whole years) and the months between are interpolated.
    The curve uses only its shape - value at month m = catalog price x
    exp(f(m) - f(0)) - so month 0 is the car's own price.
  - **Feature vector differs:** vehicle age, mileage, brand tier, **engine
    size in litres** (instead of kW), **body type** and **recond import**.
    **No MSRP**: the dataset has no real new price per listing, and an
    earlier stand-in (`msrp_proxy`, the highest *used* price of the same
    model) made the model compare each car with a 4-year-old example and was
    removed. The dataset (Kaggle "Malaysia Resale Carlist", 983 rows after
    cleaning) only gives engine size in litres, which does not convert to kW.
  - **A second metric is reported for transparency:** the
    "depreciation-shape R² (within the same model)" - the share of price
    differences *between listings of the same car model* the model explains,
    which is the part the depreciation curve uses. Both numbers are shown side
    by side on the ML page for every candidate; only the first gates
    deployment, as in the report.
  - **Electric cars use the fallback curve:** the dataset has no EVs (and
    the engine-size feature needs a displacement), so a BEV always gets the
    labelled estimated curve anchored to the GFV residuals, with its own
    message.
  - The older raw-price model (run 5, R² 0.89 on a feature that is not
    available at inference) and run 9 (trained on the mis-aged data) were
    retired; the "must beat production" check compares only R² measured on
    the same target.
  - **What the predicted curve is, and how it differs from the GFV residual
    (Run 2 fix batch 2):**
    - The deployed log-linear model's depreciation shape depends on the
      **brand tier only** (plus age and mileage). Body type, engine size and
      powertrain shift the price level, which cancels when the curve is scaled
      to the car's own price, so every car in a tier shares one percentage
      curve (run 10: 49.87% kept at month 60 for tier 1, 50.66% for tier 2).
      The screen therefore labels the figure as a brand-tier machine-learning
      estimate with a typical error of about 16% of the price (the same figure
      the ML page shows for the deployed run).
    - The GFV residual (the lender's conservative guaranteed buy-back) and the
      predicted market value are **deliberately different** things, and the
      screen now says so, with both numbers side by side (BMW 320i, 60 months:
      35% against 50.7% of the price). Subscription fees are priced on the
      residual, not on the curve.
- **Why:** the report's MSRP feature has no real source in public listing
  data, and the stand-in broke the model at inference; predicting the resale
  value itself is what the report describes. The second metric stops the
  headline R² - mostly "a Porsche costs more than a Perodua" - from being
  read as depreciation accuracy.
- **Where in code:** `backend/apps/ml/features.py` (the one feature
  definition), `backend/apps/ml/training.py` (`train_and_evaluate`,
  `within_model_r2`), `backend/apps/ml/log_linear.py`, `backend/apps/ml/curve_check.py`,
  `backend/apps/ml/listing_year.py`, `backend/apps/ml/management/commands/build_real_ml_dataset.py`,
  `backend/apps/depreciation/inference.py`, `backend/apps/depreciation/resale_notes.py`,
  `backend/apps/ml/data/README_real_data.md`.

## 9. Why GFV is recommended only when Hire Purchase is over the DSR limit

- **Report says:** each pathway is scored on three criteria - upfront cash
  preservation, maintenance protection and ownership equity - weighted by the
  buyer's own priority ratings, and a pathway over the buyer's DSR limit
  scores 0.
- **Built system does:** exactly that, and the honest consequence is worth
  stating. GFV scores the **same** as Hire Purchase on upfront cash (both
  need the same downpayment) and on maintenance protection (neither includes
  servicing), and **half** of Hire Purchase on ownership equity (at the end the
  buyer still has to pay the balloon to own the car). So on the written
  criteria GFV can never score above Hire Purchase: whatever the ratings, GFV
  is recommended only when Hire Purchase (and Subscription) are over the DSR
  limit and score 0. In Run 3, BMW 320i, all 125 rating combinations within
  the limit: GFV recommended 0 times; with Hire Purchase over the limit, every
  time. GFV's real advantage - the lower monthly instalment - is not one of the
  three criteria; it only shows up through the DSR rule.
- **Why it is kept:** this follows the FYP1 scoring definition as written; the
  scores are not changed. Adding "monthly instalment" as a fourth criterion
  would be a change to the specification, not a fix. The comparison table
  still shows GFV's lower instalment beside the others, and the rationale says
  when the recommendation is GFV that a balloon is due at the end.
- **Where in code:** `backend/apps/scoring/formulas.py`
  (`calculate_pathway_scores`, `MAINTENANCE_PROTECTION_SCORE`,
  `OWNERSHIP_EQUITY_SCORE`).

## 10. Mileage bands recalibrated (Run 3 fix batch 6)

- **Report says:** the buyer declares an annual mileage; the comparison uses it
  for the residual (GFV), the resale forecast and the Subscription's included
  mileage.
- **Built system does:** four bands, same keys as before (low / standard / high /
  very high), with these limits - **planning assumptions, editable in Django
  admin** (the subscription policy's four "up to" fields; every screen, the PDF
  and the API read them from there):
  - low: up to 10,000 km a year
  - standard: 10,001 to 15,000
  - high: 15,001 to 25,000
  - very high: above 25,000 (modelled and sold up to 35,000)
  Each band runs up to and including its limit, and a Subscription in a band
  includes the band's limit.
- **Why these cut-offs:** Malaysian driving surveys put the typical car at about
  15,000-25,000 km a year, and premium brands commonly bundle multi-year service
  packages, so their owners tend to drive a bit less. The old bands (standard up to
  20,000) called a 20,000 km a year driver "standard", which overstated resale
  value for standard users. The cut-offs are a modelling choice, not market data.
- **Representative km (what the resale model is fed for a band) - an assumption,
  same rule as before:** the band's midpoint; very high's taken up to its 35,000
  limit; low fixed at 80% of its limit. Old 8,000 / 15,000 / 25,000 / 35,000 -> new
  8,000 / 12,500 / 20,000 / 30,000.
- **GFV residual grid (5 tenures x 4 bands), re-derived, not re-invented:** for
  each tenure the old grid is read as a straight line through its four (old
  representative km, ratio) points and evaluated at the new representative km
  (4 dp). The per-km slope is the one the old grid implied; low is unchanged; a
  higher band never keeps more than a lower one. E.g. 36 months: 0.55 / 0.50 /
  0.45 / 0.40 -> 0.5500 / 0.5179 / 0.4750 / 0.4250. Applied by a reversible data
  migration (policy 0028) that leaves admin-edited rows alone.
- **Resale model:** no retrain (mileage is already a feature). The model reads total
  mileage = annual km x age; that total is capped, age by age, at the highest
  mileage the training data has at that age, and the TCO tab and PDF then say "The
  forecast is capped at the mileage the model has seen." (today only the very high
  band at year 5: 150,000 km against 147,500 seen).
- **Where in code:** `backend/apps/policy/mileage.py` (the one definition),
  `SubscriptionPolicy` limits in `backend/apps/policy/models.py`, migrations
  `policy/0027` and `0028`, `backend/apps/depreciation/inference.py`
  (`trained_mileage_caps`).
