"""Audit batch 2: the one operating-cost engine (apps.policy.operating_costs)
and the rate tables it reads (RoadTaxCcBand, EvRoadTaxGroup,
OperatingCostRate), seeded by policy data migration 0014.

Expected values are worked out by hand from the published JPJ schedules:
  petrol/diesel/hybrid/PHEV  tax = base + (cc - threshold) * per-cc rate
  battery electric           tax = base + ceil((kW - base_until) / 10) * increment
"""

import importlib
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.test import Client
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import (
    EvRoadTaxGroup,
    InterestRate,
    MileageBand,
    OperatingCostRate,
    RoadTaxCcBand,
    SubscriptionPlan,
)
from apps.policy.operating_costs import (
    OperatingCostConfigError,
    estimate_operating_costs,
    road_tax_for_cc,
    road_tax_for_kw,
)
from apps.vehicles.models import BodySegment, Brand, VehicleModel
from apps.vehicles.serializers import VehicleModelSerializer

pytestmark = pytest.mark.django_db

D = Decimal

CURRENT_INSURANCE = {
    "petrol": D("1.8"), "diesel": D("1.8"), "mild_hybrid": D("1.8"), "hybrid": D("1.8"),
    "phev": D("2.0"), "bev": D("2.3"),
}


@pytest.fixture
def brand():
    return Brand.objects.create(name="CostBrand", tier_code="2")


def make_vehicle(brand, **overrides):
    fields = dict(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN, msrp=D("265800.00"),
        engine_capacity_kw=D("135.00"), powertrain="petrol", engine_capacity_cc=1998,
    )
    fields.update(overrides)
    vehicle = VehicleModel.objects.create(**fields)
    vehicle.refresh_from_db()
    return vehicle


# --- the seed ---------------------------------------------------------------------


def test_the_migration_seeds_all_three_tables_with_provenance():
    # 9 saloon + 9 non-saloon active (run 1 fix batch 3); the 9 diesel rows are archived.
    assert RoadTaxCcBand.objects.filter(is_active=True).count() == 18
    assert RoadTaxCcBand.objects.filter(is_active=True, vehicle_class="non_saloon").count() == 9
    assert EvRoadTaxGroup.objects.filter(is_active=True).count() == 11
    assert set(OperatingCostRate.objects.values_list("powertrain", flat=True)) == {
        "petrol", "diesel", "mild_hybrid", "hybrid", "phev", "bev"}
    for model in (RoadTaxCcBand, EvRoadTaxGroup, OperatingCostRate):
        for row in model.objects.all():
            assert row.source_note and row.effective_from


def test_the_seeded_cost_rates_are_the_labelled_assumptions():
    rates = {r.powertrain: r for r in OperatingCostRate.objects.all()}
    assert {k: r.insurance_rate_percent for k, r in rates.items()} == {
        "petrol": D("1.8"), "diesel": D("1.8"), "mild_hybrid": D("1.8"), "hybrid": D("1.8"),
        "phev": D("2.0"), "bev": D("2.3")}
    assert {k: r.maintenance_rate_percent for k, r in rates.items()} == {
        "petrol": D("1.0"), "diesel": D("1.0"), "mild_hybrid": D("1.0"),
        "hybrid": D("0.9"), "phev": D("1.1"), "bev": D("0.7")}
    assert all(r.maintenance_floor_annual == D("1200") for r in rates.values())
    assert all("Planning estimate - edit in admin" in r.source_note for r in rates.values())


MIGRATION_0023 = "apps.policy.migrations.0023_non_saloon_road_tax_archive_diesel_maintenance_cap"


