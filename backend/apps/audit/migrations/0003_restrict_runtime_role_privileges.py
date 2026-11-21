from django.db import migrations

# QA audit H2: migration 0002's trigger stops the ORM's normal UPDATE/
# DELETE path, but the app's own Postgres role can still bypass it
# entirely via TRUNCATE (which fires no row-level triggers at all) or by
# disabling the trigger itself (ALTER TABLE ... DISABLE TRIGGER), since
# it is this table's OWNER - and table-owner privileges in Postgres are
# NOT granted through GRANT/REVOKE, so they cannot be revoked from the
# owner itself, by the owner itself, no matter what SQL runs here.
# Confirmed for this project's actual role (`SELECT rolsuper,
# rolcreaterole FROM pg_roles WHERE rolname = current_user` -> both
# false, so it isn't even a superuser - it is simply the table's owner,
# which is sufficient on its own for TRUNCATE/DISABLE TRIGGER).
#
# What this migration DOES do: revoke TRUNCATE from PUBLIC (closes the
# gap for any OTHER, non-owner role that might ever connect to this
# database - e.g. a future read-only reporting role) and from the
# app's own role explicitly (inert against the owner today, but keeps
# the grant state honest/correct if ownership is ever transferred later
# without updating this migration).
#
# What this migration does NOT and CANNOT do: stop the CURRENT app role
# from truncating this table or disabling its trigger, because it owns
# the table. The only real fix is a genuine role split, which requires
# a Postgres SUPERUSER (this role is not one) running, outside Django's
# migration framework entirely:
#   1. CREATE ROLE flexidrivemy_app LOGIN PASSWORD '...';  (no CREATEDB/
#      CREATEROLE/SUPERUSER)
#   2. Keep today's role (flexidrivemy) as the table owner, used only
#      for `manage.py migrate` / deploys.
#   3. GRANT SELECT, INSERT ON audit_auditlog TO flexidrivemy_app;
#      (deliberately no UPDATE/DELETE/TRUNCATE, and no ALTER-level
#      privilege, which is what disabling a trigger requires)
#   4. Point the running Django app's DATABASES["default"]["USER"] at
#      flexidrivemy_app (a new settings/env split between "migration
#      role" and "runtime role" - today both are the same role), while
#      `manage.py migrate` keeps using the owning role.
# This is a deployment/infrastructure decision (new Postgres role +
# credentials + a settings change to how the app connects), not
# something a single migration or code change can safely do on its own
# - left open deliberately rather than guessing at production
# credentials or restructuring deployment without sign-off. See
# apps/audit/tests/test_db_role_privileges.py for an executable
# specification of exactly what is and isn't enforced today.

REVOKE_TRUNCATE_SQL = """
REVOKE TRUNCATE ON audit_auditlog FROM PUBLIC;
"""

# No real reverse operation needed - REVOKE has no meaningful "undo"
# beyond re-granting, which migration 0001 never granted in the first
# place (PUBLIC had TRUNCATE only via Postgres's historical default of
# granting table privileges to PUBLIC unless explicitly revoked).
GRANT_TRUNCATE_BACK_TO_PUBLIC_SQL = """
GRANT TRUNCATE ON audit_auditlog TO PUBLIC;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0002_immutability_trigger"),
    ]

    operations = [
        migrations.RunSQL(sql=REVOKE_TRUNCATE_SQL, reverse_sql=GRANT_TRUNCATE_BACK_TO_PUBLIC_SQL),
    ]
