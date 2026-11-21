"""QA audit M18: deleting a user who has performed at least one audited
action used to fail with a 500 - Django's on_delete=SET_NULL on
AuditLog.actor issues an UPDATE nulling actor_id, which migration 0002's
trigger rejected unconditionally. Migration 0004 narrows that rejection
to allow exactly this one shape of UPDATE.
"""

import pytest

from apps.audit.models import AuditActionCategory, AuditLog
from apps.users.models import User, UserRole

pytestmark = pytest.mark.django_db


def test_deleting_a_user_with_an_audited_action_succeeds(create_user):
    actor = create_user(email="actor@example.com", role=UserRole.ADMIN)
    log = AuditLog.objects.create(
        actor=actor,
        actor_email=actor.email,
        action=AuditActionCategory.CREATE,
        resource_type="vehicles.Brand",
        resource_id="1",
    )

    actor.delete()

    assert not User.objects.filter(pk=actor.pk).exists()
    log.refresh_from_db()
    assert log.actor_id is None
    # Denormalized at write time - the log stays meaningful even though
    # the account is gone.
    assert log.actor_email == "actor@example.com"


def test_deleting_a_user_with_multiple_audited_actions_succeeds(create_user):
    actor = create_user(email="busy-actor@example.com", role=UserRole.ADMIN)
    logs = [
        AuditLog.objects.create(
            actor=actor, actor_email=actor.email, action=AuditActionCategory.CREATE,
            resource_type="vehicles.Brand", resource_id=str(i),
        )
        for i in range(3)
    ]

    actor.delete()

    for log in logs:
        log.refresh_from_db()
        assert log.actor_id is None
        assert log.actor_email == "busy-actor@example.com"


def test_other_audit_log_fields_are_unaffected_by_the_set_null(create_user):
    actor = create_user(email="actor2@example.com", role=UserRole.ADMIN)
    log = AuditLog.objects.create(
        actor=actor, actor_email=actor.email, action=AuditActionCategory.UPDATE,
        resource_type="policy.InterestRate", resource_id="42",
        before_data={"rate_percent": "3.0000"}, after_data={"rate_percent": "4.0000"},
    )

    actor.delete()

    log.refresh_from_db()
    assert log.action == AuditActionCategory.UPDATE
    assert log.resource_type == "policy.InterestRate"
    assert log.resource_id == "42"
    assert log.before_data == {"rate_percent": "3.0000"}
    assert log.after_data == {"rate_percent": "4.0000"}


def test_a_direct_update_attempt_tampering_with_another_field_is_still_rejected():
    """The narrowed trigger must still reject anything other than the
    exact actor_id-only-to-NULL shape - this isn't a general-purpose
    UPDATE escape hatch.
    """
    from django.db import DatabaseError, connection

    log = AuditLog.objects.create(
        action=AuditActionCategory.CREATE, resource_type="vehicles.Brand", resource_id="1"
    )

    with pytest.raises(DatabaseError):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE audit_auditlog SET resource_id = %s WHERE id = %s", ["tampered", log.pk]
            )
