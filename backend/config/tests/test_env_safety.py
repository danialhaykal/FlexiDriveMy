"""QA audit H4: SECRET_KEY must fail loudly at startup when unset or
left at a known placeholder value, never silently fall back to one.
Tests the pure resolve_secret_key() function directly rather than
re-importing settings.py with different env values mid-test-session
(Django settings are loaded once at process start and can't safely be
re-loaded with a different SECRET_KEY inside a single test run).
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.env_safety import require_env, resolve_secret_key


@pytest.mark.parametrize(
    "raw_value",
    [None, "", "   ", "dev-insecure-change-me", "change-me-generate-a-real-key"],
)
def test_missing_or_placeholder_secret_key_raises(raw_value):
    with pytest.raises(ImproperlyConfigured):
        resolve_secret_key(raw_value)


def test_a_real_generated_secret_key_is_accepted():
    from django.core.management.utils import get_random_secret_key

    real_key = get_random_secret_key()
    assert resolve_secret_key(real_key) == real_key


# --- QA audit L21: no insecure default for a required env var --------------


@pytest.mark.parametrize("raw_value", [None, "", "   "])
def test_require_env_raises_when_unset(raw_value):
    with pytest.raises(ImproperlyConfigured):
        require_env("POSTGRES_PASSWORD", raw_value)


def test_require_env_accepts_a_real_value():
    assert require_env("POSTGRES_PASSWORD", "a-real-password") == "a-real-password"
