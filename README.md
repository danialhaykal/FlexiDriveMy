# FlexiDriveMy

An AI-powered car subscription and GFV (Guaranteed Future Value) financing comparison platform for the Malaysian market. A buyer enters a financial profile, picks a vehicle from the catalogue, and compares the pathways side by side: Hire Purchase, GFV financing and a subscription. The platform adds a machine-learning resale forecast, total cost of ownership and a suitability score.

## Screenshots

<!-- Add screenshots here, for example:
![Catalogue](docs/screenshots/catalogue.png)
![Compare financing](docs/screenshots/compare-financing.png)
-->

_Screenshots coming soon._

## Main features

For buyers:
- Registration, login and logout with JWT authentication, plus a profile and a financial profile (budget, tenure, mileage, Islamic-financing wording preference)
- Public vehicle catalogue with filters, a vehicle detail page and quick look
- Side-by-side comparison of Hire Purchase, GFV and Subscription pathways
- ML resale forecast, total cost of ownership and a negative-equity view
- Suitability scoring across pathways, with a hard debt-service-ratio (DSR) gate and a DSR simulator
- Total-loss ("if written off") sandbox and an Arena page for comparing cars
- PDF export of a comparison report, and saved scenarios ("My Comparisons")

For admins:
- Fleet management: brands and vehicle models with bulk import, and vehicle readiness
- Policy management: interest rates, the GFV residual matrix and scoring-criteria weights
- ML model management: train RandomForest / GradientBoosting models and view model history
- Append-only audit log

## Tech stack

**Backend** (`backend/`)
- Python, Django 5.1, Django REST Framework, Simple JWT
- PostgreSQL (psycopg 3)
- scikit-learn, pandas, NumPy, joblib and SHAP for the ML and explainability features
- WeasyPrint for PDF reports, openpyxl
- Celery and Redis (optional in development; see below)
- pytest and pytest-django

**Frontend** (`frontend/`)
- React 18, TypeScript, Vite
- Tailwind CSS 4, React Router, axios, Recharts, lucide-react
- Vitest and Testing Library, oxlint

## Project layout

```
FlexiDriveMy/
├── backend/    Django REST API (config/, apps/, scripts/, tests/)
├── frontend/   React + TypeScript app (src/)
└── docs/       development notes and photo credits
```

## Setup

### Prerequisites
- Python 3 and `pip`
- Node.js and `npm`
- PostgreSQL (the development notes were written against PostgreSQL 18)

### Backend

1. Create the local database role and database. Open `backend/scripts/setup_local_db.sql`, replace the placeholder password with your own, then run it once as the `postgres` superuser:

   ```bash
   psql -U postgres -h localhost -f backend/scripts/setup_local_db.sql
   ```

2. Create your environment file and fill it in. Set `POSTGRES_PASSWORD` to the same password you chose in step 1:

   ```bash
   cd backend
   cp .env.example .env
   ```

   Generate your own secret key with:

   ```bash
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

3. Install dependencies, migrate and run:

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver
   ```

The API is served at `http://localhost:8000/api/` and the Django admin at `http://localhost:8000/admin/`.

Notes:
- Redis is optional in development. With `CELERY_TASK_ALWAYS_EAGER=True`, the model-retraining and PDF-export tasks run inline instead of needing a broker.
- PDF export uses WeasyPrint, which needs the native GObject / Pango / cairo libraries. They are available on most Linux systems; on Windows, install the GTK3 runtime. Without them, PDF export reports that the engine is unavailable.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env      # sets VITE_API_BASE_URL (default http://localhost:8000/api)
npm run dev               # http://localhost:5173
```

Other scripts: `npm run build` (type-check and production build), `npm run lint`, `npm run preview`.

## Running the tests

**Backend** (needs a running PostgreSQL; the database role needs `CREATEDB` so pytest-django can create its own test database, which `setup_local_db.sql` grants):

```bash
cd backend
pytest
```

**Frontend:**

```bash
cd frontend
npm test            # run once
npm run test:watch  # watch mode
```

## More documentation

- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md): detailed per-feature development notes
- [`docs/photo_credits.md`](docs/photo_credits.md): credits for the vehicle photos
