"""Vehicle readiness (audit batch 6): GET /api/admin/vehicle-readiness/ and
apps.vehicles.readiness.vehicle_readiness.

The point of the panel is the Batch 1-5 promise: a car created through the
serializer with only the contract fields, on a brand with only an interest
rate, is fully priceable - so it must read "Ready". Each check calls the live
code path, so the tests also prove a change to that path shows up here.
"""

from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import (
    ContractPenaltyRule,
    InterestRate,
    ResidualBaseline,
    ResidualValueMatrix,
    RoadTaxCcBand,
    SubscriptionPlan,
    SubscriptionPolicy,
)
from apps.vehicles.models import BodySegment, Brand, VehicleModel
from apps.vehicles.readiness import vehicle_readiness
from apps.vehicles.serializers import VehicleModelSerializer

pytestmark = pytest.mark.django_db

URL = "/api/admin/vehicle-readiness/"


def create_through_the_serializer(brand, **fields):
    data = {
        "brand": brand.id, "name": "Brand New Model", "trim": "Launch Edition", "body_segment": BodySegment.SUV,
        "msrp": "400000.00", "engine_capacity_kw": "150.00", "powertrain": "petrol", "engine_capacity_cc": 1998,
    }
    data.update(fields)
    serializer = VehicleModelSerializer(data=data)
    assert serializer.is_valid(), serializer.errors
    vehicle = serializer.save()
    vehicle.refresh_from_db()
    return vehicle


def brand_with_only_a_rate(name="Startup Motors"):
    brand = Brand.objects.create(name=name, tier_code="3")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    return brand


def checks_by_key(report):
    return {c["key"]: c for c in report["checks"]}


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


# --- the Batch 1-5 promise --------------------------------------------------------


def test_a_new_car_with_only_the_contract_fields_on_a_brand_with_only_a_rate_is_ready():
    vehicle = create_through_the_serializer(brand_with_only_a_rate())

    report = vehicle_readiness(vehicle)

    assert report["status"] == "ready"
    assert report["missing_count"] == 0
    statuses = {c["key"]: c["status"] for c in report["checks"]}
    assert statuses == {
        "specs": "ok", "price": "ok", "running_costs": "ok", "road_tax_class": "ok", "interest_rate": "ok",
        "residuals": "ok", "subscription": "ok", "minimum_downpayment": "ok", "contract_rule": "ok",
        "resale_forecast": "info",  # run 2 fix batch 3: informational only (no model is deployed here)
        "model_year": "warning", "photo": "warning",  # recommended, never blocking
    }
    # An SUV with no class given: non-saloon from its body type, nothing to check.
    assert vehicle.road_tax_class == "non_saloon"
    assert checks_by_key(report)["road_tax_class"]["detail"] == "Non-saloon (usual for SUV)."
    assert report["warning_count"] == 2


def test_a_new_battery_electric_car_is_ready_too():
    vehicle = create_through_the_serializer(
        brand_with_only_a_rate("Volt Motors"), powertrain="bev", engine_capacity_cc=None, engine_capacity_kw="261.10",
    )

    report = vehicle_readiness(vehicle)

    assert report["status"] == "ready"
    assert checks_by_key(report)["running_costs"]["status"] == "ok"


def test_a_fully_filled_in_car_has_no_warnings():
    vehicle = create_through_the_serializer(brand_with_only_a_rate(), model_year=2026)
    VehicleModel.objects.filter(pk=vehicle.pk).update(thumbnail_url="https://example.test/car.jpg")
    vehicle.refresh_from_db()

    report = vehicle_readiness(vehicle)

    assert (report["status"], report["missing_count"], report["warning_count"]) == ("ready", 0, 0)
    # the resale-forecast line is informational (run 2 fix batch 3), so it is the one that is not "ok"
    assert all(c["status"] == "ok" for c in report["checks"] if c["key"] != "resale_forecast")


def test_every_check_has_a_key_a_plain_label_a_status_and_a_detail():
    report = vehicle_readiness(create_through_the_serializer(brand_with_only_a_rate()))

    assert [c["key"] for c in report["checks"]] == [
        "specs", "price", "running_costs", "road_tax_class", "interest_rate", "residuals", "subscription",
        "minimum_downpayment", "contract_rule", "resale_forecast", "model_year", "photo",
    ]
    for check in report["checks"]:
        assert check["label"] and check["detail"] and check["status"] in {"ok", "missing", "warning", "info"}
        assert not any(word in check["detail"] + check["label"] for word in ("CLAUDE", "UC0", "Batch"))


# --- each check goes missing for the real reason ------------------------------------


def test_removing_the_brands_interest_rate_makes_that_check_missing_with_the_real_message():
    brand = brand_with_only_a_rate()
    vehicle = create_through_the_serializer(brand)
    InterestRate.objects.filter(brand=brand).update(is_active=False)

    report = vehicle_readiness(vehicle)

    assert report["status"] == "needs_attention"
    rate = checks_by_key(report)["interest_rate"]
    assert rate["status"] == "missing"
    assert rate["detail"] == "No active interest rate configured for brand 'Startup Motors'."
    assert report["missing_count"] == 1  # nothing else broke


