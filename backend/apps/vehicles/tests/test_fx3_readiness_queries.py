"""FX-3 (X14): Vehicle Readiness reads the three residual tables once for the whole report instead of once per
tenure x band per car (it took ~1,040 queries for 9 cars), with every check, status and message unchanged."""

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.policy.models import InterestRate, ResidualAdjustment, ResidualValueMatrix
from apps.policy.residuals import resolve_residual_ratio, residual_tables_snapshot
from apps.vehicles.models import BodySegment, Brand, VehicleModel
from apps.vehicles.readiness import active_vehicles, readiness_report, vehicle_readiness

pytestmark = pytest.mark.django_db

URL = "/api/admin/vehicle-readiness/"
RESIDUAL_TABLES = ("policy_residualvaluematrix", "policy_residualbaseline", "policy_residualadjustment")


def make_cars(count, prefix="Query"):
    cars = []
    for i in range(count):
        brand = Brand.objects.create(name=f"{prefix} Brand {i}", tier_code="3")
        InterestRate.objects.create(brand=brand, rate_percent="3.0000")
        cars.append(VehicleModel.objects.create(
            brand=brand, name=f"Model {i}", trim="T", body_segment=BodySegment.SEDAN, msrp=Decimal("200000.00"),
            engine_capacity_kw=Decimal("120.00"), powertrain="petrol" if i % 2 else "bev",
            engine_capacity_cc=None if i % 2 == 0 else 1998,
        ))
    # one override and one brand adjustment, so the snapshot has rows to choose from
    ResidualValueMatrix.objects.create(brand=cars[0].brand, tenure_months=36, mileage_band="standard", residual_value_ratio="0.5500")
    ResidualAdjustment.objects.create(brand=cars[-1].brand, delta_points="0.0300", source_note="test",
                                      effective_from=datetime.date(2026, 1, 1))
    return cars


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def residual_queries(ctx):
    """Full-row reads of the three residual tables (the reads resolve_residual_ratio makes; the tenure lists the
    Subscription and GFV availability messages read are separate and unchanged)."""
    return [q["sql"] for q in ctx.captured_queries
            if any(q["sql"].startswith(f'SELECT "{t}"."id"') for t in RESIDUAL_TABLES)]


def test_the_report_reads_each_residual_table_once_and_the_total_stays_bounded(admin_client):
    make_cars(4)
    admin_client.get(URL)  # warm any one-off caches

    with CaptureQueriesContext(connection) as ctx:
        response = admin_client.get(URL)

    assert response.status_code == 200
    assert len(response.json()["results"]) == 4
    # the three residual tables: once each for the whole report (was 20+ reads per car)
    assert len(residual_queries(ctx)) == 3
    # the rest is a few lookups per car; budget 40 per car (it was ~115 per car before)
    assert len(ctx.captured_queries) <= 40 * 4


def test_the_query_count_does_not_grow_with_tenure_x_band_cells(admin_client):
    make_cars(2)
    admin_client.get(URL)
    with CaptureQueriesContext(connection) as two:
        admin_client.get(URL)
    make_cars(2, prefix="More")
    with CaptureQueriesContext(connection) as four:
        admin_client.get(URL)

    assert len(residual_queries(four)) == len(residual_queries(two)) == 3


def test_every_check_is_identical_with_and_without_the_snapshot():
    make_cars(4)
    without = [vehicle_readiness(vehicle) for vehicle in active_vehicles()]

    assert readiness_report() == without


@pytest.mark.parametrize("tenure, band", [(36, "standard"), (48, "high"), (60, "very_high"), (12, "low")])
def test_the_snapshot_resolves_exactly_like_the_database(tenure, band):
    cars = make_cars(4)
    direct = [resolve_residual_ratio(car, tenure, band) for car in cars]
    with residual_tables_snapshot():
        snap = [resolve_residual_ratio(car, tenure, band) for car in cars]

    assert snap == direct
