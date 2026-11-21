"""Run 1 fix batch 3, part 3 of 3: one ACTIVE cc band per (registration
class, starting cc). Added only after 0023 archived the diesel rows."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("policy", "0023_non_saloon_road_tax_archive_diesel_maintenance_cap"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="roadtaxccband",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("vehicle_class", "min_cc"),
                name="unique_active_road_tax_cc_band_per_class_min",
            ),
        ),
    ]
