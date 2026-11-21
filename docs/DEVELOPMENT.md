# FlexiDriveMy: development notes

> Detailed per-feature development notes. For setup and an overview, see the [main README](../README.md). References to a separate project spec refer to a document that is not published in this repository.


AI-powered multi-brand car subscription & GFV FinTech aggregator (Malaysia). The full project spec is not published in this repository.

## Structure

```
FlexiDriveMy/
├── backend/            Django REST Framework API
│   ├── config/         settings, urls, celery app
│   ├── apps/
│   │   ├── common/     shared abstract models (TimeStampedModel)
│   │   ├── users/      custom User model (role field), auth endpoints (F001/F002)
│   │   ├── vehicles/   Brand, VehicleModel CRUD + bulk import (F010); public catalog (F004)
│   │   ├── policy/     interest rates, GFV residual matrix, MCDA weights (F011)
│   │   ├── audit/      append-only AuditLog, F010/F011 audit-log plumbing (F013)
│   │   ├── profiles/   FinancialProfile - budget/tenure/mileage/Shariah baseline (F003)
│   │   ├── comparisons/ HP/GFV/Subscription pathway calculator (F005)
│   │   ├── ml/          RandomForest/GradientBoosting training + Celery task (F012)
│   │   ├── depreciation/ ML resale forecast, TCO, negative-equity crossover (F006)
│   │   ├── scoring/      MCDA suitability scoring + hard DSR gate (F007)
│   │   ├── exports/      WeasyPrint PDF report generation (F008)
│   │   └── scenarios/    saved comparison scenarios (F009)
│   ├── scripts/        one-time local Postgres role/database setup SQL
│   ├── ml_models/       trained model files (gitignored)
│   ├── ml_data/         uploaded training CSVs (gitignored)
│   ├── exports/pdf/     generated PDF reports (gitignored)
│   └── tests/          project-level smoke test
├── frontend/            React 18 + TypeScript + Tailwind (Vite)
│   └── src/
│       ├── api/         axios client + auth requests + catalog requests
│       ├── context/      AuthContext (login/logout/profile state)
│       ├── components/  LoginForm, RegisterForm, ProfileForm, ProtectedRoute,
│       │                 CatalogGrid, CatalogFilters, VehicleCard
│       └── pages/        LoginPage, RegisterPage, ProfilePage, DashboardPage,
│                          CatalogPage, VehicleDetailPage
└── README.md
```

Docker is not used on this machine (virtualization detection fails under Secured-core PC / VBS). All local dev runs directly against Python and a local PostgreSQL 18 install — no containers.

## Backend

### One-time database setup

Run [backend/scripts/setup_local_db.sql](backend/scripts/setup_local_db.sql) once against your local Postgres 18 instance, as the `postgres` superuser:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -f backend\scripts\setup_local_db.sql
```

(It'll prompt for the `postgres` role's password — the one you set at install time.) This creates a dedicated `flexidrivemy` role/database with `CREATEDB` (not superuser), so pytest-django can create/drop its own `test_flexidrivemy` database automatically. The role's password is `<your-postgres-password>`, already wired into `backend/.env` and `backend/.env.example` — no further edits needed unless you want to change it.

### Run the app

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

API is served at `http://localhost:8000/api/`, Django admin at `http://localhost:8000/admin/`.

Redis isn't running in this dev environment (Docker doesn't work here at all, per above, and a native Redis/worker setup hasn't been done yet). F012's retrain task and F008's PDF-export task are both real Celery tasks (`@shared_task`, `.delay()`), but `CELERY_TASK_ALWAYS_EAGER=True` (set in `.env`) makes `.delay()` execute inline instead of requiring a broker. Once Redis is running, flip that to `False` and run `celery -A config worker` for real async execution — no code changes needed. PDF export works in both modes (eager: the PDF streams back in the same request; real worker: `202 {job_id}` and the page polls, then downloads) - see `docs/FYP2_report_deviations.md` item 1 for the exact demo commands.

F008 also depends on WeasyPrint, which needs a native GObject/Pango/cairo runtime this Windows machine doesn't have (confirmed: `import weasyprint` raises `OSError: cannot load library 'libgobject-2.0-0'`). `pip install` succeeds regardless (it's a pure-Python wheel); only the actual PDF-compilation call fails here. See "What's implemented (F007 + F008 + F009)" below for how this was handled.

### Before a demo or deployment

Development runs with `DJANGO_DEBUG=True` and local defaults. Before showing the app to anyone outside this
machine, or deploying it, check every item:

- [ ] `DJANGO_DEBUG=False` - no debug pages or stack traces shown to visitors.
- [ ] `DJANGO_ALLOWED_HOSTS` set to the real host name(s) (comma-separated), not left at
      `localhost,127.0.0.1`.
