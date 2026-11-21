"""Pure, independently-testable validation for security-sensitive
settings (QA audit H4) - factored out of settings.py so it can be unit
tested directly without spawning a subprocess or juggling the real .env
file on disk (settings.py itself can't be re-imported mid-test-session
with different env values, since Django settings are loaded once at
process start).
"""

from django.core.exceptions import ImproperlyConfigured

# Known-insecure values that must never be accepted as a real
# SECRET_KEY: the old hardcoded fallback this code used to silently use,
# and .env.example's own placeholder text (copying that file to .env
# without actually generating a real key would otherwise "work" with a
# value that's equally public - committed to this repo for everyone).
INSECURE_SECRET_KEY_PLACEHOLDERS = {
    "dev-insecure-change-me",
    "change-me-generate-a-real-key",
}


def resolve_secret_key(raw_value):
    """Returns `raw_value` if it's a real, non-placeholder secret key;
    otherwise raises ImproperlyConfigured. Never returns an insecure
    fallback - a missing/placeholder SECRET_KEY must fail loudly at
    startup, not silently run with a known-guessable value.
    """
    if not raw_value or not raw_value.strip() or raw_value in INSECURE_SECRET_KEY_PLACEHOLDERS:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is not set (or still has its .env.example placeholder "
            "value). Generate a real one: python -c \"from django.core.management.utils "
            "import get_random_secret_key; print(get_random_secret_key())\" and set it "
            "in your .env file."
        )
    return raw_value


def require_env(name, raw_value):
    """QA audit L21: same spirit as resolve_secret_key above - a
    required, security-sensitive setting (the Postgres password) must
    fail loudly at startup if unset, never silently fall back to a
    known, committed-to-the-repo default every clone of this project
    shares. Generic (not password-specific) so any other required
    env var can reuse it the same way.
    """
    if not raw_value or not raw_value.strip():
        raise ImproperlyConfigured(
            f"{name} is not set. Set it in your .env file (see .env.example) - "
            "there is no default."
        )
    return raw_value