def test_the_latest_seed_is_idempotent_and_never_overwrites_an_admin_edit():
    """Run 1 fix batch 3: 0014 and 0016 only ever ran against the schema of
    their day (before the registration class and the per-class constraint
    existed), so they are no longer replayed here; 0023 is the seed that runs
    against today's schema. Re-running it never duplicates a row, re-activates
    a diesel band or overwrites an admin's edit."""
    migration_0023 = importlib.import_module(MIGRATION_0023)
    OperatingCostRate.objects.filter(powertrain="petrol").update(insurance_rate_percent=D("3.1"))
    OperatingCostRate.objects.filter(powertrain="bev").update(maintenance_cap_annual=D("9000.00"))
    RoadTaxCcBand.objects.filter(vehicle_class="non_saloon", min_cc=1801).update(base_amount=D("365.00"))

    migration_0023.forwards(django_apps, None)
    migration_0023.forwards(django_apps, None)

    assert RoadTaxCcBand.objects.filter(is_active=True).count() == 18
    assert RoadTaxCcBand.objects.filter(is_active=False, fuel_schedule="diesel").count() == 9
    assert EvRoadTaxGroup.objects.count() == 11
    assert OperatingCostRate.objects.count() == 6
    assert OperatingCostRate.objects.get(powertrain="petrol").insurance_rate_percent == D("3.1")
    assert OperatingCostRate.objects.get(powertrain="bev").maintenance_cap_annual == D("9000.00")
    assert RoadTaxCcBand.objects.get(vehicle_class="non_saloon", min_cc=1801).base_amount == D("365.00")


def test_a_fresh_database_ends_up_with_the_current_values():
    """The test database IS a fresh database: every migration from 0001 runs
    on it, in order, against the schema of its day. It must land on today's
    values: both class tables active, the diesel rows archived (kept, never
    deleted), current insurance, an 8,000 maintenance cap on every rate."""
    migration_0023 = importlib.import_module(MIGRATION_0023)

    assert RoadTaxCcBand.objects.filter(is_active=True, vehicle_class="saloon").count() == 9
    assert RoadTaxCcBand.objects.filter(is_active=True, vehicle_class="non_saloon").count() == 9
    assert not RoadTaxCcBand.objects.filter(is_active=True, fuel_schedule="diesel").exists()
    assert RoadTaxCcBand.objects.filter(is_active=False, fuel_schedule="diesel").count() == 9
    assert EvRoadTaxGroup.objects.count() == 11
    assert {r.powertrain: r.insurance_rate_percent for r in OperatingCostRate.objects.all()} == CURRENT_INSURANCE
    assert {r.maintenance_cap_annual for r in OperatingCostRate.objects.all()} == {D("8000.00")}
    assert not RoadTaxCcBand.objects.filter(source_note__contains="NOT modelled").exists()
    assert set(RoadTaxCcBand.objects.filter(is_active=True, vehicle_class="saloon").values_list("source_note", flat=True)) == {
        migration_0023.SALOON_SOURCE
    }


def test_re_seeding_the_non_saloon_table_creates_the_same_rows_on_an_empty_table():
    migration_0023 = importlib.import_module(MIGRATION_0023)
    RoadTaxCcBand.objects.filter(vehicle_class="non_saloon").delete()

    migration_0023.forwards(django_apps, None)

    rows = list(RoadTaxCcBand.objects.filter(vehicle_class="non_saloon", is_active=True).order_by("min_cc"))
    assert [(r.min_cc, r.max_cc, r.base_amount, r.threshold_cc, r.per_cc_rate) for r in rows] == [
        (min_cc, max_cc, D(base), threshold, D(per_cc))
        for min_cc, max_cc, base, threshold, per_cc in migration_0023.NON_SALOON_BANDS
    ]
    assert all("StashAway" in r.source_note and "MyJPJ" in r.source_note for r in rows)


def test_the_insurance_migration_lowers_an_untouched_seeded_row_and_never_an_admin_edit():
    seed_0014 = importlib.import_module("apps.policy.migrations.0014_seed_operating_cost_rates")
    migration_0016 = importlib.import_module("apps.policy.migrations.0016_diesel_schedule_and_lower_insurance")
    OperatingCostRate.objects.all().delete()
    RoadTaxCcBand.objects.all().delete()  # 0014 ran before any diesel/petrol distinction existed
    EvRoadTaxGroup.objects.all().delete()
    seed_0014.seed_operating_cost_tables(django_apps, None)  # the original 2.6% rows, as 0014 left them
    assert {r.insurance_rate_percent for r in OperatingCostRate.objects.all()} == {D("2.6")}
    # An admin edits PETROL's percentage, and BEV's note (value untouched), and PHEV's value + note.
    OperatingCostRate.objects.filter(powertrain="petrol").update(insurance_rate_percent=D("3.1"))
    OperatingCostRate.objects.filter(powertrain="bev").update(source_note="Edited note - quoted from my insurer.")
    OperatingCostRate.objects.filter(powertrain="phev").update(insurance_rate_percent=D("2.2"), source_note="mine")

    migration_0016.lower_default_insurance_rates(django_apps, None)

    rates = {r.powertrain: r for r in OperatingCostRate.objects.all()}
    assert rates["petrol"].insurance_rate_percent == D("3.1")                       # edited value kept
    assert rates["petrol"].source_note == seed_0014.RATE_SOURCE                      # (and its note not rewritten)
    assert rates["bev"].insurance_rate_percent == D("2.6")                           # edited note => not "still original"
    assert rates["bev"].source_note == "Edited note - quoted from my insurer."
    assert (rates["phev"].insurance_rate_percent, rates["phev"].source_note) == (D("2.2"), "mine")
    for untouched in ("diesel", "mild_hybrid", "hybrid"):                            # still original => lowered
        assert rates[untouched].insurance_rate_percent == D("1.8")
        assert rates[untouched].source_note == migration_0016.RATE_SOURCE


