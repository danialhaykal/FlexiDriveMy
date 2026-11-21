"""Audit batch 6 (F6): ONE list of mileage bands for the whole app - the
Financial Profile and the compare screens - labelled by each band's ceiling in
km a year, with the very high band's ceiling coming from SubscriptionPolicy;
plus the tidy-up command for profiles saved with an old literal-km value."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditActionCategory, AuditLog
from apps.policy.mileage import mileage_band_options
from apps.policy.models import InterestRate, MileageBand, SubscriptionPolicy
from apps.profiles.models import FinancialProfile
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

URL = "/api/comparisons/mileage-bands/"


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


# --- the one list ----------------------------------------------------------------


def test_the_list_has_the_four_bands_in_order_with_the_new_ranges_and_unchanged_keys(user_client):
    """Run 3 fix batch 6 (a): same keys, recalibrated ranges ("up to and including")."""
    response = user_client.get(URL)

    assert response.status_code == status.HTTP_200_OK
    assert [o["value"] for o in response.data] == list(MileageBand.values) == ["low", "standard", "high", "very_high"]
    assert [o["label"] for o in response.data] == [
        "Low — up to 10,000 km/year",
        "Standard — 10,001 to 15,000 km/year",
        "High — 15,001 to 25,000 km/year",
        "Very high — above 25,000 km/year",
    ]
    assert [(o["lower_km"], o["upper_km"]) for o in response.data] == [
        (0, 10000), (10000, 15000), (15000, 25000), (25000, 35000),
    ]
    assert [o["included_km_per_year"] for o in response.data] == [10000, 15000, 25000, 35000]
    assert [o["representative_km_per_year"] for o in response.data] == [8000, 12500, 20000, 30000]


def test_every_band_limit_comes_from_the_subscription_policy_not_from_code(user_client):
    SubscriptionPolicy.objects.update(low_km_cap=9000, standard_km_cap=16000, high_km_cap=26000, very_high_km_cap=45000)

    options = user_client.get(URL).data

    assert [o["label"] for o in options] == [
        "Low — up to 9,000 km/year",
        "Standard — 9,001 to 16,000 km/year",
        "High — 16,001 to 26,000 km/year",
        "Very high — above 26,000 km/year",
    ]
    assert [o["included_km_per_year"] for o in options] == [9000, 16000, 26000, 45000]
    assert [o["representative_km_per_year"] for o in options] == [7200, 12500, 21000, 35500]


def test_without_an_active_policy_the_seeded_defaults_stand_in(user_client):
    SubscriptionPolicy.objects.update(is_active=False)

    options = user_client.get(URL).data

    assert [o["upper_km"] for o in options] == [10000, 15000, 25000, 35000]
    assert options[3]["label"] == "Very high — above 25,000 km/year"


def test_it_matches_what_a_subscription_reports_as_included_km(user_client):
    """The label's ceiling and the Subscription's included-km allowance are the
    same figure, from the same code."""
    from apps.comparisons.services import build_comparison

    brand = Brand.objects.create(name="MileageBrand", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    vehicle = VehicleModel.objects.create(
        brand=brand, name="M", trim="X", body_segment=BodySegment.SEDAN, msrp="300000.00",
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    vehicle.refresh_from_db()
    from decimal import Decimal

    for option in mileage_band_options():
        comparison = build_comparison(
            vehicle=vehicle, tenure_months=36, mileage_band=option["value"], downpayment=Decimal("30000.00")
        )
        assert comparison["subscription"]["included_km_per_year"] == option["included_km_per_year"]


def test_it_needs_a_signed_in_user():
    assert APIClient().get(URL).status_code == status.HTTP_401_UNAUTHORIZED


# --- a legacy profile through the real TCO endpoint -------------------------------------


def test_a_profile_with_a_legacy_value_still_gets_the_declared_mileage_alert(user_client, regular_user):
    brand = Brand.objects.create(name="AlertBrand", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    vehicle = VehicleModel.objects.create(
        brand=brand, name="A", trim="X", body_segment=BodySegment.SEDAN, msrp="300000.00",
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    FinancialProfile.objects.create(
        user=regular_user, monthly_budget="2500.00", preferred_tenure_months=48,
        annual_mileage_band="30000",  # an old stored value: maps to very_high
        ownership_preference="retain",
    )

    response = user_client.get(
        "/api/depreciation/tco/",
        {"vehicle": vehicle.id, "tenure_months": 36, "mileage_band": "standard", "downpayment": "30000.00"},
    )

    assert response.status_code == status.HTTP_200_OK
    alerts = [a["code"] for a in response.data["risk_alerts"]]
    assert "declared_mileage_mismatch" in alerts  # declared very_high vs selected standard


# --- normalize_profile_mileage_bands --------------------------------------------------------


@pytest.fixture
def profiles(create_user):
    admin = create_user(email="admin@flexidrivemy.local", role="admin")
    rows = {}
    for key, email, stored in [
        ("legacy_10k", "a@example.test", "10000"), ("legacy_20k", "b@example.test", "20000"),
        ("legacy_30k", "c@example.test", "30000"), ("current", "d@example.test", "very_high"),
        ("unknown", "e@example.test", "bogus"),
    ]:
        user = create_user(email=email, role="user")
        rows[key] = FinancialProfile.objects.create(
            user=user, monthly_budget="2500.00", preferred_tenure_months=48,
            annual_mileage_band=stored, ownership_preference="retain",
        )
    AuditLog.objects.create(
        actor=admin, actor_email=admin.email, action=AuditActionCategory.CREATE,
        resource_type="profiles.FinancialProfile", resource_id="1", after_data={"seeded": True},
    )
    return rows


def run(*args):
    out = StringIO()
    call_command("normalize_profile_mileage_bands", *args, stdout=out)
    return out.getvalue()


def state():
    return {"profiles": list(FinancialProfile.objects.order_by("pk").values()), "audit": AuditLog.objects.count()}


def test_the_dry_run_is_the_default_and_writes_nothing(profiles):
    before = state()

    output = run()

    assert state() == before
    assert output.startswith("DRY RUN - nothing will be changed")
    assert "3 to change; 1 already current; 1 unknown (left alone); 5 profile(s) in total" in output
    assert "'10000' -> 'standard'" in output and "'20000' -> 'high'" in output and "'30000' -> 'very_high'" in output
    assert "maps to no band - left alone" in output


def test_apply_rewrites_exactly_the_legacy_rows_and_audits_each(profiles):
    existing = list(AuditLog.objects.values())

    run("--apply", "--actor", "admin@flexidrivemy.local")

    bands = {key: FinancialProfile.objects.get(pk=p.pk).annual_mileage_band for key, p in profiles.items()}
    assert bands == {
        "legacy_10k": "standard", "legacy_20k": "high", "legacy_30k": "very_high",
        "current": "very_high", "unknown": "bogus",  # an unrecognised value is never guessed at
    }
    new_rows = AuditLog.objects.exclude(pk__in=[row["id"] for row in existing])
    assert new_rows.count() == 3
    assert {row.action for row in new_rows} == {AuditActionCategory.UPDATE}
    assert {row.resource_type for row in new_rows} == {"profiles.FinancialProfile"}
    assert {row.actor_email for row in new_rows} == {"admin@flexidrivemy.local"}
    sample = new_rows.get(resource_id=str(profiles["legacy_10k"].pk))
    assert sample.before_data["annual_mileage_band"] == "10000" and sample.after_data["annual_mileage_band"] == "standard"
    assert "normalize_profile_mileage_bands" in sample.after_data["correction"]
    assert list(AuditLog.objects.filter(pk__in=[row["id"] for row in existing]).values()) == existing


def test_a_second_run_changes_nothing(profiles):
    run("--apply", "--actor", "admin@flexidrivemy.local")
    after_first = state()

    output = run("--apply", "--actor", "admin@flexidrivemy.local")

    assert state() == after_first
    assert "0 to change" in output and "Nothing to change." in output


def test_an_unknown_actor_is_refused_before_anything_is_written(profiles):
    before = state()

    with pytest.raises(CommandError):
        run("--apply", "--actor", "nobody@example.com")

    assert state() == before