def test_a_car_whose_class_table_has_no_band_has_missing_running_costs_with_the_real_message():
    """Run 1 fix batch 3: there is no diesel table any more - a diesel SUV
    reads the non-saloon table like a petrol one. Remove the band covering
    its cc and running costs (and the subscription priced from them) go
    missing, naming the class; the other class's table is never used."""
    vehicle = create_through_the_serializer(
        brand_with_only_a_rate(), powertrain="diesel", engine_capacity_cc=1998,
    )
    assert vehicle_readiness(vehicle)["status"] == "ready"
    RoadTaxCcBand.objects.filter(vehicle_class="non_saloon", min_cc__lte=1998, max_cc__gte=1998).update(is_active=False)

    report = vehicle_readiness(vehicle)

    running = checks_by_key(report)["running_costs"]
    assert running["status"] == "missing"
    assert "No active non-saloon road tax band covers an engine capacity of 1,998 cc" in running["detail"]
    # Subscription is derived from the same running costs, so it is flagged too.
    assert checks_by_key(report)["subscription"]["status"] == "missing"
    assert report["status"] == "needs_attention"


@pytest.mark.parametrize("body, road_tax_class, expected", [
    ("crossover", "", "Check road-tax class on the VOC: crossovers are registered as either class (set to Non-saloon)."),
    ("crossover", "saloon", "Check road-tax class on the VOC: crossovers are registered as either class (set to Saloon)."),
    ("suv", "saloon", "Check road-tax class on the VOC: set to Saloon, which is not usual for body type SUV."),
    ("sedan", "non_saloon", "Check road-tax class on the VOC: set to Non-saloon, which is not usual for body type Sedan."),
])
def test_a_crossover_or_an_overridden_class_gets_an_amber_note_but_stays_ready(body, road_tax_class, expected):
    vehicle = create_through_the_serializer(
        brand_with_only_a_rate(), body_segment=body, road_tax_class=road_tax_class,
    )

    report = vehicle_readiness(vehicle)

    check = checks_by_key(report)["road_tax_class"]
    assert (check["status"], check["detail"]) == ("warning", expected)
    assert report["status"] == "ready"  # a note, never a blocker


def test_an_electric_car_has_no_class_to_check():
    vehicle = create_through_the_serializer(
        brand_with_only_a_rate(), body_segment="crossover", powertrain="bev", engine_capacity_cc=None,
        engine_capacity_kw="261.10",
    )

    assert checks_by_key(vehicle_readiness(vehicle))["road_tax_class"]["status"] == "ok"


def test_a_missing_residual_baseline_lists_the_exact_tenure_and_band():
    vehicle = create_through_the_serializer(brand_with_only_a_rate())
    ResidualBaseline.objects.filter(tenure_months=24, mileage_band="high").update(is_active=False)
    ResidualBaseline.objects.filter(tenure_months=60, mileage_band="low").update(is_active=False)

    residuals = checks_by_key(vehicle_readiness(vehicle))["residuals"]

    assert residuals["status"] == "missing"
    assert "24 months / high" in residuals["detail"] and "60 months / low" in residuals["detail"]
    assert "36 months" not in residuals["detail"]  # only the failing ones


def test_an_admin_override_covers_a_gap_in_the_baseline():
    brand = brand_with_only_a_rate()
    vehicle = create_through_the_serializer(brand)
    ResidualBaseline.objects.filter(tenure_months=24, mileage_band="high").update(is_active=False)
    ResidualValueMatrix.objects.create(
        brand=brand, tenure_months=24, mileage_band="high", residual_value_ratio="0.5000"
    )

    residuals = checks_by_key(vehicle_readiness(vehicle))["residuals"]

    assert residuals["status"] == "ok"
    assert "1 from admin overrides" in residuals["detail"]


def test_incomplete_specs_are_flagged_and_so_are_the_running_costs_that_depend_on_them():
    vehicle = create_through_the_serializer(brand_with_only_a_rate())
    VehicleModel.objects.filter(pk=vehicle.pk).update(powertrain="", engine_capacity_cc=None)
    vehicle.refresh_from_db()

    checks = checks_by_key(vehicle_readiness(vehicle))

    assert checks["specs"]["status"] == "missing" and checks["specs"]["detail"] == "Powertrain is required."
    assert checks["running_costs"]["status"] == "missing"
    assert "missing its specs" in checks["running_costs"]["detail"]


def test_a_missing_price_is_flagged():
    vehicle = create_through_the_serializer(brand_with_only_a_rate())
    VehicleModel.objects.filter(pk=vehicle.pk).update(msrp=Decimal("0.00"))
    vehicle.refresh_from_db()

    checks = checks_by_key(vehicle_readiness(vehicle))

    assert checks["price"]["status"] == "missing"
    assert checks["minimum_downpayment"]["status"] == "missing"


