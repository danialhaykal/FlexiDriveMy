"""Seeds a small, realistic local-dev/demo dataset - DEV ONLY, not for
production. Idempotent and convergent: safe to re-run, and a later run
updates InterestRate/VehicleModel rows that already exist to match this
file's current declared values (update_or_create, not
get_or_create(defaults=...) - the latter silently never updates an
existing row, which is exactly how the dev DB was still showing a stale
2.80% Toyota rate after that value had already been corrected here).

Creates: an admin user + a regular user (fixed dev credentials, printed at
the end), a handful of brands/vehicles with the F011 config (interest
rates) needed for F005/F006/F007's endpoints to actually return 200
instead of "missing config" 400s - useful for manual smoke-testing, demos,
and load testing. No subscription plans are seeded (audit batch 5): every
car's Subscription fee is estimated, and a plan is an optional provider quote.

GFV residuals are NOT seeded here any more (audit batch 4): the old flat
per-brand ResidualValueMatrix grid gave every brand the same residual. The
estimator (apps.policy.residuals) reads the baseline and powertrain
adjustments seeded by policy migration 0018; only the per-brand adjustment
rows are created here, because they are keyed by brand and a fresh database
has no brands when that migration runs. A residual override row is now
optional admin data, never seeded.
"""

from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import importlib

from django.apps import apps as django_apps

from apps.policy.models import InterestRate
from apps.users.models import User, UserRole
from apps.vehicles.models import Brand, BodySegment, Powertrain, VehicleModel

seed_brand_adjustments = importlib.import_module(
    "apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule"
).seed_brand_adjustments

DEV_ADMIN_EMAIL = "admin@flexidrivemy.local"
DEV_USER_EMAIL = "loadtest@flexidrivemy.local"
DEV_PASSWORD = "DevSeed_2026!"

# Locked to the FYP1 report's premium catalog scope (A1 Update Table 7:
# "Only support brand-new premium vehicle models (BMW, Mercedes-Benz,
# Lexus, Porsche, and Toyota) available in Malaysia") - see the project spec's
# "Catalog scope" note. tier_code values are the real, data-driven 1-5
# price tier each brand was assigned when the currently-deployed ML model
# was actually trained (apps/ml/data/README_real_data.md's "Brand -> tier
# table"), reused as-is from apps/vehicles/data_fixes.py's BRAND_TIERS -
# not recomputed or guessed. apps/depreciation/inference.py reads this
# field directly as the model's brand_code feature.
BRANDS = [
    {"name": "BMW", "tier_code": "2"},
    {"name": "Mercedes-Benz", "tier_code": "2"},
    {"name": "Lexus", "tier_code": "1"},
    {"name": "Porsche", "tier_code": "1"},
    {"name": "Toyota", "tier_code": "1"},
]

# One realistic, genuinely premium-segment model per brand - illustrative
# current Malaysian OTR pricing (dev/demo seed data, not a report-cited
# figure), anchored against A3 Update.pdf's own interface mockup example
# (RM 294,200 OTR, 3.10% p.a.) for the Lexus ES row below. Toyota is
# specifically the Alphard, not a Vios/Yaris - see
# apps/ml/data/README_real_data.md's own note that this dataset's real
# Toyota listings skew toward higher-value models (Harrier/Alphard/
# Vellfire), independently confirming this platform's Toyota should mean
# those premium models.
#
# Values match what apply_catalog_corrections (audit batch 1, 2026-10-07)
# leaves in the production-like dev DB, so a fresh seed agrees with it.
# engine_capacity_kw is POWER OUTPUT in kW (legacy field name); engine
# displacement (cc) and powertrain are separate fields - the new-vehicle
# contract in the project spec. The Lexus ES 250 Luxury's old RM294,200 is the
# A3 Update mockup figure quoted above; its current price is RM356,888. The
# Alphard 2.5L is no longer sold new in Malaysia, so the seed carries the
# 2.4 Executive Lounge that replaced it.
VEHICLES = [
    {"brand": "BMW", "name": "3 Series", "trim": "320i Sport", "body_segment": BodySegment.SEDAN, "msrp": "265800.00", "engine_capacity_kw": "135.00", "engine_capacity_cc": 1998, "powertrain": Powertrain.PETROL, "model_year": 2025},
    {"brand": "Mercedes-Benz", "name": "C-Class", "trim": "C200 Avantgarde", "body_segment": BodySegment.SEDAN, "msrp": "292888.00", "engine_capacity_kw": "150.00", "engine_capacity_cc": 1496, "powertrain": Powertrain.MILD_HYBRID, "model_year": 2026},
    {"brand": "Lexus", "name": "ES", "trim": "250 Luxury", "body_segment": BodySegment.SEDAN, "msrp": "356888.00", "engine_capacity_kw": "151.00", "engine_capacity_cc": 2487, "powertrain": Powertrain.PETROL, "model_year": None},
    {"brand": "Porsche", "name": "Macan", "trim": "Base", "body_segment": BodySegment.SUV, "msrp": "469000.00", "engine_capacity_kw": "195.00", "engine_capacity_cc": 1984, "powertrain": Powertrain.PETROL, "model_year": None},
    {"brand": "Toyota", "name": "Alphard", "trim": "2.4 Executive Lounge", "body_segment": BodySegment.MPV, "msrp": "548000.00", "engine_capacity_kw": "201.53", "engine_capacity_cc": 2393, "powertrain": Powertrain.PETROL, "model_year": 2026},
]

