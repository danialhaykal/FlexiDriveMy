"""Populate Brand.tier_code with the real, data-driven 1-5 price tier
each brand was assigned when the currently-deployed ML model was
actually trained (see apps/ml/data/README_real_data.md's "Brand -> tier
table"). Fixes a real inference bug: apps/depreciation/inference.py was
feeding the model vehicle.brand_id (Django's unrelated auto-increment
primary key) instead of this field, and this field itself had never been
populated with the real tier values - only arbitrary placeholder letters
(see apps/vehicles/management/commands/seed_dev_data.py's pre-fix BRANDS
list). See apps/vehicles/data_fixes.py for the matching logic and the
full reasoning (kept there, not here, so it stays directly unit-testable).

Brands not in the real 25-brand table are left untouched - there's no
real data to base a tier on for those.
"""

from django.db import migrations

from apps.vehicles.data_fixes import apply_real_brand_tiers


def forwards(apps, schema_editor):
    Brand = apps.get_model("vehicles", "Brand")
    apply_real_brand_tiers(Brand)


def backwards(apps, schema_editor):
    # Not meaningfully reversible: the original placeholder letters
    # ("A"/"B"/"C") weren't real data either, so there's nothing correct
    # to revert to.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0004_remove_vehiclemodel_unique_vehicle_model_per_brand_name_trim_year_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
