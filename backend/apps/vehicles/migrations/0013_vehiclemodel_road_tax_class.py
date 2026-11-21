"""Run 1 fix batch 3 (C2): every car gets a JPJ road-tax registration class.

Existing rows are set from their body segment (sedan/hatchback/coupe = saloon;
suv/mpv/pickup/van/crossover = non-saloon). The mapping is copied here rather
than imported so this migration keeps meaning what it meant when it ran.
"""

from django.db import migrations, models

SALOON_SEGMENTS = {"sedan", "hatchback", "coupe"}
NON_SALOON_SEGMENTS = {"suv", "mpv", "pickup", "van", "crossover"}


def set_class_from_body_segment(apps, schema_editor):
    VehicleModel = apps.get_model("vehicles", "VehicleModel")
    VehicleModel.objects.filter(road_tax_class="", body_segment__in=SALOON_SEGMENTS).update(road_tax_class="saloon")
    VehicleModel.objects.filter(road_tax_class="", body_segment__in=NON_SALOON_SEGMENTS).update(
        road_tax_class="non_saloon"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0012_vehicle_powertrain_and_engine_capacity_cc"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehiclemodel",
            name="road_tax_class",
            field=models.CharField(
                blank=True,
                choices=[("saloon", "Saloon"), ("non_saloon", "Non-saloon")],
                help_text="Use the class on the car's registration card (VOC). Body type is only the default.",
                max_length=20,
                verbose_name="road-tax class",
            ),
        ),
        # Reverse is a no-op: the column itself is dropped on the way back.
        migrations.RunPython(set_class_from_body_segment, migrations.RunPython.noop),
    ]
