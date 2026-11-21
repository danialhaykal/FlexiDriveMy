"""
Django settings for the FlexiDriveMy backend.

Configuration is read from environment variables (12-factor style) so the
same settings module works locally, inside docker-compose, and in pytest.
See .env.example for the full list of variables.
"""

from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    import os

    return os.environ.get(key, default)


def env_bool(key, default=False):
    value = env(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_list(key, default=()):
    value = env(key)
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


# QA audit H4: SECRET_KEY must never have an insecure fallback - a known,
# guessable value (shared across every clone of this repo) lets anyone
# forge a valid JWT/session/admin token. Fail loudly at startup instead,
# rather than silently running with a known-compromised key. See
# config/env_safety.py (unit tested there directly) for the validation
# itself.
from .env_safety import require_env, resolve_secret_key  # noqa: E402

SECRET_KEY = resolve_secret_key(env("DJANGO_SECRET_KEY"))

# QA audit H4: DEBUG must default to False - it previously defaulted to
# True, which shows full tracebacks on every 500 in any environment that
# forgets to set DJANGO_DEBUG explicitly, and made seed_dev_data's own
# "refuses to run with DEBUG=False" guard meaningless. Local dev's own
# .env already sets DJANGO_DEBUG=True explicitly, so this doesn't change
# the normal dev workflow - it only changes what happens when that
# variable is left unset.
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "apps.users",
    "apps.vehicles",
    "apps.policy",
    "apps.audit",
    "apps.profiles",
    "apps.comparisons",
    "apps.ml",
    "apps.depreciation",
    "apps.scoring",
    "apps.exports",
    "apps.scenarios",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Run 1 fix batch 4 (UC013): an unhandled view error becomes one
    # "runtime_error" audit row (DRF views are logged by the exception handler
    # below; this covers the rest). Never changes the response.
    "apps.audit.runtime_errors.RuntimeErrorAuditMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "flexidrivemy"),
        "USER": env("POSTGRES_USER", "flexidrivemy"),
        # QA audit L21: no insecure default - the same committed password
        # ("flexidrivemy") in every clone of this repo was also committed,
        # in cleartext, to scripts/setup_local_db.sql. Same reasoning as
        # H4's SECRET_KEY/DEBUG fix: fail loudly at startup if unset,
        # rather than silently running with a known-compromised password.
        "PASSWORD": require_env("POSTGRES_PASSWORD", env("POSTGRES_PASSWORD")),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
    }
}

# Without pooling, Django opens one DB connection per request - under real
# concurrency (e.g. F005's 500-concurrent-user load test target) this can
# exceed Postgres's max_connections (100 on this local instance) well
# before the app itself is the bottleneck. Off by default: untested
# against pytest-django's transactional test wrapping, so it's opt-in via
# DB_POOL_ENABLED=True, used only when load testing (see
# backend/loadtest/README.md), not for normal dev/test runs.
if env_bool("DB_POOL_ENABLED", False):
    # max_size=20 was the first value tried here and turned out to be the
    # actual bottleneck in the first passing-looking load test run (0
    # connection failures, but a long tail of multi-*minute* outliers from
    # requests queueing for a pool slot) - 80 leaves 20 connections of
    # headroom under Postgres's 100 max_connections for psql/migrations/admin.
    DATABASES["default"]["OPTIONS"] = {"pool": {"min_size": 10, "max_size": 80}}

AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kuala_Lumpur"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django REST Framework -------------------------------------------------

REST_FRAMEWORK = {
    # QA audit H6: the blacklist-aware subclass also rejects an access
    # token that LogoutView has blacklisted - see
    # apps.users.authentication.BlacklistAwareJWTAuthentication.
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.users.authentication.BlacklistAwareJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    # QA audit M21: login/registration had no rate limiting at all,
    # letting a password be guessed without limit. Scoped (not the
    # blanket Anon/User throttles) so these two endpoints get their own
    # named rate independent of every other AllowAny/anonymous endpoint -
    # see LoginView/RegisterView's throttle_scope and DEFAULT_THROTTLE_RATES
    # below. Keyed by IP (ScopedRateThrottle's default anonymous cache key),
    # so this doesn't block legitimate traffic from other clients.
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {
        "auth-login": "5/min",
        "auth-register": "5/min",
    },
    # Run 1 fix batch 4 (UC013): DRF's own handler, plus one "runtime_error"
    # audit row for an unhandled error (never for a 4xx).
    "EXCEPTION_HANDLER": "apps.audit.runtime_errors.api_exception_handler",
}

