"""Confirms the real-brand-tier data fix (apps/vehicles/data_fixes.py and
apps/vehicles/migrations/0005_apply_real_brand_tiers.py) applies the real,
documented tier to every matching brand and leaves everything else
untouched - the fix for apps/depreciation/inference.py feeding the model
vehicle.brand_id instead of Brand.tier_code.
"""

import pytest

from apps.vehicles.data_fixes import BRAND_TIERS, apply_real_brand_tiers
from apps.vehicles.models import Brand

pytestmark = pytest.mark.django_db


def test_every_brand_in_the_real_table_gets_its_documented_tier():
    # A representative spread across all 5 tiers, including the exact
    # three brands this platform actually seeds for dev/demo.
    toyota = Brand.objects.create(name="Toyota", tier_code="A")
    honda = Brand.objects.create(name="Honda", tier_code="A")
    perodua = Brand.objects.create(name="Perodua", tier_code="B")
    bmw = Brand.objects.create(name="BMW", tier_code="A")
    hyundai = Brand.objects.create(name="Hyundai", tier_code="A")

    updated = apply_real_brand_tiers(Brand)

    toyota.refresh_from_db()
    honda.refresh_from_db()
    perodua.refresh_from_db()
    bmw.refresh_from_db()
    hyundai.refresh_from_db()

    assert toyota.tier_code == "1"
    assert honda.tier_code == "3"
    assert perodua.tier_code == "5"
    assert bmw.tier_code == "2"
    assert hyundai.tier_code == "4"
    assert updated == 5


def test_matching_is_case_insensitive():
    brand = Brand.objects.create(name="toyota", tier_code="A")

    apply_real_brand_tiers(Brand)

    brand.refresh_from_db()
    assert brand.tier_code == "1"


def test_brand_not_in_the_real_table_is_left_untouched():
    brand = Brand.objects.create(name="SomeNewLocalBrand", tier_code="A")

    updated = apply_real_brand_tiers(Brand)

    brand.refresh_from_db()
    assert brand.tier_code == "A"
    assert updated == 0


def test_a_brand_already_at_its_correct_tier_is_not_rewritten_again():
    Brand.objects.create(name="Toyota", tier_code="1")

    updated = apply_real_brand_tiers(Brand)

    assert updated == 0


def test_brand_tiers_table_matches_the_documented_20_brand_table_exactly():
    # Guards against a silent typo drifting from
    # apps/ml/data/README_real_data.md's own table.
    expected = {
        "land rover": "1", "lexus": "1", "mini": "1", "porsche": "1", "toyota": "1",
        "bmw": "2", "ford": "2", "mercedes-benz": "2", "mitsubishi": "2", "volvo": "2",
        "audi": "3", "honda": "3", "mazda": "3", "suzuki": "3", "volkswagen": "3",
        "haval": "4", "hyundai": "4", "isuzu": "4", "nissan": "4", "subaru": "4",
        "kia": "5", "perodua": "5", "peugeot": "5", "proton": "5", "ssangyong": "5",
    }
    assert BRAND_TIERS == expected
