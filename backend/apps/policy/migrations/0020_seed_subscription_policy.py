"""Audit batch 5 seed (the schema is 0019): the single SubscriptionPolicy row
apps.policy.subscription_pricing prices every Subscription with.

Every value is a PLANNING ASSUMPTION, not provider data - real subscription
terms vary by provider - and the row's source_note says so. Idempotent and
never overwrites an admin edit: the row is only created when no ACTIVE policy
exists, and an existing one is never updated.
"""

import datetime
from decimal import Decimal

from django.db import migrations

D = Decimal

SOURCE_NOTE = "Planning estimate - edit in admin. Real subscription terms vary by provider."
VALUES = {
    "min_tenure_months": 12,
    "max_tenure_months": 36,
    "funding_rate_percent": D("4.5000"),
    "margin_percent": D("12.0000"),
    "deposit_months": D("2.00"),
    "very_high_km_cap": 40000,
}


def seed_subscription_policy(apps_registry):
    SubscriptionPolicy = apps_registry.get_model("policy", "SubscriptionPolicy")
    if SubscriptionPolicy.objects.filter(is_active=True).exists():
        return
    SubscriptionPolicy.objects.create(source_note=SOURCE_NOTE, effective_from=datetime.date(2026, 10, 7), **VALUES)


def forwards(apps, schema_editor):
    seed_subscription_policy(apps)


class Migration(migrations.Migration):

    dependencies = [
        ("policy", "0019_subscription_policy"),
    ]

    operations = [
        # Reverse is a no-op: undoing it could delete a policy an admin has since edited.
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
