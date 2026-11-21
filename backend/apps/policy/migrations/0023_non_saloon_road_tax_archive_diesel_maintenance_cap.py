"""Run 1 fix batch 3, data part 2 of 3 (C2, C4).

1. Seeds the JPJ Peninsular private NON-SALOON cc table (SUVs, MPVs,
   pick-ups...), from StashAway's 2026 road-tax guide.
2. Archives the diesel cc bands (is_active=False - kept for the audit trail,
   never deleted). They came from a single 2006 article; current sources
   (StashAway 2026, paultan's 2015 explainer - "applies to both petrol and
   diesel engines" - and the Carso calculator) describe no separate diesel
   schedule. Diesel now uses the same table as petrol for its class.
3. Re-labels the saloon rows' source note, but only where it still equals
   the note 0016 wrote (an admin's own edit is never overwritten).
4. Seeds a RM 8,000 maintenance cap on every active rate row that has none.

Idempotent: re-running changes nothing. Reverse is a no-op - undoing it could
overwrite values an admin has since edited.
"""

import datetime
import importlib
from decimal import Decimal

from django.db import migrations

D = Decimal

_seed_0016 = importlib.import_module("apps.policy.migrations.0016_diesel_schedule_and_lower_insurance")
PREVIOUS_SALOON_SOURCE = _seed_0016.PETROL_SOURCE

SALOON_SOURCE = (
    "JPJ private-car road tax, SALOON class, Peninsular Malaysia, in force since 1 Jan 2007. Checked against "
    "StashAway 'Calculate road tax Malaysia' (2026) and paultan.org's explainer - identical. Applies to petrol "
    "and diesel alike (no separate diesel schedule) and to mild hybrids, hybrids and PHEVs. Check MyJPJ for "
    "the car's exact registered class."
)
NON_SALOON_SOURCE = (
    "JPJ private-car road tax, NON-SALOON class (SUVs, MPVs, pick-ups...), Peninsular Malaysia, same for "
    "individual and company owners - StashAway 'Calculate road tax Malaysia' (2026). Applies to petrol and "
    "diesel alike. Check MyJPJ for the car's exact registered class (the VOC)."
)

# (min_cc, max_cc, base, threshold_cc, per_cc_rate) - StashAway 2026. The top
# band runs to 8,000 cc, the highest engine capacity a vehicle may have.
NON_SALOON_BANDS = [
    (0, 1000, "20.00", 0, "0.00"),
    (1001, 1200, "85.00", 0, "0.00"),
    (1201, 1400, "100.00", 0, "0.00"),
    (1401, 1600, "120.00", 0, "0.00"),
    (1601, 1800, "300.00", 1600, "0.30"),
    (1801, 2000, "360.00", 1800, "0.40"),
    (2001, 2500, "440.00", 2000, "0.80"),
    (2501, 3000, "840.00", 2500, "1.60"),
    (3001, 8000, "1640.00", 3000, "1.60"),
]

MAINTENANCE_CAP = D("8000.00")


def archive_diesel_bands(apps, schema_editor):
    RoadTaxCcBand = apps.get_model("policy", "RoadTaxCcBand")
    RoadTaxCcBand.objects.filter(fuel_schedule="diesel", is_active=True).update(is_active=False)


def relabel_saloon_rows(apps, schema_editor):
    RoadTaxCcBand = apps.get_model("policy", "RoadTaxCcBand")
    RoadTaxCcBand.objects.filter(
        fuel_schedule="petrol", vehicle_class="saloon", source_note=PREVIOUS_SALOON_SOURCE
    ).update(source_note=SALOON_SOURCE)


def seed_non_saloon_bands(apps, schema_editor):
    RoadTaxCcBand = apps.get_model("policy", "RoadTaxCcBand")
    for min_cc, max_cc, base, threshold, per_cc in NON_SALOON_BANDS:
        RoadTaxCcBand.objects.get_or_create(
            vehicle_class="non_saloon", min_cc=min_cc, is_active=True,
            defaults={
                "fuel_schedule": "petrol", "max_cc": max_cc, "base_amount": D(base), "threshold_cc": threshold,
                "per_cc_rate": D(per_cc), "source_note": NON_SALOON_SOURCE,
                "effective_from": datetime.date(2007, 1, 1),
            },
        )


def seed_maintenance_cap(apps, schema_editor):
    OperatingCostRate = apps.get_model("policy", "OperatingCostRate")
    OperatingCostRate.objects.filter(is_active=True, maintenance_cap_annual__isnull=True).update(
        maintenance_cap_annual=MAINTENANCE_CAP
    )


def forwards(apps, schema_editor):
    archive_diesel_bands(apps, schema_editor)
    relabel_saloon_rows(apps, schema_editor)
    seed_non_saloon_bands(apps, schema_editor)
    seed_maintenance_cap(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("policy", "0022_road_tax_vehicle_class_and_maintenance_cap"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