- [ ] A real `DJANGO_SECRET_KEY`: long, random, never committed, different from the development one.
- [ ] `CORS_ALLOWED_ORIGINS` limited to the real frontend address (not `http://localhost:5173`).
- [ ] `python manage.py check --deploy` run with those settings, and every warning read (some, such as
      `SECURE_SSL_REDIRECT` and HSTS, depend on how HTTPS is set up in front of the app - decide them
      deliberately rather than silencing them).
- [ ] GTK3 runtime installed on Windows, so WeasyPrint can build PDFs (otherwise PDF export answers 503
      "engine unavailable"): install the GTK3 runtime (e.g. the GTK-for-Windows Runtime Environment
      installer), make sure its `bin` folder is on `PATH`, and check `python -c "import weasyprint"` runs
      without an `OSError`.
- [ ] Frontend built for the real host: the API address (`VITE_API_BASE_URL`, default
      `http://localhost:8000/api`) is fixed into the bundle at build time, so set it before `npm run build`;
      the bundle is a single JavaScript file of about 845 KB (240 KB gzipped, no code splitting) - check the
      page still loads within 3 seconds on the target connection.

### What was verified in this environment

- `python manage.py check` → no issues
- `python manage.py makemigrations` → clean initial migrations for `users` and `vehicles` (committed under `apps/*/migrations/`)
- `python manage.py makemigrations --check --dry-run` → no drift between models and migrations
- `python manage.py migrate` → applies cleanly against the local `flexidrivemy` database, including the F013 audit-log immutability trigger and the F011 MCDA default-weights data migration
- `pytest` (full suite, live Postgres) → **247 passed, 1 skipped**, 0 warnings (the skip is a real end-to-end WeasyPrint compilation test that self-skips when the environment can't run it — see F008 below)

## Frontend

```powershell
cd frontend
npm install     # already run once during setup
cp .env.example .env   # VITE_API_BASE_URL, defaults to http://localhost:8000/api
npm run dev      # http://localhost:5173
npm run build    # tsc -b && vite build — verified clean
npm test         # vitest run — verified: 8/8 tests passing
```

## What's implemented (F001 + F002 + base schema)

- **Base schema**: `User` (custom model, `email` as login identifier, `role` ∈ {`user`, `admin`}), `Brand` (`name`, `tier_code`, `is_active`), `VehicleModel` (FK to Brand, `msrp` as `NUMERIC(12,2)`, `is_active`). Both `Brand`/`VehicleModel` carry a soft-delete `is_active` flag per the project spec's records policy; F010 below adds the CRUD endpoints and archive semantics on top of this schema.
- **F001 — Registration, login, JWT auth, profile view/edit**:
  - `POST /api/auth/register/` — self-registration always creates `role=user`; any `role` field in the payload is ignored server-side.
  - `POST /api/auth/login/` — returns `access`/`refresh` JWTs plus the user's profile. 15-minute access token, 7-day refresh token, rotation + blacklist-on-rotation enabled.
  - `POST /api/auth/login/refresh/` — standard SimpleJWT refresh.
  - `GET/PATCH /api/auth/profile/` — the authenticated user's own profile. `role`/`email`/`id`/`date_joined` are read-only.
  - `GET /api/auth/users/` — admin-only (role-based access control demo/target for F010's user-facing admin screens).
- **F002 — Logout**: `POST /api/auth/logout/` blacklists the given refresh token (`rest_framework_simplejwt.token_blacklist`), so it can no longer mint new access tokens.
- **Frontend**: `AuthContext` (token storage in `localStorage`, profile fetch on load), `LoginForm`/`RegisterForm`/`ProfileForm`, `ProtectedRoute`, and pages wiring them together via `react-router-dom`.

### Backend tests (`apps/users/tests/test_auth.py`)

Covers: registration (role can't be self-elevated, duplicate email rejected, weak password rejected), login (success, invalid credentials, unknown email, inactive user), **token expiry** (an explicitly expired `AccessToken` is rejected by a protected endpoint), profile view/edit (auth required, own data returned, editable fields persist, `role` can't be changed via PATCH), **role-based access** (regular user gets 403 on the admin-only endpoint, admin gets 200, unauthenticated gets 401), and logout (blacklists the refresh token, requires auth, requires a `refresh` field in the body).

### Frontend test (`src/components/auth/LoginForm.test.tsx`)

Renders the form fields, submits credentials and asserts `login()` is called with them and `onSuccess` fires, asserts the error message renders when `login()` rejects, and asserts the submit button disables while the request is in flight.

## What's implemented (F010 + F011 + F013)

No frontend work this pass — F010/F011/F013 are backend-only (endpoints + tests). All three roles' write paths are wired to F013's audit log via a shared `AuditedModelViewSet` mixin ([apps/audit/mixins.py](backend/apps/audit/mixins.py)).

- **F010 — Fleet & Car Specification Management (UC010)**: `VehicleModel` gained `trim`, `body_segment`, `thumbnail_url` (UC010's field list); `model_year` stays optional since UC010 never asks for it. `msrp` and `engine_capacity_kw` carry the exact boundary messages from UC010's alt flow ("MSRP must be a positive numeric value.", "Engine capacity must be between 0.10 kW and 500.00 kW.").
  - `GET/POST /api/vehicles/models/`, `GET/PATCH/DELETE /api/vehicles/models/<id>/` — single-record CRUD. `DELETE` archives (`is_active=False`), never hard-deletes; archived rows are excluded from list/retrieve unless `?include_archived=true`.
  - `POST /api/vehicles/models/bulk_import/` — CSV/Excel (`.csv`/`.xlsx`) bulk import. A missing required column rejects the whole batch (400, nothing committed) before any row is touched; otherwise every row runs through the *same* `VehicleModelSerializer` as single-entry create, and only the valid rows commit in one transaction. Response reports `total_rows`/`created_count`/`error_count` plus a per-row error list.
  - `GET/POST /api/vehicles/brands/`, `.../` — same CRUD + archive pattern for `Brand`.
  - All of the above are admin-only (`IsAdminRole`, UC010 Rule 1).

- **F011 — Financial Policy & Contract Rules Configuration**: new `apps/policy` app.
  - `InterestRate` (dealer rate per brand, `rate_percent` constrained to 0.01%–15.00%) — `/api/policy/interest-rates/`, standard CRUD + archive.
  - `ResidualValueMatrix` (GFV `G_ratio`, keyed by brand + `tenure_months` [12–108, matching HP_monthly's `t`] + `mileage_band`) — `/api/policy/residual-value-matrix/`, unique per (brand, tenure, band), CRUD + archive.
  - `MCDACriteriaWeight` (the three the project spec criteria) — `GET/PUT /api/policy/mcda-weights/`. This is deliberately *not* per-row CRUD: `Sum(w_j) = 1` spans all three rows, so the endpoint replaces all three atomically and rejects any payload that doesn't supply exactly the three criteria summing to 1.0. Seeded with defaults (0.34 / 0.33 / 0.33) via a data migration.

- **F013 — System Log & Audit Trail Management (UC013)**: new `apps/audit` app.
  - `AuditLog`: actor (+ denormalized `actor_email`), timestamp, action category (create/update/archive/bulk_import), resource type/id, IP address, `before_data`/`after_data` JSON snapshots.
  - **Append-only, enforced at the database level**: migration `0002_immutability_trigger` adds a Postgres trigger that raises on *any* UPDATE or DELETE against the table — chosen over revoking UPDATE/DELETE grants because the app's DB role owns the table (it ran the migrations that created it) and table owners bypass GRANT/REVOKE in Postgres, so a trigger is the only mechanism that actually holds. The model's `save()`/`delete()` also raise in Python as a fast, friendly first line of defense.
  - `GET /api/audit/logs/` — filterable by `actor`, `action`, `resource_type`, `timestamp_from`/`timestamp_to`; paginated. `GET /api/audit/logs/<id>/` — full before/after payload (UC013's detail inspector).
  - **Query timeout (UC013 alt flow)**: the list query runs under a Postgres `statement_timeout` (`AUDIT_LOG_QUERY_TIMEOUT_MS`, default 8000ms); a cancelled query returns `504` with "Log query timed out. Please specify a narrower date range filter." instead of hanging or 500ing.

### Backend tests added this pass (67 new, 90 total)

- `apps/vehicles/tests/test_vehicle_crud.py` — single-entry CRUD, the missing/invalid-value flow (negative MSRP, out-of-range engine capacity, missing mandatory field — each asserts only the offending field errors and nothing gets persisted), archive-not-hard-delete, and F013 integration (create/update/archive each write the expected audit row).
- `apps/vehicles/tests/test_bulk_import.py` — mixed valid/invalid rows (correct per-row error reporting, only valid rows committed), whole-batch rejection on a missing required column, unsupported file type, missing file, one audit row per imported vehicle.
- `apps/vehicles/tests/test_brand_crud.py`, `test_models.py` — Brand CRUD + archive; model-level constraint/validator coverage.
- `apps/policy/tests/` — interest-rate and residual-ratio boundary validation (incl. exact 0.01/15.00/12/108 boundary values), residual-matrix uniqueness, MCDA weight-set sum-to-1 validation.
- `apps/audit/tests/test_immutability.py` — direct SQL `UPDATE`/`DELETE` against `audit_auditlog` both raise `DatabaseError` (the DB trigger), plus the ORM-level `save()`/`delete()` guards.
- `apps/audit/tests/test_timeout.py` — the timeout helper cancels a `pg_sleep()`-slowed query deterministically; the view maps a timeout to the UC013 504 response (via monkeypatching, so this doesn't rely on an actually-slow query at the HTTP layer).
- `apps/audit/tests/test_filtering.py` — filter by action/actor/resource_type/timestamp range, role-gated access, detail view.

## What's implemented (F003 + F004)

- **F003 — Financial & Lifestyle Profiling Input (UC003)**: new `apps/profiles` app, `FinancialProfile` (one per user, `OneToOneField`).
  - `GET/PUT /api/profile/financial/` — a singleton-per-user resource, not row CRUD: GET 404s until the user's first save, PUT upserts ("Save & Apply Baseline" doesn't care whether this is a create or an edit). Any authenticated user (UC003's actor is "User", not admin); F003 is intentionally *not* wired into F013's audit log, since that's scoped to admin actions on F010/F011 data, not a user's own profile.
  - `monthly_budget` and `preferred_tenure_months` are declared explicitly on the serializer (not left to `ModelSerializer`'s auto-generated validators) so both the "not a number" and "out of range" cases surface UC003's exact message, "Please enter a valid positive numerical amount." — the same fix pattern used for F010's MSRP field.
  - `preferred_tenure_months` is bound to the same `[12, 108]` inclusive range as HP_monthly's `t` (the project spec) and F011's residual-value tenure — the constants now live in `apps/common/constants.py` so both apps import the same numbers instead of each hardcoding them. (UC003 Rule 2 says tenure must "strictly fall between 12 and 108 months (1 to 9 years)"; read as the same inclusive range the project spec's formula uses, not literal open-interval exclusion, since the parenthetical directly maps 12/108 to 1/9 years.)
  - `annual_mileage_band` stores the same four band keys as `policy.MileageBand` (audit batch 6, F6; one band list for the whole app, served by `GET /api/comparisons/mileage-bands/`). The ranges come from one definition, `apps/policy/mileage.py`, which reads the subscription policy's admin-editable limits (Run 3 fix batch 6: up to 10,000 / 15,000 / 25,000 km a year, very high above 25,000). Profiles saved with the original UC003 literal values (`10000` / `20000` / `30000`) still read as standard / high / very high.

- **F004 — Catalog Browse & Search (UC004)**: added to `apps/vehicles` (same `VehicleModel` data, a different read-only surface).
  - `GET /api/vehicles/catalog/` — paginated, always filtered to `is_active=True` with no `?include_archived` escape hatch (unlike the admin `VehicleModelViewSet`) — UC004 Rule 1. Any authenticated user, not admin-only.
  - Dynamic filters via query params: `brand` (id), `body_segment`, `min_price`/`max_price` (against `msrp`), `search` (name/trim/brand name, case-insensitive) — freely combinable, all evaluated server-side per request (UC004 Rule 2: no full page reload is a frontend property, met by the SPA just re-fetching on filter change rather than navigating).
  - `GET /api/vehicles/catalog/<id>/` — full spec/pricing detail view.
  - `GET /api/vehicles/catalog/brands/` — active brands only, for populating the filter dropdown (the admin `/api/vehicles/brands/` endpoint is `IsAdminRole`-gated and unreachable for regular users).
  - No matching vehicles → an ordinary `200` with `count: 0, results: []`, not an error; the frontend renders UC004's exact alt-flow message and a working "Reset All Filters" button.
  - **Frontend**: `CatalogPage` → `CatalogGrid` (fetches on mount and on every filter change via `useEffect([filters])`, no navigation involved) → `CatalogFilters` + `VehicleCard`; `VehicleDetailPage` for the per-vehicle spec view with a disabled "Compare Financing Options" placeholder (that flow isn't built yet). MSRP is formatted for display (`toLocaleString`) but never recomputed client-side, per the project spec's architecture rule.

### Backend tests added this pass (43 new, 133 total)

- `apps/profiles/tests/test_financial_profile.py` — budget/tenure boundary validation (non-positive, alphabetic, out-of-range, and the exact 12/108 boundary values), the invalid-input flow (only the offending field errors; a rejected PUT never overwrites a previously-saved baseline), mileage-band/ownership/Shariah persistence across all valid choices, per-user scoping (one user can't see another's profile).
- `apps/vehicles/tests/test_catalog.py` — access control (auth required, any role), the archived-vehicle exclusion rule, each filter individually (brand, body segment, min/max price, search-by-name/brand/trim), filter combinations (including one that narrows to zero), the empty-result case (200 with `count: 0`, not an error) and that resetting filters restores the full catalog, detail view (incl. 404 for an archived vehicle), and the brands-dropdown endpoint excluding archived brands.

### Frontend test added this pass (`src/components/catalog/CatalogGrid.test.tsx`, 3 new, 8 total)

Initial fetch renders the returned vehicles; changing the brand filter triggers a second fetch with the updated param, swaps the rendered vehicle, and leaves `window.location.href` unchanged (no navigation); an empty result renders UC004's exact alt-flow message, and clicking "Reset All Filters" clears the search input and re-fetches the unfiltered catalog.

## What's implemented (F005)

- **Formula correction (flagged before implementing, per the project spec's own "flag the deviation first" rule)**: the project spec's originally-published GFV formula didn't reproduce its own mandated reference case — computing it literally gives RM 1,270.37, not the required RM 5,344.44. The bug was an extra `× 12` in the first term's denominator (`/(12×t)` instead of `/t`); removing it reproduces the reference case exactly. The HP formula had the identical shape, with no reference case of its own to confirm it independently — corrected by the same logic (confirmed against you) and by the real Hire Purchase Act 1967 flat-rate convention. **the project spec itself has been corrected** (see its Financial formulas section, marked "*Corrected 2026-09-03*") so the spec and the implementation now agree:
  - `HP_monthly = (P − D) / t + [(P − D) × r] / 12`
  - `GFV_monthly = (P − D − GFV_balloon) / t + [(P − D) × r] / 12`
- **Formula-first**: [apps/comparisons/formulas.py](backend/apps/comparisons/formulas.py) is plain Python (no Django/DRF imports), covered by [apps/comparisons/tests/test_formulas.py](backend/apps/comparisons/tests/test_formulas.py) — written and passing *before* any endpoint code existed. Every monetary result is quantized to 2dp with `ROUND_HALF_UP` (the standard financial rounding convention, not Python's default banker's rounding).
- **`GET /api/comparisons/?vehicle=<id>&tenure_months=<t>&mileage_band=<band>&downpayment=<D>`** — read-only (GET, not POST: no side effects, nothing persisted). Looks up the vehicle's `msrp` (P), its brand's active `InterestRate` (r), the matching `ResidualValueMatrix` entry for (brand, tenure, mileage_band) (G_ratio), and (new) an active `SubscriptionPlan` for the vehicle (fee/insurance/tax/maintenance — F011's data didn't have anywhere to source the Subscription pathway's inputs from, so this small model was added). Returns all three pathways side by side in one call: `monthly_instalment`, `upfront_cash`, `total_contract_outlay` for each, plus `balloon_payment`/`residual_value_ratio` for GFV and `interest_rate_percent` for HP.
- **Missing/null config → 400, never a 500 (UC005 alt flow)**: a missing or inactive `InterestRate`, `ResidualValueMatrix` entry, or `SubscriptionPlan` each raise a `ComparisonConfigError` caught by the view and returned as `400 {"detail": "No active interest rate configured for brand '...'."}` (or the residual-ratio/subscription-plan equivalents) — never an unhandled exception.
- **Currency stays a string on the wire**: a real bug caught by the endpoint tests, not just theorized — returning raw `Decimal` values straight in a DRF `Response` falls through `JSONRenderer`'s fallback encoder to `float()`, exactly the precision loss the project spec's architecture rule forbids for money. Fixed by routing the result through an output `ComparisonResultSerializer` (`DecimalField.to_representation()` keeps every currency value a quoted string in the JSON body) rather than returning the plain dict directly. Covered by a test that asserts on `response.json()` (the actual over-the-wire body), not just `response.data`.
- No frontend work this pass (not requested) — the endpoint is ready for a future comparison-results UI to consume.

### Backend tests added this pass (27 new, 160 total)

- `apps/comparisons/tests/test_formulas.py` — the the project spec reference case (balloon + monthly, to the exact cent), a from-scratch manual reconciliation independent of the function under test, HP's equivalent manual reconciliation, a zero-rate sanity check, half-up rounding, and Subscription NetCost (including going negative when offsets exceed the fee).
- `apps/comparisons/tests/test_comparison_endpoint.py` — the full reference case end-to-end through the real API (not just the pure function), HP and Subscription pathways, all three pathways in one response, missing/inactive interest rate, missing residual ratio (both wrong-tenure and wrong-mileage-band cases), missing subscription plan, tenure/downpayment/vehicle validation (out-of-range tenure, downpayment ≥ price, negative downpayment, unknown or archived vehicle), and the wire-format currency-as-string check.

## What's implemented (F012 + F006)

New dependencies: `scikit-learn`, `pandas`, `numpy`, `joblib` (added to `requirements.txt`).

- **F012 — ML Data Management & Updating (UC012)**: new `apps/ml` app.
  - `POST /api/ml/datasets/` — CSV upload. Column validation (`vehicle_age`, `mileage`, `resale_price`, `brand_code`) happens synchronously so a malformed file is rejected immediately (`400`, UC012's exact message shape: `"Dataset upload failed. Missing required columns: [...]."`) with nothing created and the current production model untouched. A well-formed upload is saved to disk and handed to `run_training_task` (a real Celery `@shared_task`, run inline for now — see "Run the app" above).
  - The task trains **both** `RandomForestRegressor` and `GradientBoostingRegressor` on an 80/20 split, records R² and MAE for both on `MLTrainingRun`, and deploys whichever has the higher R² — but only if that R² also clears the 0.80 threshold (UC012 Rule 1); otherwise nothing is deployed and `MLTrainingRun.rejection_reason` explains why. "Hot-swap" means writing a new uniquely-named model file and repointing a `ProductionModel` singleton at it, never overwriting a fixed filename in place. A successful deployment writes an F013 audit log entry (`ml.ProductionModel`).
  - `GET /api/ml/training-runs/`, `GET /api/ml/training-runs/<id>/` — history/status for an ML Model Management dashboard.
  - **Known, flagged deviation from the project spec's 5-feature vector** `[Vehicle Age, Annual Mileage, MSRP, Brand Tier Code, Engine Capacity/kW]`: UC012's specified CSV columns only carry 4 fields with no MSRP or engine capacity per row, so this pipeline trains on 3 features (`vehicle_age`, `mileage`, `brand_code`) → `resale_price`. See `apps/ml/data/README.md`.
  - **Synthetic placeholder dataset**: no real historical pricing data exists yet, so `apps/ml/data/synthetic_historical_pricing.csv` (2,500 rows, reproducible via `python manage.py generate_synthetic_ml_dataset`) stands in — clearly marked SYNTHETIC in its own README, reaches R² ≈ 0.996 on both candidate models (comfortably clears the 0.80 gate), and must be replaced with real data before any model trained on it is trusted.

- **F006 — Predictive Depreciation, TCO Visualization & Contract Risk Alerts (UC006)**: new `apps/depreciation` app.
  - `GET /api/depreciation/tco/?vehicle=&tenure_months=&mileage_band=&downpayment=` — same input contract as F005's comparison endpoint. Calls F012's deployed model for a 60-month resale forecast (one row per month: `[vehicle_age_years, cumulative_mileage_estimate, brand_code]` — mileage is converted from the user's *annual* rate to an *estimated cumulative* odometer reading per month, matching what the model was actually trained on; see the note in `apps/depreciation/inference.py`), combines it with a new `OperatingCostBand` model (road tax/insurance/maintenance banded by engine capacity — kW, filling the data gap behind UC006's "operating cost parameter tables (UC011)", not yet its own full admin feature) into the project spec's 60-month TCO, and computes the negative-equity crossover: the first month the outstanding HP principal (excluding interest — interest isn't a claim against the asset) exceeds the predicted resale value, plus the shortfall amount.
  - **ML failure/timeout never blocks the response (UC006 exception flow)**: no deployed model, a corrupt model file, a prediction exception, or a prediction exceeding `ML_INFERENCE_TIMEOUT_SECONDS` (default 5s, via a background thread + `future.result(timeout=...)` so a hung prediction doesn't block the request) all fall back to a deterministic straight-line depreciation curve. The response completes normally with `model_degraded: true` and UC006's exact warning text, `degraded_reason`, never a 500.
  - Missing interest-rate or operating-cost config (same pattern as F005) → `400`, never a 500.
  - No frontend work this pass (not requested) — ready for a future "TCO Breakdown & Depreciation" tab to consume.

### Backend tests added this pass (46 new, 206 total)

- `apps/ml/tests/test_training.py` — malformed-CSV column validation (incl. every missing column listed, unparseable rows dropped vs. all-unparseable being fatal), the R² ≥ 0.80 gate as a pure decision function (deploys the higher-R² candidate when both clear 0.80, rejects when neither does, inclusive-at-exactly-0.80 boundary), and a smoke test that the checked-in synthetic dataset actually trains to an acceptable R².
- `apps/ml/tests/test_upload_endpoint.py` — admin-only, malformed CSV rejected with **no training run created and the existing production model provably untouched**, missing file, and a valid upload completing a full training run end-to-end (eager Celery).
- `apps/ml/tests/test_training_task.py` — **the explicitly-requested scenario**: a mocked low-R² retrain leaves the previously-deployed model's file path/R²/type completely unchanged and records the rejection reason; a mocked high-R² retrain deploys the better of the two candidates and writes an audit log entry (a rejected retrain does not).
- `apps/depreciation/tests/test_formulas.py` — straight-line fallback curve (incl. the 40% floor), HP outstanding-balance decay, the negative-equity crossover as a hand-constructed pure-function case *and* a fully hand-reconciled integrated case (price=100000, downpayment=5000, tenure=108 → crossover at month 42, shortfall RM55.56, verified independently to the cent), and TCO (incl. capping the payment term at `min(tenure, 60)`).
- `apps/depreciation/tests/test_inference_fallback.py` — **the explicitly-requested scenario**: no model deployed, a missing model file, a prediction exception, and a prediction timeout (monkeypatched to hang for 2s against a 50ms timeout, asserting the fallback returns in well under 1s rather than waiting out the hang) all degrade gracefully with the exact UC006 warning text; a working model is confirmed to actually be used (not silently replaced by the fallback) when nothing goes wrong.
- `apps/depreciation/tests/test_tco_endpoint.py` — the same negative-equity crossover reproduced end-to-end through the real API, missing interest-rate/operating-cost config as 4xx, degraded-but-complete responses when no model is deployed, and request validation.

## What's implemented (F007 + F008 + F009)

- **F007 — AI Suitability Scoring & Recommendation (UC007)**: new `apps/scoring` app, reuses F005's `build_comparison()` rather than recomputing HP/GFV/Subscription figures.
  - `GET /api/scoring/?vehicle=&tenure_months=&mileage_band=&downpayment=&upfront_cash_preservation=&maintenance_protection=&ownership_equity=&monthly_income=&max_dsr_percent=` — the three priority ratings (1-5 each) are normalized to weights summing to 1 (UC007 step 3); missing any one of the three blocks scoring with UC007's exact message, `"Please rate all three priorities to receive a recommendation."`, via a serializer `validate()` (fields declared `required=False` so DRF's own per-field errors don't fire first).
  - **the project spec specifies `Score_i = Σ(w_j × s_ij)` and the weight-normalization rule exactly, but not how each pathway's per-criterion score `s_ij` is derived** - a genuine gap, filled and flagged (not silently assumed) in `apps/scoring/formulas.py`: upfront-cash-preservation is continuous (min-max normalized across the pathways being compared, lower upfront cash scores higher); maintenance-protection and ownership-equity are fixed per pathway (Subscription bundles maintenance into its fee → 1.0, HP/GFV pay it separately → 0.0; HP gives full ownership → 1.0, GFV's balloon makes it conditional → 0.5, Subscription gives none → 0.0, consistent with the project spec's own TCO note about which paths credit `V_residual`).
  - **Hard DSR gate (UC007 Rule 1)**: each pathway's DSR (`monthly_instalment / monthly_income`) is compared against `max_dsr_percent`; exceeding it forces that pathway's score to exactly 0 **after** the weighted sum is computed, regardless of how high that sum was — verified by a test where a pathway with the mathematically maximum possible raw score (1.0) still gets zeroed and loses the ranking to a pathway DSR didn't touch. If every pathway exceeds the limit, `recommended_pathway` is `null` with a message saying none fit, rather than "recommending" a meaningless 0%.
  - Response includes the normalized weights, per-pathway DSR%/score/exceeds-flag, a `ranking`, the top pick, and a short plain-language `rationale` naming the pathway and the priority that drove it.
  - No frontend work this pass (not requested).

- **F008 — PDF Document Export Generation (UC008)**: new `apps/exports` app.
  - `POST /api/exports/pdf/` — the client sends whatever pathway figures it already has (from F005/F006/F007) reshaped into a `pathways` list plus an optional pre-rendered Recharts SVG string; the backend never recomputes anything, only renders it (the project spec's architecture rule). Dispatches `generate_pdf_task` as a real Celery task; in this environment's eager mode the task has already finished by the time `.delay()` returns, so the view checks the job immediately and either streams the compiled PDF back in the same response or returns UC008's alt-flow message. `PDFExportJob` tracks status/file path so a genuinely-async setup later would only need the view to return the job id instead of blocking on it — no model changes.
  - Compilation runs through a `ThreadPoolExecutor` + `future.result(timeout=...)` (same pattern as F006's ML-inference timeout) so a hang doesn't block the request; any failure — timeout, memory exhaustion, or (as here) the rendering engine being unavailable at all — surfaces through the same `PDFCompilationError` → `504 {"detail": "PDF export failed due to a server generation timeout. Please try downloading again."}`, never a 500. `weasyprint` is imported *lazily* inside the compile function, not at module load, specifically because it isn't usable on this machine (see above) - importing it eagerly would have crashed the whole Django app on startup.
  - The HTML template (`apps/exports/templates/exports/comparison_report.html`) explicitly includes the UC008 Rule 1 disclaimer and embeds `chart_svg` verbatim via Django's `|safe` filter (real SVG markup, never rasterized to an image, per the project spec).
  - **Real WeasyPrint compilation is unverified on this machine** (same native-library gap as the "Run the app" section explains) - flagged to you and confirmed before building, rather than silently working around it. What *is* verified here: the HTML template genuinely contains the disclaimer/data/SVG before compilation, the Celery dispatch and job-status bookkeeping, and the timeout/failure handling (all via mocking the compile step, not WeasyPrint itself). A real end-to-end test (`apps/exports/tests/test_real_pdf_compilation.py`) that compiles an actual PDF and extracts the disclaimer text back out with `pypdf` is written and correctly *self-skips* here (`import weasyprint` raises `OSError`, not the `ImportError` a plain `pytest.importorskip` catches, so this guards on `Exception` explicitly) - it will actually run and verify real PDF output wherever WeasyPrint's native deps are present (e.g. a Linux CI image).
  - No frontend work this pass (not requested).

- **F009 — Calculation History Save & Retrieval (UC009)**: new `apps/scenarios` app, `SavedScenario` (title + vehicle + opaque JSON `payload` — whatever the client already computed from F005/F006/F007, stored as-is so "reload the full comparison view" reproduces exactly what was saved even if rates change later).
  - `POST /api/scenarios/` creates; `GET /api/scenarios/` lists; `GET/PATCH/DELETE /api/scenarios/<id>/` — all scoped to the requesting user via `get_queryset()`, so another user's scenario id is a `404`, not a `403` (doesn't confirm the id exists for someone else) — UC009 Rule 1.
  - **Duplicate title (UC009 alt flow)**: a duplicate `(user, title)` without `overwrite` in the request returns `409 {"detail": "A scenario with this label already exists. Please provide a unique title or overwrite the existing scenario."}` (UC009's exact text) and touches nothing; the same request with `overwrite: true` replaces the existing row's payload in place (`updated_at` bumps via `auto_now`, "records the change timestamp" per UC009 2.4b) rather than creating a second row. The uniqueness check is per-user, not global — two different users can each have a scenario titled the same thing.
  - No frontend work this pass (not requested) — ready for a future "My Comparisons" dashboard to consume.

### Backend tests added this pass (41 new, 247 total; 1 skipped)

- `apps/scoring/tests/test_formulas.py` — weight normalization, a fully manually-reconciled MCDA scoring example (weights 0.5/0.3/0.2 → HP 20%, GFV 10%, Subscription 80%), and the DSR override forcing a 0 despite the maximum possible raw score.
- `apps/scoring/tests/test_scoring_endpoint.py` — the incomplete-quiz block for each of the three priorities individually and all three at once, the DSR override reflected end-to-end (every pathway zeroed, no recommendation), missing F010/F011 config as 400.
- `apps/exports/tests/test_rendering.py` — the disclaimer, vehicle label, pathway figures, and verbatim/unescaped SVG all present in the pre-compile HTML.
- `apps/exports/tests/test_pdf_timeout.py` — successful/failed/timed-out compilation (the timeout case asserts it returns in well under 1s against a 2s hang, not waiting it out), all via monkeypatching the compile step.
- `apps/exports/tests/test_export_endpoint.py` — auth required, a mocked-successful export streams real PDF headers/bytes, a mocked-failure returns the exact UC008 504 message and marks the job failed, request validation.
- `apps/exports/tests/test_real_pdf_compilation.py` — real end-to-end WeasyPrint compilation + `pypdf` text extraction confirming the disclaimer survives compilation (skips here, would run and pass in a working WeasyPrint environment).
- `apps/scenarios/tests/test_save_and_retrieve.py` — save, list (own scenarios only), retrieve (full payload reload), delete, blank-title rejection.
- `apps/scenarios/tests/test_duplicate_title.py` — the exact reject-and-rename message, saving under a different title instead, and the overwrite path replacing the payload in place and bumping `updated_at`.
- `apps/scenarios/tests/test_user_isolation.py` — another user gets 404 on retrieve/update/delete (not 403), is excluded from the owner's list, and the duplicate-title check is confirmed per-user (not global).

## Not yet built

F014+, the 60-month TCO's remaining pathway variants (GFV-return / GFV-retain distinction), and the "Compare Financing Options" / "TCO Breakdown & Depreciation" / suitability-quiz / "Export as PDF" / "My Comparisons" frontend UI that would call F005-F009 from the catalog's vehicle detail page — out of scope for this pass per the task.