# Illustrative annual campaign flat rates per brand - A3 Update.pdf's own
# interface mockup cites 3.10% p.a. as an example, used here for Lexus
# (paired with that same mockup's RM 294,200 OTR example above).
INTEREST_RATES = {
    "BMW": "2.8000",
    "Mercedes-Benz": "2.9000",
    "Lexus": "3.1000",
    "Porsche": "3.5000",
    "Toyota": "2.5000",
}


class Command(BaseCommand):
    help = "Seed a small local-dev/demo dataset (users, brands, vehicles, F011 rates). Idempotent."

    def handle(self, *args, **options):
        # This creates accounts with a fixed, source-committed password -
        # never let it run anywhere DEBUG is off.
        if not settings.DEBUG:
            raise CommandError("seed_dev_data refuses to run with DEBUG=False (creates known-password accounts).")

        admin, created = User.objects.get_or_create(
            email=DEV_ADMIN_EMAIL, defaults={"role": UserRole.ADMIN, "is_staff": True, "is_superuser": True}
        )
        if created:
            admin.set_password(DEV_PASSWORD)
            admin.save()

        user, created = User.objects.get_or_create(email=DEV_USER_EMAIL, defaults={"role": UserRole.USER})
        if created:
            user.set_password(DEV_PASSWORD)
            user.save()

        brands = {}
        for row in BRANDS:
            brand, _ = Brand.objects.get_or_create(name=row["name"], defaults={"tier_code": row["tier_code"]})
            brands[row["name"]] = brand
            InterestRate.objects.update_or_create(
                brand=brand, is_active=True, defaults={"rate_percent": Decimal(INTEREST_RATES[row["name"]])}
            )
        # Residuals are no longer keyed per brand (audit batch 4): the
        # estimator (apps.policy.residuals) reads the baseline and the
        # powertrain adjustments that policy migration 0018 seeds. Brand
        # adjustments are keyed by brand, so a fresh database gets them here,
        # now that its brands exist (a no-op where they already do).
        seed_brand_adjustments(django_apps)

        vehicles = []
        for row in VEHICLES:
            # update_or_create, not get_or_create(defaults=...): the latter
            # never updates an existing row, so a corrected MSRP/spec here
            # would never reach an already-seeded DB (same reason as the
            # rate/residual rows above). is_active is deliberately NOT in
            # defaults, so re-seeding never un-archives a vehicle.
            vehicle, _ = VehicleModel.objects.update_or_create(
                brand=brands[row["brand"]], name=row["name"], trim=row["trim"],
                defaults={
                    "body_segment": row["body_segment"],
                    "msrp": Decimal(row["msrp"]),
                    "engine_capacity_kw": Decimal(row["engine_capacity_kw"]),
                    "engine_capacity_cc": row["engine_capacity_cc"],
                    "powertrain": row["powertrain"],
                    "model_year": row["model_year"],
                },
            )
            vehicles.append(vehicle)
            # No SubscriptionPlan is created (audit batch 5): the old seed
            # filled every plan with MSRP / 40, a formula rather than provider
            # data. apps.policy.subscription_pricing now estimates every car's
            # Subscription fee from its own residual, running costs and the
            # SubscriptionPolicy seeded by policy migration 0020; a plan is
            # only an optional provider-quote override an admin keys in.
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(brands)} brands and {len(vehicles)} vehicles "
            "(GFV residuals are estimated, not keyed: no residual override rows are created)."
        ))
        self.stdout.write(self.style.SUCCESS(
            f"Dev admin: {DEV_ADMIN_EMAIL} / {DEV_PASSWORD}\n"
            f"Dev user:  {DEV_USER_EMAIL} / {DEV_PASSWORD}\n"
            f"First vehicle id: {vehicles[0].id} ({vehicles[0]})"
        ))