def test_the_insurance_note_states_the_liberalisation_and_the_market_anchor():
    note = OperatingCostRate.objects.get(powertrain="petrol").source_note
    assert note == (
        "Planning estimate - edit in admin. Percentage of price, no no-claims discount (conservative). "
        "Insurers set their own rates since the 2017 liberalisation; anchored to published market examples "
        "(about RM4,000 for a BMW 3 Series; EVs 20-30% higher), not a tariff."
    )

# --- JPJ cc schedule: golden values + boundaries -------------------------------------


@pytest.mark.parametrize(
    "cc, expected",
    [
        (1496, "90.00"),     # Mercedes C200: flat band 1,401-1,600
        (1969, "364.50"),    # Volvo B5/T8: 280 + 169 * 0.50
        (1984, "372.00"),    # Macan: 280 + 184 * 0.50
        (1998, "379.00"),    # BMW 320i: 280 + 198 * 0.50
        (2393, "773.00"),    # Alphard 2.4: 380 + 393 * 1.00
        (2487, "867.00"),    # Lexus ES 250: 380 + 487 * 1.00
        (2981, "2082.50"),   # 911: 880 + 481 * 2.50
        (4000, "6630.00"),   # 2,130 + 1,000 * 4.50
        (1000, "20.00"),
        (1200, "55.00"),
        # boundaries
        (1001, "55.00"),
        (1201, "70.00"),
        (1400, "70.00"),
        (1401, "90.00"),
        (1600, "90.00"),     # top of the flat band
        (1601, "200.40"),    # first cc of the progressive band: 200 + 1 * 0.40
        (1800, "280.00"),
        (1801, "280.50"),
        (2000, "380.00"),
        (2001, "381.00"),
        (2500, "880.00"),
        (2501, "882.50"),
        (3000, "2130.00"),
        (3001, "2134.50"),   # 2,130 + 1 * 4.50
        (5000, "11130.00"),  # 2,130 + 2,000 * 4.50
    ],
)
def test_road_tax_by_cc_golden_values_and_boundaries(cc, expected):
    amount, _band = road_tax_for_cc(cc)

    assert amount == D(expected)


def test_no_band_covering_a_cc_raises_naming_the_value():
    RoadTaxCcBand.objects.filter(min_cc=3001).update(is_active=False)

    with pytest.raises(OperatingCostConfigError, match=r"3,500 cc"):
        road_tax_for_cc(3500)


# --- JPJ EV kW groups: golden values + boundaries ---------------------------------------


@pytest.mark.parametrize(
    "kw, expected",
    [
        ("220", "305.00"),     # Tesla Model Y RWD: group C, at base_until
        ("150", "160.00"),     # group B: 80 + ceil(40/10) * 20
        ("385", "965.00"),     # group D: 615 + ceil(65/10)=7 * 50
        ("261.10", "455.00"),  # Macan Electric: group C: 305 + ceil(41.1/10)=5 * 30
        ("100", "70.00"),      # group A top: 20 + 5 * 10
        ("210", "280.00"),     # group B top: 80 + 10 * 20
        ("310", "575.00"),     # group C top: 305 + 9 * 30
        # boundaries
        ("100.1", "80.00"),    # first kW of group B
        ("100.05", "80.00"),   # between 100 and JPJ's "100.1": still the next group, no gap
        ("210.1", "305.00"),   # first kW of group C
        ("50", "20.00"),
        ("0.5", "20.00"),
        ("1010", "14415.00"),  # group J top: 11,265 + 9 * 350
        ("1011", "20000.00"),  # group K: fixed amount
        ("2500", "20000.00"),
    ],
)
def test_ev_road_tax_by_kw_golden_values_and_boundaries(kw, expected):
    amount, _group = road_tax_for_kw(D(kw))

    assert amount == D(expected)


