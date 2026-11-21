"""QA audit C8 correction: the ProductionModel row deployed before this
batch (if any) was trained on raw resale_price, under the pre-C8
convention - 0005 added prediction_target but left it blank on that
existing row, which apps/depreciation/inference.py now treats as
"unknown, therefore incompatible" anyway (the safe default), but this
migration is explicit about WHY it's blank rather than leaving that
implicit: a row with a real, already-deployed model_file_path predates
the ratio-target convention entirely, so it's labelled
RAW_RESALE_PRICE - the accurate, not just conservative, description of
what's actually there.
"""

from django.db import migrations

from apps.ml.models import PredictionTarget


def backfill_legacy_prediction_target(apps, schema_editor):
    ProductionModel = apps.get_model("ml", "ProductionModel")
    ProductionModel.objects.filter(prediction_target="").exclude(model_file_path="").update(
        prediction_target=PredictionTarget.RAW_RESALE_PRICE
    )


def clear_prediction_target(apps, schema_editor):
    ProductionModel = apps.get_model("ml", "ProductionModel")
    ProductionModel.objects.filter(prediction_target=PredictionTarget.RAW_RESALE_PRICE).update(
        prediction_target=""
    )


class Migration(migrations.Migration):

    dependencies = [
        ("ml", "0005_productionmodel_prediction_target"),
    ]

    operations = [
        migrations.RunPython(backfill_legacy_prediction_target, reverse_code=clear_prediction_target),
    ]
