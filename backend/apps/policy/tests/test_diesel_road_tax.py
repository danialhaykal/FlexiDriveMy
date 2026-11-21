"""Run 1 fix batch 3 (C2): there is no separate diesel road-tax table.

Audit batch 3 had seeded one from a single 2006 article (paultan.org, 31 Dec
2006); current sources - StashAway 2026, paultan's 2015 explainer ("applies to
both petrol and diesel engines") and the Carso calculator - describe none.
Diesel now reads the same cc table as petrol for the car's registration class
(saloon / non-saloon). The old diesel rows are archived (is_active=False),
never deleted, and never read.
"""

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.policy.models import RoadTaxCcBand
from apps.policy.operating_costs import estimate_operating_costs, road_tax_for_cc
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def brand():
    return Brand.objects.create(name="DieselBrand", tier_code="2")


def make_vehicle(brand, **overrides):
    fields = dict(
        brand=brand, name="Hilux", trim="2.4 Double Cab", body_segment=BodySegment.PICKUP, msrp=D("150000.00"),
        engine_capacity_kw=D("110.00"), powertrain="diesel", engine_capacity_cc=2393,
    )
    fields.update(overrides)
    vehicle = VehicleModel.objects.create(**fields)
    vehicle.refresh_from_db()
    return vehicle


def test_a_hilux_style_diesel_pickup_is_on_the_non_saloon_table(brand):
    """2,393 cc diesel pickup, non-saloon by its body type:
    440 + (2,393 - 2,000) x 0.80 = 754.40 (the archived diesel table said
    1,644.60 at this cc)."""
    hilux = make_vehicle(brand)

    costs = estimate_operating_costs(hilux)

    assert hilux.road_tax_class == "non_saloon"
    assert costs.road_tax_annual == D("754.40")
    assert costs.basis["road_tax"] == "2,393 cc diesel, non-saloon - JPJ cc schedule"


def test_the_real_hilux_2_8_is_no_longer_costed_at_about_rm_3410(brand):
    """2,755 cc: the archived diesel table gave 1,880 + 255 x 6.00 = 3,410.00
    (Master Test Run 1, C2). Non-saloon: 840 + 255 x 1.60 = 1,248.00."""
    hilux = make_vehicle(brand, trim="2.8 Rogue", engine_capacity_cc=2755)

    assert estimate_operating_costs(hilux).road_tax_annual == D("1248.00")


@pytest.mark.parametrize("road_tax_class, expected", [("non_saloon", "433.60"), ("saloon", "372.00")])
def test_diesel_and_petrol_pay_the_same_for_the_same_class_and_cc(brand, road_tax_class, expected):
    diesel = make_vehicle(brand, trim="D", engine_capacity_cc=1984, road_tax_class=road_tax_class)
    petrol = make_vehicle(brand, trim="P", engine_capacity_cc=1984, powertrain="petrol", road_tax_class=road_tax_class)

    assert estimate_operating_costs(diesel).road_tax_annual == estimate_operating_costs(petrol).road_tax_annual == D(expected)


def test_the_diesel_rows_are_archived_not_deleted_and_never_read():
    archived = RoadTaxCcBand.objects.filter(fuel_schedule="diesel")

    assert archived.count() == 9  # kept for the audit trail
    assert not archived.filter(is_active=True).exists()
    # Every active band, whatever its old fuel_schedule label, is a class table.
    assert set(RoadTaxCcBand.objects.filter(is_active=True).values_list("fuel_schedule", flat=True)) == {"petrol"}
    assert road_tax_for_cc(2393, "non_saloon")[1].fuel_schedule == "petrol"


def test_a_diesel_band_cannot_be_reactivated_alongside_the_class_table():
    """Re-activating an archived diesel row would give one class two active
    bands for the same cc - the database refuses it."""
    diesel_row = RoadTaxCcBand.objects.filter(fuel_schedule="diesel", min_cc=0).first()

    with pytest.raises(IntegrityError), transaction.atomic():
        RoadTaxCcBand.objects.filter(pk=diesel_row.pk).update(is_active=True)
