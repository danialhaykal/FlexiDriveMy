"""Run 1 fix batch 3, schema part 1 of 3 (C2, C4).

- RoadTaxCcBand.vehicle_class: the JPJ registration class each band belongs
  to (existing rows are saloon). The old one-active-band-per-(fuel schedule,
  min cc) rule is dropped here; 0024 adds one-active-band-per-(class, min cc)
  once 0023 has archived the diesel rows (which would otherwise clash with
  the saloon bands).
- OperatingCostRate.maintenance_cap_annual: an optional planning-assumption
  ceiling on maintenance.
"""

import django.core.validators
from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("policy", "0021_contract_rule_subscription_early_return_wording"),
        ("vehicles", "0013_vehiclemodel_road_tax_class"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="roadtaxccband",
            name="unique_active_road_tax_cc_band_per_schedule_min",
        ),
        migrations.AddField(
            model_name="roadtaxccband",
            name="vehicle_class",
            field=models.CharField(
                choices=[("saloon", "Saloon"), ("non_saloon", "Non-saloon")], default="saloon", max_length=20
            ),
        ),
        migrations.AlterModelOptions(
            name="roadtaxccband",
            options={"ordering": ["vehicle_class", "min_cc"]},
        ),
        migrations.AddField(
            model_name="operatingcostrate",
            name="maintenance_cap_annual",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text=(
                    "Planning assumption, not a tariff. Maintenance is never costed above this; leave empty for "
                    "no cap."
                ),
                max_digits=12,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="maintenance cap (RM a year)",
            ),
        ),
    ]
