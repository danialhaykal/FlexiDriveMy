from decimal import Decimal

from django.db import migrations

# Illustrative placeholder figures (not sourced from an official JPJ/
# insurer schedule) - banded by engine capacity (kW), matching the project spec's
# ML feature vector unit. Replace with verified Malaysian road tax /
# insurance / maintenance figures before relying on these for real users.
BANDS = [
    (Decimal("0.10"), Decimal("70.00"), Decimal("90.00"), Decimal("1500.00"), Decimal("800.00")),
    (Decimal("70.01"), Decimal("100.00"), Decimal("380.00"), Decimal("2200.00"), Decimal("1200.00")),
    (Decimal("100.01"), Decimal("140.00"), Decimal("1000.00"), Decimal("3200.00"), Decimal("1800.00")),
    (Decimal("140.01"), Decimal("200.00"), Decimal("2500.00"), Decimal("4500.00"), Decimal("2500.00")),
    (Decimal("200.01"), Decimal("500.00"), Decimal("6000.00"), Decimal("7000.00"), Decimal("4000.00")),
]


def seed_bands(apps, schema_editor):
    OperatingCostBand = apps.get_model("policy", "OperatingCostBand")
    for min_kw, max_kw, road_tax, insurance, maintenance in BANDS:
        OperatingCostBand.objects.get_or_create(
            min_engine_capacity_kw=min_kw,
            max_engine_capacity_kw=max_kw,
            defaults={
                "road_tax_annual": road_tax,
                "insurance_annual": insurance,
                "maintenance_annual": maintenance,
            },
        )


def unseed_bands(apps, schema_editor):
    OperatingCostBand = apps.get_model("policy", "OperatingCostBand")
    for min_kw, max_kw, *_ in BANDS:
        OperatingCostBand.objects.filter(min_engine_capacity_kw=min_kw, max_engine_capacity_kw=max_kw).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("policy", "0004_operatingcostband"),
    ]

    operations = [
        migrations.RunPython(seed_bands, reverse_code=unseed_bands),
    ]
