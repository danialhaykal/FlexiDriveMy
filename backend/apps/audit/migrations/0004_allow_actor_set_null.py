from django.db import migrations

# QA audit M18: AuditLog.actor uses on_delete=SET_NULL (actor_email is
# already denormalized onto the row specifically so the log stays
# meaningful once the account is gone) - but migration 0002's trigger
# rejects EVERY UPDATE unconditionally, including the single-column
# actor_id -> NULL update Django itself issues when the referenced User
# is deleted. That made deleting any admin who had ever performed an
# audited action fail with the trigger's own exception (an unhandled
# 500), even though nothing about this UPDATE actually threatens
# append-only-ness - every other column is untouched.
#
# This replaces the trigger function to allow exactly that one shape of
# UPDATE (actor_id transitioning from non-null to null, every other
# column byte-for-byte unchanged) while continuing to reject anything
# else - tampering with resource_id/before_data/after_data/etc., or
# reactivating a nulled actor_id to a different value, still raises.

UPDATE_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION audit_log_prevent_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.actor_id IS NULL
           AND OLD.actor_id IS NOT NULL
           AND NEW.id = OLD.id
           AND NEW.actor_email = OLD.actor_email
           AND NEW.timestamp = OLD.timestamp
           AND NEW.action = OLD.action
           AND NEW.resource_type = OLD.resource_type
           AND NEW.resource_id = OLD.resource_id
           AND NEW.ip_address IS NOT DISTINCT FROM OLD.ip_address
           AND NEW.before_data IS NOT DISTINCT FROM OLD.before_data
           AND NEW.after_data IS NOT DISTINCT FROM OLD.after_data
        THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION 'audit_auditlog rows are append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;
"""

REVERT_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION audit_log_prevent_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_auditlog rows are append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0003_restrict_runtime_role_privileges"),
    ]

    operations = [
        migrations.RunSQL(sql=UPDATE_TRIGGER_FUNCTION_SQL, reverse_sql=REVERT_TRIGGER_FUNCTION_SQL),
    ]
