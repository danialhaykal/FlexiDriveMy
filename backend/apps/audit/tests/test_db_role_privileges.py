"""QA audit H2 - executable specification of exactly what is and isn't
enforced at the database layer against audit_auditlog, given this app's
own Postgres role (which owns the table - see migration
0003_restrict_runtime_role_privileges's docstring for the full
explanation of why a table owner's privileges can't be revoked from
itself). Documents the current, honest state rather than asserting a
stronger guarantee than what's actually true.
"""

import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


def make_log(**overrides):
    defaults = {"action": "create", "resource_type": "vehicles.VehicleModel", "resource_id": "1"}
    defaults.update(overrides)
    return AuditLog.objects.create(**defaults)


def test_current_role_is_not_a_superuser_or_createrole():
    """Ground truth for the limitation documented below: this role isn't
    special-cased, it's just this table's OWNER (confirmed via
    pg_roles), which is sufficient on its own for TRUNCATE/DISABLE
    TRIGGER and is not revocable via GRANT/REVOKE.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolsuper, rolcreaterole FROM pg_roles WHERE rolname = current_user"
        )
        is_superuser, can_create_role = cursor.fetchone()
    assert is_superuser is False
    assert can_create_role is False


def test_update_and_delete_are_blocked_by_the_trigger_regardless_of_role():
    """What IS fully enforced (migration 0002) - row-level UPDATE/DELETE,
    which the trigger rejects unconditionally, ownership notwithstanding.
    """
    log = make_log()
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE audit_auditlog SET resource_id = %s WHERE id = %s", ["tampered", log.pk])
    assert AuditLog.objects.get(pk=log.pk).resource_id == "1"


@pytest.mark.xfail(
    reason=(
        "KNOWN, DOCUMENTED LIMITATION (QA audit H2): TRUNCATE fires no "
        "row-level triggers at all, and this app's Postgres role owns "
        "audit_auditlog - table-owner privileges aren't granted via "
        "GRANT/REVOKE in Postgres, so they can't be revoked from the "
        "owner by the owner. Closing this fully requires a genuine "
        "role split run by a Postgres superuser outside Django's "
        "migration framework - see migration "
        "0003_restrict_runtime_role_privileges's docstring. This test "
        "is expected to fail (TRUNCATE succeeds) until that deployment "
        "decision is made; it exists so a future fix is proven by this "
        "test flipping to passing, not by silently deleting it."
    ),
    strict=True,
)
def test_truncate_is_blocked():
    make_log()
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE audit_auditlog")
    assert AuditLog.objects.count() > 0


@pytest.mark.xfail(
    reason=(
        "KNOWN, DOCUMENTED LIMITATION (QA audit H2): disabling a trigger "
        "requires ALTER TABLE privilege, which this role has as the "
        "table's owner - the same owner-bypass gap as TRUNCATE above. "
        "See migration 0003_restrict_runtime_role_privileges's docstring."
    ),
    strict=True,
)
def test_disabling_the_trigger_is_blocked():
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE audit_auditlog DISABLE TRIGGER audit_auditlog_no_delete")
    try:
        log = make_log()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_auditlog WHERE id = %s", [log.pk])
        assert AuditLog.objects.filter(pk=log.pk).exists()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE audit_auditlog ENABLE TRIGGER audit_auditlog_no_delete")


def test_truncate_from_public_grant_is_revoked():
    """What IS achievable and enforced by migration 0003: PUBLIC (any
    role other than the owner) no longer has TRUNCATE on this table.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_table_privilege('public', 'audit_auditlog', 'TRUNCATE')"
        )
        (public_can_truncate,) = cursor.fetchone()
    assert public_can_truncate is False