def test_ev_group_is_named_in_the_basis(brand):
    macan = make_vehicle(brand, powertrain="bev", engine_capacity_cc=None, engine_capacity_kw=D("261.10"),
                         msrp=D("575000.00"))

    assert estimate_operating_costs(macan).basis["road_tax"] == "261.1 kW electric - JPJ EV kW schedule, group C"


def test_no_ev_group_covering_a_kw_raises_naming_the_value():
    EvRoadTaxGroup.objects.update(is_active=False)

    with pytest.raises(OperatingCostConfigError, match=r"261\.10 kW"):
        road_tax_for_kw(D("261.10"))


# --- estimate_operating_costs ------------------------------------------------------------------


def test_bmw_320i_sport_real_catalog_expectations(brand):
    bmw = make_vehicle(brand)  # RM265,800 / 1,998 cc / petrol

    costs = estimate_operating_costs(bmw)

    assert costs.road_tax_annual == D("379.00")
    assert costs.insurance_annual == D("4784.40")      # 1.8% x 265,800
    assert costs.maintenance_annual == D("2658.00")    # 1.0% x 265,800 (above the RM1,200 floor)
    assert costs.basis == {
        "road_tax": "1,998 cc petrol, saloon - JPJ cc schedule",  # the class named since run 1 fix batch 3
        "insurance": "1.8% of RM 265,800.00",
        "maintenance": "1.0% of price (floor RM 1,200)",
    }


def test_macan_electric_real_catalog_expectations(brand):
    macan = make_vehicle(brand, name="Macan Electric", powertrain="bev", engine_capacity_cc=None,
                         engine_capacity_kw=D("261.10"), msrp=D("575000.00"))

    costs = estimate_operating_costs(macan)

    assert costs.road_tax_annual == D("455.00")
    assert costs.insurance_annual == D("13225.00")     # 2.3% x 575,000 (EVs run 20-30% above petrol)
    assert costs.maintenance_annual == D("4025.00")    # 0.7% x 575,000
    assert costs.basis["maintenance"] == "0.7% of price (floor RM 1,200)"


def test_a_bev_never_reads_the_cc_table_and_everything_else_never_reads_the_ev_table(brand):
    bev = make_vehicle(brand, trim="E", powertrain="bev", engine_capacity_cc=None, engine_capacity_kw=D("220"))
    petrol = make_vehicle(brand, trim="P")
    active_bands = list(RoadTaxCcBand.objects.filter(is_active=True).values_list("pk", flat=True))
    RoadTaxCcBand.objects.update(is_active=False)
    assert estimate_operating_costs(bev).road_tax_annual == D("305.00")  # still costs: no cc band needed

    # Back to exactly the bands that were active (the archived diesel rows stay archived).
    RoadTaxCcBand.objects.filter(pk__in=active_bands).update(is_active=True)
    EvRoadTaxGroup.objects.update(is_active=False)
    assert estimate_operating_costs(petrol).road_tax_annual == D("379.00")  # no EV group needed


@pytest.mark.parametrize(
    "powertrain, cc, expected_tax",
    [("phev", 1969, "364.50"), ("hybrid", 1998, "379.00"), ("mild_hybrid", 1496, "90.00")],
)
def test_hybrids_and_phev_use_the_petrol_cc_schedule(brand, powertrain, cc, expected_tax):
    vehicle = make_vehicle(brand, powertrain=powertrain, engine_capacity_cc=cc)

    costs = estimate_operating_costs(vehicle)

    assert costs.road_tax_annual == D(expected_tax)
    assert "JPJ cc schedule" in costs.basis["road_tax"]


@pytest.mark.parametrize("powertrain, maintenance_pct", [("hybrid", "0.9"), ("phev", "1.1"), ("diesel", "1.0")])
def test_maintenance_follows_the_powertrains_own_rate(brand, powertrain, maintenance_pct):
    vehicle = make_vehicle(brand, powertrain=powertrain, msrp=D("300000.00"))

    assert estimate_operating_costs(vehicle).maintenance_annual == (D("300000") * D(maintenance_pct) / 100).quantize(D("0.01"))


