import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.users.models import UserRole

TEST_PASSWORD = "StrongPassw0rd!23"


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """QA audit M21: login/register are now rate-limited via DRF's
    ScopedRateThrottle, which tracks request counts in Django's cache
    (LocMemCache by default - one process-wide instance, not reset
    between tests on its own). Without this, tests that call the real
    login/register endpoints several times would accumulate counts
    across the whole test session and eventually start failing with an
    unrelated 429, depending on test execution order.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_password():
    return TEST_PASSWORD


@pytest.fixture
def create_user(db):
    from apps.users.models import User

    def _create_user(email="rider@example.com", role=UserRole.USER, password=TEST_PASSWORD, **kwargs):
        return User.objects.create_user(email=email, password=password, role=role, **kwargs)

    return _create_user


@pytest.fixture
def regular_user(create_user):
    return create_user(email="rider@example.com", role=UserRole.USER)


@pytest.fixture
def admin_user(create_user):
    return create_user(email="admin@example.com", role=UserRole.ADMIN, is_staff=True)


@pytest.fixture(autouse=True)
def isolate_ml_storage(settings, tmp_path):
    """Tests that go through the real F012 upload/training endpoints or
    F008's PDF export endpoint write actual files (CSVs, joblib models,
    PDFs) to settings.ML_*_DIR / PDF_EXPORTS_DIR. Without this, every test
    run would leave more of them behind in the real backend/ml_models,
    ml_data, and exports directories. tmp_path is per-test and cleaned up
    by pytest automatically.
    """
    settings.ML_MODELS_DIR = str(tmp_path / "ml_models")
    settings.ML_DATASET_UPLOAD_DIR = str(tmp_path / "ml_data" / "uploads")
    settings.PDF_EXPORTS_DIR = str(tmp_path / "exports" / "pdf")
