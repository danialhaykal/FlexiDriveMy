"""Run 1 fix batch 4 (UC013): a "Runtime Error" action category.

Only the field's choices change - no schema change - so the append-only
triggers from 0002 (BEFORE UPDATE / BEFORE DELETE ... FOR EACH ROW on
audit_auditlog) keep covering every row, runtime errors included.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0004_allow_actor_set_null"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("create", "Create"),
                    ("update", "Update"),
                    ("archive", "Archive"),
                    ("bulk_import", "Bulk Import"),
                    ("runtime_error", "Runtime Error"),
                ],
                max_length=20,
            ),
        ),
    ]