def test_maintenance_never_drops_below_the_floor(brand):
    cheap = make_vehicle(brand, msrp=D("60000.00"), engine_capacity_cc=1496)  # 1.0% = 600 < 1,200

    costs = estimate_operating_costs(cheap)

    assert costs.maintenance_annual == D("1200.00")
    assert costs.basis["maintenance"] == "floor RM 1,200 (1.0% of price is lower)"


def test_insurance_is_a_percentage_of_price_rounded_to_the_sen(brand):
    vehicle = make_vehicle(brand, msrp=D("123456.78"))

    assert estimate_operating_costs(vehicle).insurance_annual == D("2222.22")  # 1.8% x 123,456.78 = 2222.22204


def test_every_figure_is_a_decimal_rounded_to_two_places(brand):
    costs = estimate_operating_costs(make_vehicle(brand, msrp=D("333333.33")))

    for value in (costs.road_tax_annual, costs.insurance_annual, costs.maintenance_annual):
        assert isinstance(value, Decimal)
        assert value == value.quantize(D("0.01"))


@pytest.mark.parametrize("overrides", [{"powertrain": ""}, {"engine_capacity_cc": None}, {"powertrain": "", "engine_capacity_cc": None}])
def test_a_vehicle_missing_its_specs_is_never_guessed(brand, overrides):
    vehicle = make_vehicle(brand, **overrides)

    with pytest.raises(OperatingCostConfigError) as excinfo:
        estimate_operating_costs(vehicle)

    assert "is missing its specs (powertrain / engine capacity). Complete them in Fleet Management." in str(excinfo.value)
    assert str(vehicle) in str(excinfo.value)


def test_a_missing_rate_row_for_the_powertrain_raises(brand):
    OperatingCostRate.objects.filter(powertrain="petrol").update(is_active=False)

    with pytest.raises(OperatingCostConfigError, match="petrol"):
        estimate_operating_costs(make_vehicle(brand))


# --- THE new-car contract: contract fields only, costed automatically ---------------------------


def create_through_serializer(brand, **overrides):
    data = {
        "brand": brand.pk, "name": "Brand New", "trim": "Launch Edition", "body_segment": "sedan",
        "msrp": "310000.00", "engine_capacity_kw": "180.00", "powertrain": "petrol", "engine_capacity_cc": 1998,
    }
    data.update(overrides)
    serializer = VehicleModelSerializer(data=data)
    assert serializer.is_valid(), serializer.errors
    return serializer.save()


def request_tco(client, vehicle):
    return client.get(
        "/api/depreciation/tco/",
        {"vehicle": vehicle.pk, "tenure_months": 36, "mileage_band": MileageBand.STANDARD, "downpayment": "31000.00"},
    )


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


def test_a_brand_new_car_with_only_the_contract_fields_is_costed_with_no_further_config(user_client, brand):
    # Brand-level config the app always needed (an interest rate) is the ONLY
    # thing set up; nothing is keyed in per car - no cost band, no plan.
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    new_car = create_through_serializer(brand)
    assert not SubscriptionPlan.objects.filter(vehicle=new_car).exists()

    response = request_tco(user_client, new_car)

    assert response.status_code == status.HTTP_200_OK
    assert Decimal(response.data["road_tax_annual"]) == D("379.00")        # 1,998 cc
    assert Decimal(response.data["insurance_annual"]) == D("5580.00")      # 1.8% x 310,000
    assert Decimal(response.data["maintenance_annual"]) == D("3100.00")    # 1.0% x 310,000
    # A sedan: the saloon class, filled in from its body type with no step.
    assert new_car.road_tax_class == "saloon"
    assert response.data["operating_cost_basis"]["road_tax"] == "1,998 cc petrol, saloon - JPJ cc schedule"


