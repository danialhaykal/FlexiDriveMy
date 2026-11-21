import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


def make_vehicle(brand, **overrides):
    defaults = {
        "brand": brand,
        "name": "City",
        "trim": "V",
        "body_segment": BodySegment.SEDAN,
        "msrp": "99999.99",
        "engine_capacity_kw": "90.00",
        # A complete spec, so full_clean() in the range tests below fails
        # only for the field under test.
        "powertrain": "petrol",
        "engine_capacity_cc": 1498,
    }
    defaults.update(overrides)
    return VehicleModel.objects.create(**defaults)


def test_brand_str_and_defaults():
    brand = Brand.objects.create(name="Proton", tier_code="B")
    assert str(brand) == "Proton"
    assert brand.is_active is True


def test_vehicle_model_str_and_soft_delete_flag():
    brand = Brand.objects.create(name="Honda", tier_code="A")
    model = make_vehicle(brand)
    assert str(model) == "Honda City V"
    assert model.is_active is True

    model.is_active = False
    model.save(update_fields=["is_active"])
    model.refresh_from_db()
    assert model.is_active is False
    # Soft delete only: the row must still exist.
    assert VehicleModel.objects.filter(pk=model.pk).exists()


def test_vehicle_model_unique_per_brand_name_trim():
    brand = Brand.objects.create(name="Toyota", tier_code="A")
    make_vehicle(brand, name="Vios", trim="G", model_year=2024)
    with pytest.raises(IntegrityError):
        make_vehicle(brand, name="Vios", trim="G", model_year=2024)


def test_vehicle_model_unique_ignores_model_year():
    # model_year isn't part of UC010's field list and isn't part of the
    # uniqueness key: same brand/name/trim still collides even with a
    # different (or absent) model_year.
    brand = Brand.objects.create(name="Toyota", tier_code="A")
    make_vehicle(brand, name="Yaris", trim="E", model_year=2024)
    with pytest.raises(IntegrityError):
        make_vehicle(brand, name="Yaris", trim="E", model_year=None)


def test_vehicle_model_allows_distinct_trims_of_same_model():
    brand = Brand.objects.create(name="Perodua", tier_code="C")
    make_vehicle(brand, name="Myvi", trim="X", model_year=2025)
    # Different trim, same brand/name/year: not a duplicate.
    make_vehicle(brand, name="Myvi", trim="H", model_year=2025)
    assert VehicleModel.objects.filter(brand=brand, name="Myvi").count() == 2


def test_msrp_must_be_positive():
    brand = Brand.objects.create(name="Mazda", tier_code="B")
    vehicle = make_vehicle(brand, msrp="-1.00")
    with pytest.raises(ValidationError):
        vehicle.full_clean()


def test_engine_capacity_must_be_within_range():
    # QA audit L13: ceiling raised 500.00 -> 700.00 kW (real in-scope
    # cars like a BMW M5 at 535kW were previously rejected outright) -
    # 701.00 is the new boundary's first invalid value.
    brand = Brand.objects.create(name="Mazda", tier_code="B")
    vehicle = make_vehicle(brand, engine_capacity_kw="701.00")
    with pytest.raises(ValidationError):
        vehicle.full_clean()
