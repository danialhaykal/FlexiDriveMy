"""QA audit M1: query-param filters (catalog, audit log) previously
passed raw, unchecked strings straight into ORM lookups - a non-numeric
`brand`/`actor`, a non-numeric `min_price`/`max_price`, or a malformed
date crashed with an unhandled 500 once the queryset was actually
evaluated (Django/psycopg raising deep inside query execution, not
caught by anything in these views). These helpers validate and parse a
query param up front, raising DRF's own ValidationError (which the
framework always turns into a clean 400) instead of letting a bad value
ever reach the database.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import ValidationError


def parse_int_param(params, key):
    raw = params.get(key)
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError({key: f"'{key}' must be a valid integer."})


def parse_decimal_param(params, key):
    raw = params.get(key)
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({key: f"'{key}' must be a valid number."})


def parse_datetime_param(params, key, *, end_of_day=False):
    """Accepts either a plain date ("2026-01-01") or a full ISO-8601
    datetime - a date-only value is treated as midnight local time that
    day BY DEFAULT. parse_datetime() returns a NAIVE datetime for a
    date-only string (no time component to attach a timezone to) rather
    than None, so every path below is passed through make_aware() when
    needed - never just trusted as already aware.

    QA audit L12: `end_of_day=True` (the audit log view's own
    `timestamp_to`) instead combines a date-only value with the LAST
    instant of that day - "to 2026-10-03" means through the end of
    October 3rd to a human, not "until the stroke of midnight starting
    it", which previously silently excluded every entry from later that
    same day. Only applies when no explicit time was given at all - an
    explicit ISO-8601 datetime is always honored exactly as given.
    """
    raw = params.get(key)
    if not raw:
        return None
    # parse_date() is tried FIRST, not as a fallback after parse_datetime()
    # fails: Django's parse_datetime() regex has an OPTIONAL time portion,
    # so it successfully parses a bare "YYYY-MM-DD" too (as midnight) -
    # checking parse_date() first is what actually lets a pure date route
    # through the end_of_day branch below, rather than that branch being
    # unreachable dead code for exactly the input it exists to handle.
    # parse_date()'s own regex is anchored to match ONLY a bare date
    # (nothing else), so a real datetime string still falls through to
    # parse_datetime() below exactly as before.
    parsed_date = parse_date(raw)
    if parsed_date is not None:
        time_component = datetime.max.time() if end_of_day else datetime.min.time()
        parsed = datetime.combine(parsed_date, time_component)
    else:
        parsed = parse_datetime(raw)
    if parsed is None:
        raise ValidationError({key: f"'{key}' must be a valid date (YYYY-MM-DD) or ISO-8601 datetime."})
    if dj_timezone.is_naive(parsed):
        parsed = dj_timezone.make_aware(parsed)
    return parsed
