from django.db import migrations

# F013 rule: "Audit trail log records are strictly append-only;
# administrators cannot delete, edit, or tamper with recorded log entries."
#
# The app's DB role also owns this table (it ran the migrations that
# created it), so plain REVOKE UPDATE/DELETE grants would have no effect —
# table owners bypass GRANT/REVOKE in Postgres. A trigger that unconditionally
# rejects UPDATE/DELETE is the enforcement mechanism the project spec itself offers
# as the alternative, and it holds regardless of which role is connected.

CREATE_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION audit_log_prevent_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_auditlog rows are append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;
"""

DROP_TRIGGER_FUNCTION_SQL = "DROP FUNCTION IF EXISTS audit_log_prevent_modification() CASCADE;"

CREATE_TRIGGERS_SQL = """
CREATE TRIGGER audit_auditlog_no_update
    BEFORE UPDATE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_log_prevent_modification();

CREATE TRIGGER audit_auditlog_no_delete
    BEFORE DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_log_prevent_modification();
"""

DROP_TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS audit_auditlog_no_update ON audit_auditlog;
DROP TRIGGER IF EXISTS audit_auditlog_no_delete ON audit_auditlog;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_TRIGGER_FUNCTION_SQL, reverse_sql=DROP_TRIGGER_FUNCTION_SQL),
        migrations.RunSQL(sql=CREATE_TRIGGERS_SQL, reverse_sql=DROP_TRIGGERS_SQL),
    ]
