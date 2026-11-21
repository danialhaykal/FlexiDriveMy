"""Plain, importable helpers backing one-off data migrations for
apps/vehicles/models.py::Brand and VehicleModel.

Kept separate from the migration files themselves - a migration module's
filename starts with a digit (e.g. 0005_apply_real_brand_tiers.py) so it
can't be imported by a normal `import` statement - so this logic stays
directly unit-testable (see apps/vehicles/tests/test_data_fixes.py)
without needing to load migration files or replay the migration graph.
"""

# Brands seeded by the pre-fix seed_dev_data.py that are now out of the
# FYP1 report's locked premium catalog scope (A1 Update Table 7: BMW,
# Mercedes-Benz, Lexus, Porsche, Toyota only - see the project spec's "Catalog
# scope" note). Toyota itself stays in scope, but its old seed vehicle
# (a Vios) doesn't - see soft_delete_out_of_scope_catalog_rows below.
OUT_OF_SCOPE_BRAND_NAMES = ["Perodua", "Honda"]
OUT_OF_SCOPE_TOYOTA_VEHICLE_NAMES = ["Vios"]

# The real, data-driven 1-5 price tier each of these 25 brands was
# assigned when apps/ml/management/commands/build_real_ml_dataset.py
# built the dataset the currently-deployed model was actually trained on
# - see apps/ml/data/README_real_data.md's "Brand -> tier table"
# (tier 1 = highest median resale price .. tier 5 = lowest). Brands not
# in this table have no real data to base a tier on, so they're left
# untouched rather than guessed - see apply_real_brand_tiers below.
BRAND_TIERS = {
    "land rover": "1",
    "lexus": "1",
    "mini": "1",
    "porsche": "1",
    "toyota": "1",
    "bmw": "2",
    "ford": "2",
    "mercedes-benz": "2",
    "mitsubishi": "2",
    "volvo": "2",
    "audi": "3",
    "honda": "3",
    "mazda": "3",
    "suzuki": "3",
    "volkswagen": "3",
    "haval": "4",
    "hyundai": "4",
    "isuzu": "4",
    "nissan": "4",
    "subaru": "4",
    "kia": "5",
    "perodua": "5",
    "peugeot": "5",
    "proton": "5",
    "ssangyong": "5",
}


def soft_delete_out_of_scope_catalog_rows(brand_model, vehicle_model, interest_rate_model, residual_matrix_model):
    """Deactivates the specific dev-only Brand/VehicleModel/InterestRate/
    ResidualValueMatrix rows that predate the FYP1 catalog-scope fix (the
    old seed_dev_data.py seeded Perodua/Honda and a Toyota Vios, out of
    the locked BMW/Mercedes-Benz/Lexus/Porsche/Toyota premium scope - see
    the project spec's "Catalog scope" note and this command's current BRANDS/
    VEHICLES lists).

    Soft delete only (is_active=False), never a hard delete - Brand and
    VehicleModel are PROTECTed foreign keys (InterestRate/
    ResidualValueMatrix/VehicleModel from Brand; SavedScenario-style
    references from VehicleModel), and this project's own rule is
    soft-delete-only for exactly that reason - existing saved comparisons
    must never be orphaned. The catalog browse endpoint already filters
    is_active=True, so this is what actually removes them from what a
    user sees; `model_class.objects.all()` (e.g. the admin CRUD view, or
    a raw query) still shows them, by design.

    Models are passed in rather than imported directly so this also works
    against the historical snapshots a RunPython migration receives via
    apps.get_model(). Returns (brands_deactivated, vehicles_deactivated).
    A no-op wherever none of these specific rows exist (already cleaned
    up, or an environment that never seeded them in the first place).
    """
    vehicles_deactivated = vehicle_model.objects.filter(
        brand__name__in=OUT_OF_SCOPE_BRAND_NAMES, is_active=True
    ).update(is_active=False)
    vehicles_deactivated += vehicle_model.objects.filter(
        brand__name="Toyota", name__in=OUT_OF_SCOPE_TOYOTA_VEHICLE_NAMES, is_active=True
    ).update(is_active=False)

    interest_rate_model.objects.filter(brand__name__in=OUT_OF_SCOPE_BRAND_NAMES, is_active=True).update(
        is_active=False
    )
    residual_matrix_model.objects.filter(brand__name__in=OUT_OF_SCOPE_BRAND_NAMES, is_active=True).update(
        is_active=False
    )

    brands_deactivated = brand_model.objects.filter(name__in=OUT_OF_SCOPE_BRAND_NAMES, is_active=True).update(
        is_active=False
    )
    return brands_deactivated, vehicles_deactivated


def apply_real_brand_tiers(model):
    """`model` is Brand - either the real current model class, or the
    historical snapshot a RunPython migration receives via
    apps.get_model(). Matches by name, case-insensitively, against the
    real 25-brand table above; a brand with no match is left completely
    untouched - there's no real data to base a tier on for those, so this
    never guesses or invents a value. Returns the number of rows actually
    changed.
    """
    updated = 0
    for brand in model.objects.all():
        tier = BRAND_TIERS.get(brand.name.strip().lower())
        if tier is None or brand.tier_code == tier:
            continue
        brand.tier_code = tier
        brand.save(update_fields=["tier_code"])
        updated += 1
    return updated
