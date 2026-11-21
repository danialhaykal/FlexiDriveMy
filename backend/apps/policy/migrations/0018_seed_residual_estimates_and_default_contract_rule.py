"""Audit batch 4 seed data (the schema is 0017):

  - ResidualBaseline: share of price retained by tenure x mileage band. The
    36/48/60-month values are the figures the old flat per-brand matrix used
    (36 months / standard = 0.50 is the project spec's worked GFV reference case);
    12 and 24 months are new.
  - ResidualAdjustment: brand and powertrain shifts, in ratio points.
  - The single default ContractPenaltyRule (brand = null).

Every row is a PLANNING ASSUMPTION - directional, not market data (real GFV
residuals are set by the lender) - and says so in its source_note.

Idempotent and never overwrites an admin edit: a row is only created when no
ACTIVE row exists for its key, and existing rows are never updated. Brand
adjustments are keyed by brand, so they are only created for brands that
exist when this runs; seed_brand_adjustments() is public so a freshly
created database (seed_dev_data) can add them after it creates its brands.
"""

import datetime
from decimal import Decimal

from django.db import migrations

D = Decimal

EFFECTIVE_FROM = datetime.date(2026, 10, 7)
NOTE = "Planning estimate - directional, edit in admin. Real GFV residuals are set by the lender."

MILEAGE_BANDS = ["low", "standard", "high", "very_high"]
BASELINE = {
    12: ["0.80", "0.77", "0.74", "0.70"],
    24: ["0.64", "0.61", "0.57", "0.52"],
    36: ["0.55", "0.50", "0.45", "0.40"],
    48: ["0.47", "0.42", "0.38", "0.33"],
    60: ["0.40", "0.35", "0.31", "0.27"],
}
BRAND_ADJUSTMENTS = {
    "Toyota": "0.06",
    "Lexus": "0.04",
    "Porsche": "0.05",
    "BMW": "0.00",
    "Mercedes-Benz": "0.00",
    "Volvo": "-0.04",
}
POWERTRAIN_ADJUSTMENTS = {
    "bev": "-0.08",
    "phev": "-0.03",
    "petrol": "0.00",
    "diesel": "0.00",
    "mild_hybrid": "0.00",
    "hybrid": "0.00",
}
BRAND_NOTES = {
    "Toyota": NOTE + " Toyota (Alphard/Vellfire) is known to hold its value well in Malaysia.",
    "Lexus": NOTE + " Lexus is known to hold its value better than the average premium brand.",
    "Porsche": NOTE + " Porsche is known to hold its value well in Malaysia.",
    "Volvo": NOTE + " Some Volvos are known to depreciate faster than German peers.",
}
POWERTRAIN_NOTES = {
    "bev": NOTE + " Electric cars are known to depreciate faster than petrol ones.",
    "phev": NOTE + " Plug-in hybrids are assumed to depreciate somewhat faster than petrol ones.",
}

DEFAULT_RULE = {
    "excess_mileage_charge_per_km": D("0.50"),
    "early_termination_months": D("3.00"),
    "wear_tear_tolerance_description": (
        "Normal wear and tear for the car's age and mileage is accepted; damage beyond that (deep dents, torn "
        "upholstery, tyres below the legal tread depth, missing items) is billed at repair cost on return."
    ),
    "source_note": "Planning estimate - typical terms vary by provider; edit in admin.",
}


def seed_baseline(apps_registry):
    ResidualBaseline = apps_registry.get_model("policy", "ResidualBaseline")
    for tenure, ratios in BASELINE.items():
        for band, ratio in zip(MILEAGE_BANDS, ratios):
            ResidualBaseline.objects.get_or_create(
                tenure_months=tenure, mileage_band=band, is_active=True,
                defaults={"ratio": D(ratio), "source_note": NOTE, "effective_from": EFFECTIVE_FROM},
            )


def seed_powertrain_adjustments(apps_registry):
    ResidualAdjustment = apps_registry.get_model("policy", "ResidualAdjustment")
    for powertrain, delta in POWERTRAIN_ADJUSTMENTS.items():
        if ResidualAdjustment.objects.filter(brand__isnull=True, powertrain=powertrain, is_active=True).exists():
            continue
        ResidualAdjustment.objects.create(
            brand=None, powertrain=powertrain, delta_points=D(delta),
            source_note=POWERTRAIN_NOTES.get(powertrain, NOTE), effective_from=EFFECTIVE_FROM,
        )


def seed_brand_adjustments(apps_registry):
    """Create the brand rows for whichever of the named brands exist."""
    Brand = apps_registry.get_model("vehicles", "Brand")
    ResidualAdjustment = apps_registry.get_model("policy", "ResidualAdjustment")
    for name, delta in BRAND_ADJUSTMENTS.items():
        brand = Brand.objects.filter(name=name).first()
        if brand is None or ResidualAdjustment.objects.filter(brand=brand, is_active=True).exists():
            continue
        ResidualAdjustment.objects.create(
            brand=brand, powertrain="", delta_points=D(delta),
            source_note=BRAND_NOTES.get(name, NOTE), effective_from=EFFECTIVE_FROM,
        )


def seed_default_contract_rule(apps_registry):
    ContractPenaltyRule = apps_registry.get_model("policy", "ContractPenaltyRule")
    if ContractPenaltyRule.objects.filter(brand__isnull=True, is_active=True).exists():
        return
    ContractPenaltyRule.objects.create(brand=None, **DEFAULT_RULE)


def forwards(apps, schema_editor):
    seed_baseline(apps)
    seed_powertrain_adjustments(apps)
    seed_brand_adjustments(apps)
    seed_default_contract_rule(apps)


class Migration(migrations.Migration):

    dependencies = [
        ("policy", "0017_residual_estimator_and_default_contract_rule"),
        ("vehicles", "0008_alter_vehiclemodel_engine_capacity_kw_and_more"),
    ]

    operations = [
        # Reverse is a no-op: undoing it could delete rows an admin has since edited.
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
