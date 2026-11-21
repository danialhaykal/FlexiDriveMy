from django.db import connection, transaction
from django.db.utils import OperationalError


class QueryTimeoutError(Exception):
    """Raised when a query is cancelled by Postgres's statement_timeout."""


def run_with_statement_timeout(fn, timeout_ms):
    """Run fn() with a Postgres statement_timeout applied, translating a
    server-side cancellation into QueryTimeoutError.

    SET LOCAL only applies for the current transaction, so the timeout and
    the query it guards are wrapped in the same atomic() block — required
    for this to take effect under Django's default autocommit mode.
    """
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", [timeout_ms])
            return fn()
    except OperationalError as exc:
        if "statement timeout" in str(exc).lower():
            raise QueryTimeoutError() from exc
        raise