def test_a_brand_with_no_rule_uses_the_default_and_is_missing_only_when_that_is_gone_too():
    vehicle = create_through_the_serializer(brand_with_only_a_rate())
    assert checks_by_key(vehicle_readiness(vehicle))["contract_rule"]["detail"] == "Uses the default rule."

    ContractPenaltyRule.objects.create(
        brand=vehicle.brand, excess_mileage_charge_per_km="0.80", early_termination_months="6",
        wear_tear_tolerance_description="Brand terms.",
    )
    assert checks_by_key(vehicle_readiness(vehicle))["contract_rule"]["detail"] == "Startup Motors has its own rule."

    ContractPenaltyRule.objects.update(is_active=False)
    rule = checks_by_key(vehicle_readiness(vehicle))["contract_rule"]
    assert rule["status"] == "missing" and "no default rule" in rule["detail"]


def test_a_provider_quote_is_reported_as_the_subscription_source():
    vehicle = create_through_the_serializer(brand_with_only_a_rate())
    SubscriptionPlan.objects.create(vehicle=vehicle, fee_monthly="6000.00")

    assert checks_by_key(vehicle_readiness(vehicle))["subscription"]["detail"] == (
        "Priced at 12, 24, 36 months (provider quote)."
    )


def test_warnings_never_block_a_ready_car():
    vehicle = create_through_the_serializer(brand_with_only_a_rate())  # no year, no photo

    report = vehicle_readiness(vehicle)

    assert report["warning_count"] == 2 and report["missing_count"] == 0 and report["status"] == "ready"


# --- derived from the live code paths: a rule change shows up with no edit here --------


def test_a_change_to_the_subscription_policy_flows_straight_into_the_check():
    vehicle = create_through_the_serializer(brand_with_only_a_rate())
    assert checks_by_key(vehicle_readiness(vehicle))["subscription"]["detail"] == "Priced at 12, 24, 36 months (estimated)."

    SubscriptionPolicy.objects.update(max_tenure_months=48)  # an admin extends Subscription to 48 months

    assert checks_by_key(vehicle_readiness(vehicle))["subscription"]["detail"] == (
        "Priced at 12, 24, 36, 48 months (estimated)."
    )


def test_no_active_subscription_policy_is_missing():
    vehicle = create_through_the_serializer(brand_with_only_a_rate())
    SubscriptionPolicy.objects.update(is_active=False)

    sub = checks_by_key(vehicle_readiness(vehicle))["subscription"]

    assert sub["status"] == "missing" and sub["detail"] == "Subscription pricing isn't configured."


# --- the endpoint -------------------------------------------------------------------------


def test_the_endpoint_returns_every_active_vehicle_with_its_checks(admin_client):
    ready = create_through_the_serializer(brand_with_only_a_rate("Alpha Motors"), name="Ready One")
    broken_brand = brand_with_only_a_rate("Beta Motors")
    broken = create_through_the_serializer(broken_brand, name="Broken One")
    InterestRate.objects.filter(brand=broken_brand).update(is_active=False)

    response = admin_client.get(URL)

    assert response.status_code == status.HTTP_200_OK
    results = {r["vehicle_id"]: r for r in response.data["results"]}
    assert results[ready.pk]["status"] == "ready"
    assert results[broken.pk]["status"] == "needs_attention"
    assert results[broken.pk]["missing_count"] == 1
    assert results[ready.pk]["label"] == "Alpha Motors Ready One Launch Edition"
    assert len(results[ready.pk]["checks"]) == 12  # + road-tax class (run 1 fix batch 3), + resale forecast (run 2 fix batch 3)


def test_archived_vehicles_and_vehicles_of_archived_brands_are_excluded(admin_client):
    brand = brand_with_only_a_rate()
    live = create_through_the_serializer(brand, name="Live")
    archived = create_through_the_serializer(brand, name="Archived")
    VehicleModel.objects.filter(pk=archived.pk).update(is_active=False)
    other_brand = brand_with_only_a_rate("Gone Motors")
    hidden = create_through_the_serializer(other_brand, name="Hidden")
    Brand.objects.filter(pk=other_brand.pk).update(is_active=False)

    ids = {r["vehicle_id"] for r in admin_client.get(URL).data["results"]}

    assert live.pk in ids
    assert archived.pk not in ids and hidden.pk not in ids


def test_a_non_admin_gets_403_and_an_anonymous_visitor_401(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)

    assert client.get(URL).status_code == status.HTTP_403_FORBIDDEN
    assert APIClient().get(URL).status_code == status.HTTP_401_UNAUTHORIZED


def test_the_endpoint_is_read_only(admin_client):
    for method in (admin_client.post, admin_client.put, admin_client.patch, admin_client.delete):
        assert method(URL).status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_the_readiness_check_changes_no_data(admin_client):
    create_through_the_serializer(brand_with_only_a_rate())
    before = (VehicleModel.objects.count(), InterestRate.objects.count(), SubscriptionPlan.objects.count())

    admin_client.get(URL)

    assert (VehicleModel.objects.count(), InterestRate.objects.count(), SubscriptionPlan.objects.count()) == before
