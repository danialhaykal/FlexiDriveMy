"""Seeds the operating-cost rate tables (audit batch 2) so a fresh database
and production both get them. Idempotent: rows are matched on their natural
key and created only if missing, so re-running never duplicates a row or
overwrites a value an admin has since edited."""

import datetime
from decimal import Decimal

from django.db import migrations

D = Decimal

CC_SOURCE = (
    "JPJ private-car road tax schedule, Peninsular Malaysia, individual owner (petrol rates, in force since "
    "1 Jan 2007). Checked against StashAway 'Calculate road tax Malaysia' and paultan.org's 31 Dec 2006 "
    "article on the new rates - identical. Applied to petrol, mild hybrid, hybrid and PHEV (and diesel - "
    "note JPJ publishes a separate, higher diesel schedule that is NOT modelled here)."
)
EV_SOURCE = (
    "JPJ kW-based battery-electric road tax, effective 1 Jan 2026, Peninsular Malaysia, individual owner. "
    "Source: Carlist 'EV road tax Malaysia 2026'; checked against motorist.my (group minimum, maximum and "
    "per-10 kW increments agree). East Malaysia and Langkawi/Labuan concessions are not modelled."
)
RATE_SOURCE = (
    "Planning estimate - edit in admin. Insurance is a percentage of the vehicle's price with no no-claims "
    "discount applied (deliberately conservative); Bank Negara liberalised motor tariffs in 2017, so insurers "
    "set their own rates and no single published tariff exists. Maintenance is an assumed percentage of "
    "price with a floor."
)

# (min_cc, max_cc, base, threshold_cc, per_cc_rate)
CC_BANDS = [
    (0, 1000, "20.00", 0, "0.00"),
    (1001, 1200, "55.00", 0, "0.00"),
    (1201, 1400, "70.00", 0, "0.00"),
    (1401, 1600, "90.00", 0, "0.00"),
    (1601, 1800, "200.00", 1600, "0.40"),
    (1801, 2000, "280.00", 1800, "0.50"),
    (2001, 2500, "380.00", 2000, "1.00"),
    (2501, 3000, "880.00", 2500, "2.50"),
    (3001, 8000, "2130.00", 3000, "4.50"),
]

# (label, min_kw, max_kw, base, base_until_kw, increment_per_10kw)
EV_GROUPS = [
    ("A", "0.001", "100.000", "20.00", "50.00", "10.00"),
    ("B", "100.100", "210.000", "80.00", "110.00", "20.00"),
    ("C", "210.100", "310.000", "305.00", "220.00", "30.00"),
    ("D", "310.100", "410.000", "615.00", "320.00", "50.00"),
    ("E", "410.100", "510.000", "1140.00", "420.00", "100.00"),
    ("F", "510.100", "610.000", "2165.00", "520.00", "150.00"),
    ("G", "610.100", "710.000", "3690.00", "620.00", "200.00"),
    ("H", "710.100", "810.000", "5715.00", "720.00", "250.00"),
    ("I", "810.100", "910.000", "8240.00", "820.00", "300.00"),
    ("J", "910.100", "1010.000", "11265.00", "920.00", "350.00"),
    ("K", "1010.100", None, "20000.00", None, "0.00"),  # fixed amount
]

# powertrain -> (insurance %, maintenance %)
COST_RATES = {
    "petrol": ("2.6000", "1.0000"),
    "diesel": ("2.6000", "1.0000"),
    "mild_hybrid": ("2.6000", "1.0000"),
    "hybrid": ("2.6000", "0.9000"),
    "phev": ("2.6000", "1.1000"),
    "bev": ("2.6000", "0.7000"),
}
MAINTENANCE_FLOOR = "1200.00"


def seed_operating_cost_tables(apps, schema_editor):
    RoadTaxCcBand = apps.get_model("policy", "RoadTaxCcBand")
    EvRoadTaxGroup = apps.get_model("policy", "EvRoadTaxGroup")
    OperatingCostRate = apps.get_model("policy", "OperatingCostRate")

    for min_cc, max_cc, base, threshold, per_cc in CC_BANDS:
        RoadTaxCcBand.objects.get_or_create(
            min_cc=min_cc, is_active=True,
            defaults={
                "max_cc": max_cc, "base_amount": D(base), "threshold_cc": threshold, "per_cc_rate": D(per_cc),
                "source_note": CC_SOURCE, "effective_from": datetime.date(2007, 1, 1),
            },
        )
    for label, min_kw, max_kw, base, base_until, increment in EV_GROUPS:
        EvRoadTaxGroup.objects.get_or_create(
            label=label, is_active=True,
            defaults={
                "min_kw": D(min_kw), "max_kw": D(max_kw) if max_kw else None, "base_amount": D(base),
                "base_until_kw": D(base_until) if base_until else None, "increment_per_10kw": D(increment),
                "source_note": EV_SOURCE, "effective_from": datetime.date(2026, 1, 1),
            },
        )
    for powertrain, (insurance, maintenance) in COST_RATES.items():
        OperatingCostRate.objects.get_or_create(
            powertrain=powertrain, is_active=True,
            defaults={
                "insurance_rate_percent": D(insurance), "maintenance_rate_percent": D(maintenance),
                "maintenance_floor_annual": D(MAINTENANCE_FLOOR), "source_note": RATE_SOURCE,
                "effective_from": datetime.date(2026, 10, 7),
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("policy", "0013_operating_cost_rate_tables"),
    ]

    operations = [
        # Reverse is a no-op: removing the seed rows on rollback could delete
        # rates an admin has since edited.
        migrations.RunPython(seed_operating_cost_tables, migrations.RunPython.noop),
    ]
