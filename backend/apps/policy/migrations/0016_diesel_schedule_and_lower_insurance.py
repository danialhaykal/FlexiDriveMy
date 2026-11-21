"""Audit batch 3 follow-ups to the operating-cost seed (0014 already ran, so
it is not edited):

  0a. Insurance defaults were too high. The "RM26 per RM1,000" figure was the
      pre-2017 tariff; Bank Negara liberalised motor tariffs in 2017 and
      insurers now set their own rates. A row is updated ONLY if it still
      equals its original seeded value (insurance 2.6000 AND the original
      source note), so an admin's own edit is never overwritten.
  0b. JPJ publishes a separate, higher DIESEL cc schedule (paultan.org,
      31 Dec 2006). It is seeded as its own fuel_schedule, and the petrol
      schedule's note (which said diesel was not modelled) is refreshed under
      the same only-if-unchanged rule.

A fresh database runs 0014 then this migration and ends up with exactly the
values a migrated one does. seed_current_defaults() additionally creates any
of these rows that are missing, with the current values, so an emptied table
can be re-seeded to the same result.
"""

import datetime
import importlib
from decimal import Decimal

from django.db import migrations

D = Decimal

_seed_0014 = importlib.import_module("apps.policy.migrations.0014_seed_operating_cost_rates")
ORIGINAL_RATE_SOURCE = _seed_0014.RATE_SOURCE
ORIGINAL_CC_SOURCE = _seed_0014.CC_SOURCE
ORIGINAL_INSURANCE_PERCENT = D("2.6000")

RATE_SOURCE = (
    "Planning estimate - edit in admin. Percentage of price, no no-claims discount (conservative). "
    "Insurers set their own rates since the 2017 liberalisation; anchored to published market examples "
    "(about RM4,000 for a BMW 3 Series; EVs 20-30% higher), not a tariff."
)
INSURANCE_PERCENT = {
    "petrol": D("1.8000"),
    "diesel": D("1.8000"),
    "mild_hybrid": D("1.8000"),
    "hybrid": D("1.8000"),
    "phev": D("2.0000"),
    "bev": D("2.3000"),
}
MAINTENANCE_PERCENT = {"petrol": "1.0000", "diesel": "1.0000", "mild_hybrid": "1.0000", "hybrid": "0.9000",
                       "phev": "1.1000", "bev": "0.7000"}

PETROL_SOURCE = (
    "JPJ private-car road tax schedule (petrol rates), Peninsular Malaysia, individual owner, in force since "
    "1 Jan 2007. Checked against StashAway 'Calculate road tax Malaysia' and paultan.org's 31 Dec 2006 "
    "article on the new rates - identical. Applied to petrol, mild hybrid, hybrid and PHEV. Diesel has its "
    "own schedule (fuel_schedule = diesel)."
)
DIESEL_SOURCE = (
    "JPJ DIESEL private-car road tax schedule, Peninsular Malaysia, from paultan.org's 31 Dec 2006 article on "
    "the rates in force from 1 Jan 2007 (the article stops at 5,000 cc, so there is no diesel band above it). "
    "SINGLE SOURCE - verify before relying on it: StashAway's 2026 guide describes no separate diesel "
    "schedule, and ecentral.my describes a ~50% diesel surcharge (RM380 -> RM570 at 2,000 cc) that "
    "disagrees with this table (RM780 at 2,000 cc) and says it does not apply to diesel SUVs/4WDs."
)

# (min_cc, max_cc, base, threshold_cc, per_cc_rate) - paultan.org, 31 Dec 2006. Ranges in the article, e.g.
# "1,601-1,800 cc: RM400.80 to RM560", are base + (cc - threshold) * rate: 400 + 1 * 0.80 = 400.80 at 1,601 cc
# and 400 + 200 * 0.80 = 560 at 1,800 cc.
DIESEL_BANDS = [
    (0, 1000, "20.00", 0, "0.00"),
    (1001, 1200, "130.00", 0, "0.00"),
    (1201, 1400, "140.00", 0, "0.00"),
    (1401, 1600, "180.00", 0, "0.00"),
    (1601, 1800, "400.00", 1600, "0.80"),
    (1801, 2000, "560.00", 1800, "1.10"),
    (2001, 2500, "780.00", 2000, "2.20"),
    (2501, 3000, "1880.00", 2500, "6.00"),
    (3001, 5000, "4880.00", 3000, "10.80"),
]


def lower_default_insurance_rates(apps, schema_editor):
    """Only rows still equal to their original seeded value are touched."""
    OperatingCostRate = apps.get_model("policy", "OperatingCostRate")
    for powertrain, percent in INSURANCE_PERCENT.items():
        OperatingCostRate.objects.filter(
            powertrain=powertrain, is_active=True,
            insurance_rate_percent=ORIGINAL_INSURANCE_PERCENT, source_note=ORIGINAL_RATE_SOURCE,
        ).update(insurance_rate_percent=percent, source_note=RATE_SOURCE)


def refresh_petrol_source_note(apps, schema_editor):
    RoadTaxCcBand = apps.get_model("policy", "RoadTaxCcBand")
    RoadTaxCcBand.objects.filter(fuel_schedule="petrol", source_note=ORIGINAL_CC_SOURCE).update(
        source_note=PETROL_SOURCE
    )


def seed_current_defaults(apps, schema_editor):
    """Create any missing row with the CURRENT values (a no-op on a database
    that already has them)."""
    RoadTaxCcBand = apps.get_model("policy", "RoadTaxCcBand")
    OperatingCostRate = apps.get_model("policy", "OperatingCostRate")
    for min_cc, max_cc, base, threshold, per_cc in DIESEL_BANDS:
        RoadTaxCcBand.objects.get_or_create(
            fuel_schedule="diesel", min_cc=min_cc, is_active=True,
            defaults={
                "max_cc": max_cc, "base_amount": D(base), "threshold_cc": threshold, "per_cc_rate": D(per_cc),
                "source_note": DIESEL_SOURCE, "effective_from": datetime.date(2007, 1, 1),
            },
        )
    for powertrain, percent in INSURANCE_PERCENT.items():
        OperatingCostRate.objects.get_or_create(
            powertrain=powertrain, is_active=True,
            defaults={
                "insurance_rate_percent": percent, "maintenance_rate_percent": D(MAINTENANCE_PERCENT[powertrain]),
                "maintenance_floor_annual": D("1200.00"), "source_note": RATE_SOURCE,
                "effective_from": datetime.date(2026, 10, 7),
            },
        )


def forwards(apps, schema_editor):
    lower_default_insurance_rates(apps, schema_editor)
    refresh_petrol_source_note(apps, schema_editor)
    seed_current_defaults(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("policy", "0015_road_tax_fuel_schedule"),
    ]

    operations = [
        # Reverse is a no-op: undoing it could overwrite rates an admin has
        # since edited.
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