# F013 - System Log & Audit Trail: cap how long a filtered audit log query
# may run before it's cancelled server-side (see apps/audit/db.py).
AUDIT_LOG_QUERY_TIMEOUT_MS = int(env("AUDIT_LOG_QUERY_TIMEOUT_MS", "8000"))

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# --- CORS (frontend dev server) --------------------------------------------

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", ["http://localhost:5173"])
# FX-2 (item 13): the app reads the PDF's file name from Content-Disposition, which a browser hides from
# a cross-origin script unless it is exposed.
CORS_EXPOSE_HEADERS = ["Content-Disposition"]

# --- Security (QA audit H4: `python manage.py check --deploy`) -------------
#
# Cookie Secure flags are safe to tie directly to DEBUG: they only add the
# `Secure` attribute (browser won't send the cookie over plain HTTP), which
# has no effect on local dev's own plain-HTTP setup and is strictly safer
# once DEBUG=False (a real deployment). Left for a deliberate deployment
# decision rather than flipped here: SECURE_SSL_REDIRECT and
# SECURE_HSTS_SECONDS, since both actively change request handling (an
# unconditional SSL redirect behind a reverse proxy that doesn't set
# X-Forwarded-Proto correctly loops forever) - safe only once the real
# production reverse-proxy/TLS-termination setup is known, which this local
# FYP build doesn't have. `check --deploy` still correctly flags both
# (W004, W008) as a reminder for whoever sets up that deployment.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# --- Celery / Redis ----------------------------------------------------------

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# Redis isn't running in this dev environment yet (see README). F012's
# retrain task is written as a real Celery task (@shared_task, .delay()),
# but with no broker to hand it to, .delay() would just fail outright.
# CELERY_TASK_ALWAYS_EAGER makes .delay() execute inline/synchronously
# instead, so the endpoint and tests work today. Once Redis is running,
# flip this to False (and run `celery -A config worker`) for real async
# execution - no code changes needed.
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", True)
CELERY_TASK_EAGER_PROPAGATES = True

# --- F012 ML model storage --------------------------------------------------

ML_MODELS_DIR = env("ML_MODELS_DIR", str(BASE_DIR / "ml_models"))
ML_DATASET_UPLOAD_DIR = env("ML_DATASET_UPLOAD_DIR", str(BASE_DIR / "ml_data" / "uploads"))
# QA audit L18: no upload size limit existed at all - a CSV upload is
# read fully into memory as a DataFrame (training.load_and_validate_csv)
# before anything else, so an arbitrarily large file was a real,
# unbounded memory-exhaustion risk for a single admin-only endpoint. 50MB
# is generous for a CSV of this schema (5 numeric columns) - the real
# 888-row production dataset is well under 100KB - while still clearly
# bounding the worst case.
ML_DATASET_MAX_UPLOAD_SIZE_BYTES = int(env("ML_DATASET_MAX_UPLOAD_SIZE_BYTES", str(50 * 1024 * 1024)))

# --- F006 ML inference -------------------------------------------------------

# How long predict_resale_curve()/explain_resale_prediction() each wait for
# the deployed model before falling back to straight-line depreciation /
# None (UC006 exception flow). QA audit M8: lowered from 5s to 2s now that
# _load_production_model() caches the deserialized estimator in-process
# (apps/depreciation/inference.py) - the 5s figure was sized to also cover
# a cold joblib.load() of the ~1.85MB model file on every single call,
# which no longer happens on a cache hit, so the remaining cost really is
# just the model's own predict()/SHAP call, typically well under 1s.
# Honest limit, not full NFR compliance: build_tco_report calls BOTH
# predict_resale_curve AND explain_resale_prediction sequentially - in the
# genuine worst case (both independently hang and both exhaust their full
# timeout), that's up to 2 * ML_INFERENCE_TIMEOUT_SECONDS = 4s, still over
# the 3s page-load NFR. Accepted as a known limit for this batch (the
# timeout is a safety net for a hung/degenerate case, not the expected
# path - same reasoning as the fallback's own existence); running the two
# calls concurrently or sharing one timeout budget across both would close
# this gap and is flagged for a future batch, not solved here.
ML_INFERENCE_TIMEOUT_SECONDS = float(env("ML_INFERENCE_TIMEOUT_SECONDS", "2"))

# --- F008 PDF export ---------------------------------------------------------

PDF_EXPORTS_DIR = env("PDF_EXPORTS_DIR", str(BASE_DIR / "exports" / "pdf"))
# How long render_pdf_with_timeout() waits for WeasyPrint before failing
# (UC008 alt flow: compilation timeout / memory exhaustion).
PDF_COMPILATION_TIMEOUT_SECONDS = float(env("PDF_COMPILATION_TIMEOUT_SECONDS", "30"))
