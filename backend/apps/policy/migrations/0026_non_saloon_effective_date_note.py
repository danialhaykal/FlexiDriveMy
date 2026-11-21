"""Run 1 fix batch 5 (step 6.3): the non-saloon road-tax rows' source note
says the effective date is an assumption. StashAway's 2026 table gives no
start date; 0023 seeded 1 Jan 2007 to match the saloon table.

Only rows whose note is still exactly what 0023 wrote are touched (an admin's
own edit is never overwritten); no rate or date changes. Idempotent.
"""

import importlib

from django.db import migrations

_seed_0023 = importlib.import_module("apps.policy.migrations.0023_non_saloon_road_tax_archive_diesel_maintenance_cap")
EFFECTIVE_DATE_NOTE = "Effective date not stated by the source; 1 Jan 2007 assumed to match the saloon table."
NOTED_SOURCE = f"{_seed_0023.NON_SALOON_SOURCE} {EFFECTIVE_DATE_NOTE}"


def add_effective_date_note(apps, schema_editor):
    RoadTaxCcBand = apps.get_model("policy", "RoadTaxCcBand")
    RoadTaxCcBand.objects.filter(vehicle_class="non_saloon", source_note=_seed_0023.NON_SALOON_SOURCE).update(
        source_note=NOTED_SOURCE
    )


class Migration(migrations.Migration):

    dependencies = [
        ("policy", "0025_operating_cost_band_deprecated_title"),
    ]

    operations = [
        migrations.RunPython(add_effective_date_note, migrations.RunPython.noop),
    ]
