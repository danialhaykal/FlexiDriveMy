"""Run 1 fix batch 3 (C3): the buyer's No-Claim Discount. Existing profiles
get 0%, so every screen reads exactly as before until the buyer sets it."""

from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("profiles", "0002_mileage_band_uses_policy_bands"),
    ]

    operations = [
        migrations.AddField(
            model_name="financialprofile",
            name="ncd_percent",
            field=models.DecimalField(
                choices=[
                    (Decimal("0.00"), "0%"),
                    (Decimal("25.00"), "25%"),
                    (Decimal("30.00"), "30%"),
                    (Decimal("38.33"), "38.33%"),
                    (Decimal("45.00"), "45%"),
                    (Decimal("55.00"), "55%"),
                ],
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="Check your last insurance renewal notice. New drivers start at 0%.",
                max_digits=5,
                verbose_name="No-Claim Discount (NCD) on your current car insurance",
            ),
        ),
    ]
