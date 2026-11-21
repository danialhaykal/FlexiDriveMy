from decimal import Decimal

from django.db import migrations

DEFAULT_WEIGHTS = {
    "upfront_cash_preservation": Decimal("0.3400"),
    "maintenance_protection": Decimal("0.3300"),
    "ownership_equity": Decimal("0.3300"),
}


def seed_weights(apps, schema_editor):
    MCDACriteriaWeight = apps.get_model("policy", "MCDACriteriaWeight")
    for criterion, weight in DEFAULT_WEIGHTS.items():
        MCDACriteriaWeight.objects.get_or_create(criterion=criterion, defaults={"default_weight": weight})


def unseed_weights(apps, schema_editor):
    MCDACriteriaWeight = apps.get_model("policy", "MCDACriteriaWeight")
    MCDACriteriaWeight.objects.filter(criterion__in=DEFAULT_WEIGHTS.keys()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("policy", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_weights, reverse_code=unseed_weights),
    ]
