import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


def make_log(**overrides):
    defaults = {
        "action": "create",
        "resource_type": "vehicles.VehicleModel",
        "resource_id": "1",
    }
    defaults.update(overrides)
    return AuditLog.objects.create(**defaults)


def test_direct_sql_update_is_rejected_by_db_trigger():
    log = make_log()
    with pytest.raises(DatabaseError):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE audit_auditlog SET resource_id = %s WHERE id = %s", ["tampered", log.pk]
            )


def test_direct_sql_delete_is_rejected_by_db_trigger():
    log = make_log()
    with pytest.raises(DatabaseError):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_auditlog WHERE id = %s", [log.pk])


def test_row_survives_rejected_delete_attempt():
    log = make_log()
    # Wrapped in its own atomic() so the trigger's error only rolls back to
    # a savepoint, leaving the outer test transaction usable afterward.
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM audit_auditlog WHERE id = %s", [log.pk])
    assert AuditLog.objects.filter(pk=log.pk).exists()


def test_orm_save_on_existing_instance_raises():
    log = make_log()
    log.resource_id = "changed"
    with pytest.raises(ValueError):
        log.save()


def test_orm_delete_raises():
    log = make_log()
    with pytest.raises(ValueError):
        log.delete()
    assert AuditLog.objects.filter(pk=log.pk).exists()
