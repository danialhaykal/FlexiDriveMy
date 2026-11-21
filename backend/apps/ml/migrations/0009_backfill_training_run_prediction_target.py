"""ML batch 1: give every existing training run its own prediction_target, by
explicit rules (the serializer used to work the MAE unit out on every read):

- every recorded MAE <= 1 -> value_retention_ratio (a fraction of the price
  cannot exceed 1, while an RM error on a car's price is in the thousands);
- any other run with metrics -> raw_resale_price;
- a run with no metrics -> left blank (unknown).

Only blank targets are filled, so a re-run (or a run recorded after 0008) is
never relabelled.
"""

from django.db import migrations

VALUE_RETENTION_RATIO = "value_retention_ratio"
RAW_RESALE_PRICE = "raw_resale_price"


def target_for(rf_mae, gb_mae):
    values = [v for v in (rf_mae, gb_mae) if v is not None]
    if not values:
        return ""
    return VALUE_RETENTION_RATIO if all(v <= 1 for v in values) else RAW_RESALE_PRICE


def backfill(apps, schema_editor):
    MLTrainingRun = apps.get_model("ml", "MLTrainingRun")
    for run in MLTrainingRun.objects.filter(prediction_target=""):
        target = target_for(run.rf_mae, run.gb_mae)
        if target:
            MLTrainingRun.objects.filter(pk=run.pk).update(prediction_target=target)


def clear(apps, schema_editor):
    MLTrainingRun = apps.get_model("ml", "MLTrainingRun")
    MLTrainingRun.objects.filter(prediction_target__in=[VALUE_RETENTION_RATIO, RAW_RESALE_PRICE]).update(
        prediction_target=""
    )


class Migration(migrations.Migration):

    dependencies = [
        ("ml", "0008_mltrainingrun_prediction_target_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_code=clear),
    ]
