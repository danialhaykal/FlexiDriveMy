"""Soft-deletes the specific dev-only Brand/VehicleModel/InterestRate/
ResidualValueMatrix rows that predate the FYP1 catalog-scope fix (the old
seed_dev_data.py seeded Perodua/Honda and a Toyota Vios, out of the
locked BMW/Mercedes-Benz/Lexus/Porsche/Toyota premium scope - A1 Update
Table 7, see the project spec's "Catalog scope" note).

Soft delete only (is_active=False), never a hard delete - see
apps/vehicles/data_fixes.py::soft_delete_out_of_scope_catalog_rows for
the full reasoning (kept there, not here, so it stays directly
unit-testable). A no-op in any environment that was always seeded (or
never seeded) with the new, in-scope brand list.
"""

from django.db import migrations

from apps.vehicles.data_fixes import soft_delete_out_of_scope_catalog_rows


def forwards(apps, schema_editor):
    Brand = apps.get_model("vehicles", "Brand")
    VehicleModel = apps.get_model("vehicles", "VehicleModel")
    InterestRate = apps.get_model("policy", "InterestRate")
    ResidualValueMatrix = apps.get_model("policy", "ResidualValueMatrix")
    soft_delete_out_of_scope_catalog_rows(Brand, VehicleModel, InterestRate, ResidualValueMatrix)


def backwards(apps, schema_editor):
    # Not meaningfully reversible: reactivating these would reintroduce
    # out-of-scope catalog data, exactly what this migration exists to
    # prevent.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0005_apply_real_brand_tiers"),
        ("policy", "0005_seed_operating_cost_bands"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