def test_a_brand_new_bev_with_only_the_contract_fields_is_costed_with_no_further_config(user_client, brand):
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    new_bev = create_through_serializer(
        brand, name="Brand New EV", trim="RWD", powertrain="bev", engine_capacity_cc=None, engine_capacity_kw="220.00",
        msrp="200000.00",
    )

    response = request_tco(user_client, new_bev)

    assert response.status_code == status.HTTP_200_OK
    assert Decimal(response.data["road_tax_annual"]) == D("305.00")        # group C at 220 kW
    assert Decimal(response.data["insurance_annual"]) == D("4600.00")      # 2.3% x 200,000
    assert Decimal(response.data["maintenance_annual"]) == D("1400.00")    # 0.7% x 200,000
    assert "group C" in response.data["operating_cost_basis"]["road_tax"]


# --- SubscriptionPlan: only the fee is asked for ------------------------------------------------------


def test_a_subscription_plan_needs_only_its_monthly_fee(brand):
    admin = APIClient()
    from django.contrib.auth import get_user_model

    admin.force_authenticate(user=get_user_model().objects.create_user(email="adm@example.com", password="pw", role="admin"))
    vehicle = make_vehicle(brand)

    response = admin.post("/api/policy/subscription-plans/", {"vehicle": vehicle.pk, "fee_monthly": "6500.00"}, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    plan = SubscriptionPlan.objects.get(pk=response.data["id"])
    assert (plan.insurance_annual, plan.road_tax_annual, plan.maintenance_annual) == (D("0.00"), D("0.00"), D("0.00"))


def test_the_old_cost_band_api_is_gone(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)

    assert client.get("/api/policy/operating-cost-bands/").status_code == status.HTTP_404_NOT_FOUND


# --- read-only API + Django admin -------------------------------------------------------------------------


def test_the_operating_costs_endpoint_lists_the_three_tables_with_provenance(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)

    response = client.get("/api/policy/operating-costs/")

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["road_tax_cc_bands"]) == 18  # 9 non-saloon + 9 saloon, active
    assert len(response.data["ev_road_tax_groups"]) == 11
    assert len(response.data["cost_rates"]) == 6
    assert [b["vehicle_class"] for b in response.data["road_tax_cc_bands"]] == ["non_saloon"] * 9 + ["saloon"] * 9
    saloon_bands = [b for b in response.data["road_tax_cc_bands"] if b["vehicle_class"] == "saloon"]
    band = saloon_bands[5]
    assert (band["min_cc"], band["max_cc"], band["base_amount"], band["threshold_cc"], band["per_cc_rate"]) == (
        1801, 2000, "280.00", 1800, "0.50")
    assert band["source_note"] and band["effective_from"] == "2007-01-01"
    non_saloon = [b for b in response.data["road_tax_cc_bands"] if b["vehicle_class"] == "non_saloon"][5]
    assert (non_saloon["vehicle_class_label"], non_saloon["base_amount"], non_saloon["per_cc_rate"]) == (
        "Non-saloon", "360.00", "0.40")
    # The old diesel rows, listed separately and read-only, never mixed in with the live tables.
    archived = response.data["archived_diesel_cc_bands"]
    assert len(archived) == 9
    assert {b["fuel_schedule"] for b in archived} == {"diesel"} and not any(b["is_active"] for b in archived)
    assert {r["maintenance_cap_annual"] for r in response.data["cost_rates"]} == {"8000.00"}
    group = response.data["ev_road_tax_groups"][2]
    assert (group["label"], group["base_amount"], group["base_until_kw"], group["increment_per_10kw"]) == (
        "C", "305.00", "220.00", "30.00")
    assert group["effective_from"] == "2026-01-01"
    assert {r["powertrain"] for r in response.data["cost_rates"]} == {
        "petrol", "diesel", "mild_hybrid", "hybrid", "phev", "bev"}


def test_the_operating_costs_endpoint_is_admin_only_and_read_only(regular_user, admin_user):
    user = APIClient()
    user.force_authenticate(user=regular_user)
    assert user.get("/api/policy/operating-costs/").status_code == status.HTTP_403_FORBIDDEN

    admin = APIClient()
    admin.force_authenticate(user=admin_user)
    assert admin.post("/api/policy/operating-costs/", {}, format="json").status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.parametrize("model", ["roadtaxccband", "evroadtaxgroup", "operatingcostrate"])
def test_the_three_tables_are_registered_in_django_admin(django_user_model, model):
    client = Client()
    client.force_login(django_user_model.objects.create_superuser(email="super@example.com", password="pw"))

    assert client.get(reverse(f"admin:policy_{model}_changelist")).status_code == 200
