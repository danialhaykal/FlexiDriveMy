import hashlib
import ipaddress
import logging
import re

from django.core.cache import cache

from .models import AuditActionCategory, AuditLog

logger = logging.getLogger(__name__)


def _is_valid_ip(value):
    if not value:
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def get_client_ip(request):
    """Extracts a client IP for the audit log.

    `X-Forwarded-For` is attacker-controlled unless a trusted reverse
    proxy strips/overwrites it before this app ever sees the request - a
    production deployment requirement this header alone can't guarantee
    (QA audit H1). `REMOTE_ADDR` (the actual last-hop TCP connection) is
    the more reliable fallback when the header is missing or malformed.

    Always returns a syntactically valid IP string or None - never raises
    and never passes a malformed value through, which previously reached
    the database as an invalid `inet` literal and crashed the audit
    insert (H1's exact bug: after the record change had already
    committed, leaving no audit row at all).
    """
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        candidate = forwarded_for.split(",")[0].strip()
        if _is_valid_ip(candidate):
            return candidate
    remote_addr = request.META.get("REMOTE_ADDR")
    return remote_addr if _is_valid_ip(remote_addr) else None


def write_audit_log(
    *, actor, action, resource_type, resource_id, request=None, ip_address=None, before=None, after=None
):
    """Create one append-only audit row for an admin action against
    F010/F011/F012 data.

    Pass `request` when called from a view (IP is extracted from it).
    Background tasks (e.g. F012's Celery training task) have no request
    object, so they pass `ip_address` directly instead, captured earlier
    at upload time.
    """
    if request is not None:
        ip_address = get_client_ip(request)
    elif not _is_valid_ip(ip_address):
        # Defense in depth: a caller that bypasses get_client_ip() (e.g. a
        # background task passed a bad value) must still never reach the
        # database with a malformed `inet` literal (H1).
        ip_address = None
    return AuditLog.objects.create(
        actor=actor if actor and actor.is_authenticated else None,
        actor_email=getattr(actor, "email", "") or "",
        action=action,
        resource_type=resource_type,
        resource_id="" if resource_id is None else str(resource_id),
        ip_address=ip_address,
        before_data=before,
        after_data=after,
    )


# --- Run 1 fix batch 4: runtime errors (UC013 "system runtime errors") --------

RUNTIME_ERROR_RESOURCE_TYPE = "system.error"
RUNTIME_ERROR_WINDOW_SECONDS = 60
RUNTIME_ERROR_MESSAGE_MAX = 500
# How long a suppressed-repeat count waits for the next row that reports it.
_SUPPRESSED_COUNT_TTL_SECONDS = 24 * 60 * 60

# Anything that looks like a credential in an exception message is masked
# before it is stored: "password=...", "token: ...", "Bearer ...", a URL's
# "user:secret@" part.
_SECRET_PATTERNS = [
    # The value stops at whitespace or closing punctuation, so "(api_key=X)" keeps its ")".
    re.compile(
        r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|authorization|access|refresh)\b(\s*[=:]\s*)"
        r"[^\s,;)\]}'\"]+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(://[^/\s:@]+:)[^@\s/]+@"),
]


def _redact(text):
    # "Bearer <token>" first: in "Authorization: Bearer <token>" the key=value
    # rule alone would mask only the word "Bearer" and leave the token.
    text = _SECRET_PATTERNS[1].sub("Bearer [redacted]", text)
    text = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    return _SECRET_PATTERNS[2].sub(r"\1[redacted]@", text)


def _rate_limit_keys(source, error_type, path):
    digest = hashlib.sha256(f"{source}|{error_type}|{path}".encode()).hexdigest()[:32]
    return f"audit-runtime-error:{digest}", f"audit-runtime-error-suppressed:{digest}"


RUNTIME_ERROR_LOGGED_ATTR = "_flexidrivemy_runtime_error_logged"


def already_logged(error):
    """True once log_runtime_error has seen this exception object (e.g. a
    failed task whose error then reaches the web layer as a 500)."""
    return getattr(error, RUNTIME_ERROR_LOGGED_ATTR, False)


def _mark_logged(error):
    try:
        setattr(error, RUNTIME_ERROR_LOGGED_ATTR, True)
    except Exception:  # an exception type that refuses new attributes
        pass


def log_runtime_error(*, source, error, request=None, actor=None, context=None, status=500):
    """One append-only "runtime_error" audit row for an unhandled error.

    resource_type "system.error", resource_id = `source` ("api",
    "pdf_export", "ml_training", "spec_draft"...). after_data holds ONLY
    {error_type, message (first 500 characters, credential-looking values
    masked), path, method, status, context} - never a stack trace, request
    body, headers, tokens, passwords or environment values. The full
    traceback goes to the normal Python log instead.

    Rate limit: at most one row per (source, error_type, path) per 60 seconds
    (Django's cache), so an error storm can't flood the table; each
    suppressed repeat is counted and reported in the next row's
    context.suppressed. Never raises: if the row can't be written, a warning
    is logged and the caller carries on. Returns the row, or None. The
    exception is marked, so the same error object is never logged twice.
    """
    if already_logged(error):
        return None
    _mark_logged(error)
    try:
        logger.error(
            "Runtime error [%s]: %s", source, type(error).__name__,
            exc_info=(type(error), error, error.__traceback__),
        )
        error_type = type(error).__name__
        path = getattr(request, "path", "") if request is not None else ""
        row_key, suppressed_key = _rate_limit_keys(source, error_type, path)
        if not cache.add(row_key, True, RUNTIME_ERROR_WINDOW_SECONDS):
            cache.add(suppressed_key, 0, _SUPPRESSED_COUNT_TTL_SECONDS)
            cache.incr(suppressed_key)
            return None
        suppressed = cache.get(suppressed_key, 0)
        cache.delete(suppressed_key)

        if actor is None and request is not None:
            user = getattr(request, "user", None)
            actor = user if getattr(user, "is_authenticated", False) else None
        row_context = dict(context or {})
        if suppressed:
            row_context["suppressed"] = suppressed
        return write_audit_log(
            actor=actor,
            action=AuditActionCategory.RUNTIME_ERROR,
            resource_type=RUNTIME_ERROR_RESOURCE_TYPE,
            resource_id=source,
            request=request,
            after={
                "error_type": error_type,
                "message": _redact(str(error))[:RUNTIME_ERROR_MESSAGE_MAX],
                "path": path,
                "method": getattr(request, "method", "") if request is not None else "",
                "status": status,
                "context": row_context,
            },
        )
    except Exception:  # never let logging an error cause another one
        logger.warning("Could not write the runtime-error audit row for %s", source, exc_info=True)
        return None
