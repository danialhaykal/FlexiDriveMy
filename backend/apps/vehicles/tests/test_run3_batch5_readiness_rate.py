"""Run 3 fix batch 5 (F-18): Vehicle Readiness says the flat rate to 2 dp, as the
buyer screens show it ("2.80%", not "2.8000%"). Display only - the stored rate and
the API's 4-dp value are unchanged."""

from decimal import Decimal

import pytest

from apps.policy.models import InterestRate
from apps.vehicles.models import BodySegment, Brand, VehicleModel
from apps.vehicles.readiness import vehicle_readiness

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("rate, shown", [("2.8000", "2.80"), ("3.1000", "3.10"), ("2.8250", "2.83"), ("15.0000", "15.00")])
def test_the_rate_line_uses_two_decimals(rate, shown):
    brand = Brand.objects.create(name="RateBrand", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent=rate)
    car = VehicleModel.objects.create(brand=brand, name="M", trim="X", body_segment=BodySegment.SEDAN, msrp="300000.00",
                                      engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998)
    car.refresh_from_db()

    check = next(c for c in vehicle_readiness(car)["checks"] if c["key"] == "interest_rate")

    assert check["detail"] == f"RateBrand has a flat rate of {shown}% a year."
    assert InterestRate.objects.get(brand=brand).rate_percent == Decimal(rate)
