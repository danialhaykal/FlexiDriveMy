"""Run 1 fix batch 3: running-cost realism.

  C2  road tax by JPJ registration class (saloon / non-saloon); diesel uses the
      same tables (see test_diesel_road_tax.py)
  C3  the buyer's No-Claim Discount on OWNER insurance only - never on the
      subscription fee - read from their own profile, never the request
  C4  a maintenance ceiling (planning assumption, RM 8,000)

Every expected figure is worked out by hand in its comment (the batch prompt's
goldens); "before" figures are reproduced by putting back the pre-batch
configuration (every car saloon, no cap) on the same cars.
"""

import importlib
import io
import json
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.comparisons.services import build_comparison
from apps.depreciation.services import build_tco_report
from apps.exports import tasks
from apps.policy.models import InterestRate, OperatingCostRate
from apps.policy.operating_costs import estimate_operating_costs
from apps.profiles.models import FinancialProfile
from apps.scenarios.models import SavedScenario
from apps.vehicles.models import BodySegment, Brand, VehicleModel, VehicleSpecDraft
from apps.vehicles.serializers import VehicleModelSerializer

pytestmark = pytest.mark.django_db

D = Decimal
seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")

# The dev catalog's cars (same price, body, powertrain, cc / kW), keyed by a short name.
DEV_CARS = {
    "bmw": ("BMW", "3 Series", "320i Sport", "sedan", "265800.00", "petrol", 1998, "135.00", "2.8000"),
    "lexus": ("Lexus", "ES", "250 Luxury", "sedan", "356888.00", "petrol", 2487, "152.00", "2.8000"),
    "c200": ("Mercedes-Benz", "C-Class", "C200 Avantgarde", "sedan", "292888.00", "mild_hybrid", 1496, "150.00", "2.8000"),
    "911": ("Porsche", "911", "Carrera", "coupe", "1430000.00", "petrol", 2981, "290.00", "3.5000"),
    "macan": ("Porsche", "Macan", "Base", "suv", "469000.00", "petrol", 1984, "195.00", "3.5000"),
    "alphard": ("Toyota", "Alphard", "2.4 Executive Lounge", "mpv", "548000.00", "petrol", 2393, "205.00", "2.5000"),
    "xc60": ("Volvo", "XC60", "B5 Core", "suv", "328888.00", "mild_hybrid", 1969, "184.00", "2.5000"),
    "xc90": ("Volvo", "XC90", "Ultra T8", "suv", "434888.00", "phev", 1969, "233.15", "2.5000"),
    "macan_ev": ("Porsche", "Macan Electric", "RWD", "suv", "575000.00", "bev", None, "261.10", "3.5000"),
}


def make_car(key, **overrides):
    brand_name, name, trim, body, msrp, powertrain, cc, kw, rate = DEV_CARS[key]
    brand, _ = Brand.objects.get_or_create(name=brand_name, defaults={"tier_code": "2"})
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.get_or_create(brand=brand, is_active=True, defaults={"rate_percent": rate})
    fields = dict(
        brand=brand, name=name, trim=trim, body_segment=body, msrp=msrp, powertrain=powertrain,
        engine_capacity_cc=cc, engine_capacity_kw=kw,
    )
    fields.update(overrides)
    vehicle = VehicleModel.objects.create(**fields)
    vehicle.refresh_from_db()
    return vehicle


def running(costs):
    return costs.road_tax_annual + costs.insurance_annual + costs.maintenance_annual


def ten_percent(vehicle):
    return (vehicle.msrp * D("0.10")).quantize(D("0.01"))


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


@pytest.fixture
def admin_client(admin_user):
    c = APIClient()
    c.force_authenticate(user=admin_user)
    return c


def set_ncd(user, ncd):
    FinancialProfile.objects.update_or_create(
        user=user,
        defaults={"monthly_budget": "8000.00", "preferred_tenure_months": 60, "annual_mileage_band": "standard",
                  "ownership_preference": "retain", "ncd_percent": D(ncd)},
    )


# --- Step 1: road-tax registration class --------------------------------------------------------------


@pytest.mark.parametrize("key, road_tax_class, expected", [
    ("bmw", "saloon", "379.00"),       # 280 + 198 x 0.50 (unchanged)
    ("lexus", "saloon", "867.00"),     # 380 + 487 x 1.00 (unchanged)
    ("c200", "saloon", "90.00"),       # flat 1,401-1,600 (unchanged)
    ("911", "saloon", "2082.50"),      # a coupe: 880 + 481 x 2.50 (unchanged)
    ("macan", "non_saloon", "433.60"),     # 360 + 184 x 0.40 (was 372.00)
    ("alphard", "non_saloon", "754.40"),   # 440 + 393 x 0.80 (was 773.00)
    ("xc60", "non_saloon", "427.60"),      # 360 + 169 x 0.40 (was 364.50)
    ("xc90", "non_saloon", "427.60"),      # 360 + 169 x 0.40 (was 364.50)
    ("macan_ev", "non_saloon", "455.00"),  # 261.1 kW, group C - EV tax is not split by class (unchanged)
])
def test_step_1_road_tax_for_the_dev_cars(key, road_tax_class, expected):
    car = make_car(key)

    assert car.road_tax_class == road_tax_class  # filled from the body type, nothing keyed
    assert estimate_operating_costs(car).road_tax_annual == D(expected)


@pytest.mark.parametrize("body, expected", [
    ("sedan", "saloon"), ("hatchback", "saloon"), ("coupe", "saloon"),
    ("suv", "non_saloon"), ("mpv", "non_saloon"), ("pickup", "non_saloon"), ("van", "non_saloon"),
    ("crossover", "non_saloon"),
])
def test_the_class_defaults_from_the_body_type(body, expected):
    assert make_car("bmw", body_segment=body).road_tax_class == expected


def test_an_admin_override_wins_over_the_body_type_and_is_costed_on_its_own_table():
    # A crossover registered as a saloon on its VOC.
    car = make_car("macan", body_segment="crossover", road_tax_class="saloon")

    assert car.road_tax_class == "saloon"
    assert estimate_operating_costs(car).road_tax_annual == D("372.00")  # 280 + 184 x 0.50
    assert estimate_operating_costs(car).basis["road_tax"] == "1,984 cc petrol, saloon - JPJ cc schedule"


def test_the_django_admin_form_offers_the_class_with_the_voc_help_text():
    # The admin's ModelForm builds its field from the model field, so this
    # is the field (and help text) the Django admin form shows.
    from django.forms import modelform_factory

    field = modelform_factory(VehicleModel, fields=["road_tax_class"])().fields["road_tax_class"]
    assert field.help_text == "Use the class on the car's registration card (VOC). Body type is only the default."
    assert not field.required  # blank = the body type's default, filled on save


def test_a_row_written_without_save_is_still_costed_from_its_body_type():
    """bulk_create / queryset.update skip save(); the engine applies the same
    body-type default rather than failing or guessing anything else."""
    car = make_car("macan")
    VehicleModel.objects.filter(pk=car.pk).update(road_tax_class="")
    car.refresh_from_db()

    assert estimate_operating_costs(car).road_tax_annual == D("433.60")


# --- the new-car contract: a new SUV is non-saloon and costed on every create path ------------------------------


SUV_FIELDS = {
    "name": "GLC", "trim": "300 4MATIC", "body_segment": "suv", "msrp": "400000.00", "engine_capacity_kw": "190.00",
    "powertrain": "petrol", "engine_capacity_cc": 1999,
}


def assert_new_suv_is_costed(vehicle):
    vehicle.refresh_from_db()
    assert vehicle.road_tax_class == "non_saloon"
    # 360 + 199 x 0.40 = 439.60 - no class, band, plan or cost row keyed by hand.
    assert estimate_operating_costs(vehicle).road_tax_annual == D("439.60")


def test_a_new_suv_through_the_fleet_api(admin_client):
    brand = Brand.objects.create(name="Mercedes-Benz", tier_code="2")

    response = admin_client.post("/api/vehicles/models/", {"brand": brand.pk, **SUV_FIELDS}, format="json")

    assert response.status_code == 201, response.data
    assert response.data["road_tax_class"] == "non_saloon"
    assert response.data["road_tax_class_is_default"] is True
    assert_new_suv_is_costed(VehicleModel.objects.get(pk=response.data["id"]))


def test_a_new_suv_through_bulk_import(admin_client):
    Brand.objects.create(name="Mercedes-Benz", tier_code="2")
    csv = (
        "brand,name,trim,body_segment,msrp,engine_capacity_kw,powertrain,engine_capacity_cc\n"
        "Mercedes-Benz,GLC,300 4MATIC,suv,400000.00,190.00,petrol,1999\n"
    ).encode()
    upload = SimpleUploadedFile("import.csv", csv, content_type="text/csv")

    response = admin_client.post("/api/vehicles/models/bulk_import/", {"file": upload}, format="multipart")

    assert response.status_code in (200, 201), response.data
    assert_new_suv_is_costed(VehicleModel.objects.get(name="GLC"))


def test_bulk_import_accepts_a_spreadsheet_spelling_of_the_class(admin_client):
    Brand.objects.create(name="Toyota", tier_code="2")
    csv = (
        "brand,name,trim,body_segment,msrp,engine_capacity_kw,powertrain,engine_capacity_cc,road_tax_class\n"
        "Toyota,Corolla Cross,1.8V,crossover,140000.00,103.00,petrol,1798,Saloon\n"
    ).encode()

    admin_client.post("/api/vehicles/models/bulk_import/", {"file": SimpleUploadedFile("i.csv", csv)}, format="multipart")

    assert VehicleModel.objects.get(name="Corolla Cross").road_tax_class == "saloon"


def test_a_new_suv_approved_from_a_spec_draft(admin_client, admin_user):
    """Approving a draft is the Add Vehicle form posting the draft's proposed
    values to the same create endpoint (VehicleSpecDraft never creates a car
    itself). A draft carries no class; the body type supplies it."""
    brand = Brand.objects.create(name="Mercedes-Benz", tier_code="2")
    draft = VehicleSpecDraft.objects.create(
        brand=brand, model_name_query="GLC", status="ready", requested_by=admin_user,
        proposed_data={key: SUV_FIELDS[key] for key in ("name", "trim", "body_segment", "msrp", "engine_capacity_kw",
                                                        "powertrain", "engine_capacity_cc")},
    )
    assert "road_tax_class" not in draft.proposed_data

    response = admin_client.post("/api/vehicles/models/", {"brand": brand.pk, **draft.proposed_data}, format="json")

    assert response.status_code == 201, response.data
    assert_new_suv_is_costed(VehicleModel.objects.get(pk=response.data["id"]))


def test_the_serializer_refuses_an_unknown_class():
    brand = Brand.objects.create(name="Mercedes-Benz", tier_code="2")
    serializer = VehicleModelSerializer(data={"brand": brand.pk, **SUV_FIELDS, "road_tax_class": "truck"})

    assert not serializer.is_valid()
    assert "road_tax_class" in serializer.errors


# --- Step 2: No-Claim Discount ------------------------------------------------------------------------------------


@pytest.mark.parametrize("ncd, insurance, running_total, basis", [
    ("0", "4784.40", "7821.40", "1.8% of RM 265,800.00"),
    # 4,784.40 x 0.45 = 2,152.98
    ("55", "2152.98", "5189.98", "1.8% of RM 265,800.00, less 55% NCD"),
    # 265,800 x 1.8% x 0.6167 = 2,950.5394 -> 2,950.54
    ("38.33", "2950.54", "5987.54", "1.8% of RM 265,800.00, less 38.33% NCD"),
])
def test_ncd_lowers_owner_insurance_rounded_once(ncd, insurance, running_total, basis):
    costs = estimate_operating_costs(make_car("bmw"), ncd_percent=D(ncd))

    assert costs.insurance_annual == D(insurance)
    assert running(costs) == D(running_total)
    assert costs.basis["insurance"] == basis


def test_bmw_tco_and_subscription_offset_at_ncd_55_through_the_api(client, regular_user):
    """TCO 60 months: 5 x (4,784.40 - 2,152.98) = 13,157.10 less -
    gross 338,397.80 -> 325,240.70, net 240,609.98 -> 227,452.88.
    Subscription 36 months: the fee 5,563.90 is unchanged; the offset is
    5,563.90 - 5,189.98 / 12 = 5,131.40 (was 5,563.90 - 7,821.40 / 12 = 4,912.12).
    Run 3 fix batch 6: resale(60) 93,030.00 -> 97,787.82 and the fee 5,701.93 -> 5,563.90
    (the recalibrated standard residual); the NCD movements themselves are unchanged."""
    bmw = make_car("bmw")
    q = {"vehicle": bmw.pk, "mileage_band": "standard", "downpayment": "26580.00"}

    set_ncd(regular_user, "0")
    tco_0 = client.get("/api/depreciation/tco/", {**q, "tenure_months": 60}).data
    sub_0 = client.get("/api/comparisons/", {**q, "tenure_months": 36}).data
    set_ncd(regular_user, "55")
    tco_55 = client.get("/api/depreciation/tco/", {**q, "tenure_months": 60}).data
    sub_55 = client.get("/api/comparisons/", {**q, "tenure_months": 36}).data

    assert (tco_0["tco_gross"], tco_0["tco_net"], tco_0["ncd_percent"]) == ("338397.80", "240609.98", "0.00")
    assert (tco_55["tco_gross"], tco_55["tco_net"], tco_55["ncd_percent"]) == ("325240.70", "227452.88", "55.00")
    assert tco_55["insurance_annual"] == "2152.98"
    assert sub_0["subscription"]["monthly_instalment"] == sub_55["subscription"]["monthly_instalment"] == "5563.90"
    assert sub_0["subscription"]["refundable_deposit"] == sub_55["subscription"]["refundable_deposit"]
    assert sub_0["subscription"]["net_cost_after_bundled_benefits"] == "4912.12"
    assert sub_55["subscription"]["net_cost_after_bundled_benefits"] == "5131.40"
    assert sub_55["ncd_percent"] == "55.00"
    # Nothing financed moves: instalments, outlay and effective rate are NCD-free.
    assert sub_0["hire_purchase"] == sub_55["hire_purchase"]
    assert sub_0["gfv_leasing"] == sub_55["gfv_leasing"]


def test_ncd_38_33_subscription_offset(client, regular_user):
    # 5,563.90 - (379.00 + 2,950.54 + 2,658.00) / 12 = 5,563.90 - 498.9617 = 5,064.94
    # (Run 3 fix batch 6: the fee was 5,701.93, so the offset was 5,202.97)
    bmw = make_car("bmw")
    set_ncd(regular_user, "38.33")

    data = client.get("/api/comparisons/", {"vehicle": bmw.pk, "tenure_months": 36, "mileage_band": "standard",
                                            "downpayment": "26580.00"}).data

    assert data["subscription"]["net_cost_after_bundled_benefits"] == "5064.94"


def test_the_subscription_fee_never_uses_the_buyers_ncd():
    bmw = make_car("bmw")

    fees = {
        ncd: build_comparison(vehicle=bmw, tenure_months=36, mileage_band="standard", downpayment=D("26580.00"),
                              ncd_percent=D(ncd))["subscription"]["monthly_instalment"]
        for ncd in ("0", "25", "55")
    }

    assert set(fees.values()) == {D("5563.90")}


@pytest.mark.parametrize("path", ["/api/depreciation/tco/", "/api/comparisons/"])
def test_an_ncd_query_parameter_is_ignored_never_trusted(client, regular_user, path):
    """No request parameter can claim a discount: an unknown query parameter
    is ignored (the request serializers don't declare it), so the profile's
    0% stands."""
    bmw = make_car("bmw")
    set_ncd(regular_user, "0")
    q = {"vehicle": bmw.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "26580.00"}

    plain = client.get(path, q)
    forged = client.get(path, {**q, "ncd_percent": "55"})

    assert forged.status_code == 200
    assert json.loads(forged.content) == json.loads(plain.content)
    assert forged.data["ncd_percent"] == "0.00"


def test_no_profile_means_no_ncd(client):
    bmw = make_car("bmw")

    data = client.get("/api/depreciation/tco/", {"vehicle": bmw.pk, "tenure_months": 60, "mileage_band": "standard",
                                                 "downpayment": "26580.00"}).data

    assert (data["ncd_percent"], data["insurance_annual"]) == ("0.00", "4784.40")


@pytest.mark.parametrize("value, stored", [("55", "55.00"), ("38.33", "38.33"), ("0", "0.00"), ("45.00", "45.00")])
def test_the_profile_accepts_the_six_ncd_steps(client, value, stored):
    body = {"monthly_budget": "5000.00", "preferred_tenure_months": 48, "annual_mileage_band": "standard",
            "ownership_preference": "retain", "shariah_compliant_required": False, "ncd_percent": value}

    response = client.put("/api/profile/financial/", body, format="json")

    assert response.status_code in (200, 201), response.data
    assert response.data["ncd_percent"] == stored


@pytest.mark.parametrize("value", ["50", "60", "-25", "38.3"])
def test_the_profile_refuses_any_other_ncd(client, value):
    body = {"monthly_budget": "5000.00", "preferred_tenure_months": 48, "annual_mileage_band": "standard",
            "ownership_preference": "retain", "shariah_compliant_required": False, "ncd_percent": value}

    response = client.put("/api/profile/financial/", body, format="json")

    assert response.status_code == 400
    assert "ncd_percent" in response.data


def test_a_profile_saved_without_ncd_reads_0(client):
    body = {"monthly_budget": "5000.00", "preferred_tenure_months": 48, "annual_mileage_band": "standard",
            "ownership_preference": "retain", "shariah_compliant_required": False}

    assert client.put("/api/profile/financial/", body, format="json").data["ncd_percent"] == "0.00"


def test_a_saved_snapshot_records_the_ncd_from_the_profile(client, regular_user):
    bmw = make_car("bmw")
    set_ncd(regular_user, "55")

    response = client.post("/api/scenarios/", {"title": "NCD 55", "vehicle": bmw.pk, "inputs": {
        "tenure_months": 60, "mileage_band": "standard", "downpayment": "26580.00", "include_tco": True,
    }}, format="json")

    assert response.status_code == 201, response.data
    payload = SavedScenario.objects.get(pk=response.data["id"]).payload
    assert payload["inputs"]["ncd_percent"] == "55.00"
    assert payload["tco"]["insurance_annual"] == "2152.98"
    assert payload["tco"]["tco_net"] == "227452.88"


def test_the_pdf_uses_the_same_figures_as_the_screen(client, regular_user, monkeypatch):
    captured = []
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: captured.append(html) or b"%PDF")
    bmw = make_car("bmw")
    set_ncd(regular_user, "55")
    q = {"vehicle": bmw.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "26580.00"}

    screen = client.get("/api/comparisons/", q).data
    response = client.post("/api/exports/pdf/", {**q, "chart_svg": ""}, format="json")

    assert response.status_code == 200
    for pathway in ("hire_purchase", "gfv_leasing", "subscription"):
        for field in ("monthly_instalment", "upfront_cash", "total_contract_outlay"):
            assert f"RM {D(screen[pathway][field]):,.2f}" in captured[0]


# --- Step 3: maintenance ceiling ----------------------------------------------------------------------------------


def test_the_911s_maintenance_is_capped_at_8000():
    # 1.0% x 1,430,000 = 14,300 > the 8,000 cap.
    costs = estimate_operating_costs(make_car("911"))

    assert costs.maintenance_annual == D("8000.00")
    assert costs.basis["maintenance"] == "1.0% of price, capped at RM 8,000 (floor RM 1,200)"


@pytest.mark.parametrize("key, expected", [
    ("bmw", "2658.00"), ("lexus", "3568.88"), ("c200", "2928.88"), ("macan", "4690.00"),
    ("alphard", "5480.00"), ("xc60", "3288.88"), ("xc90", "4783.77"), ("macan_ev", "4025.00"),
])
def test_every_other_dev_car_stays_under_the_cap(key, expected):
    costs = estimate_operating_costs(make_car(key))

    assert costs.maintenance_annual == D(expected)
    assert "capped" not in costs.basis["maintenance"]


def test_an_empty_cap_means_no_cap():
    OperatingCostRate.objects.filter(powertrain="petrol").update(maintenance_cap_annual=None)

    assert estimate_operating_costs(make_car("911")).maintenance_annual == D("14300.00")


# --- Step 4: the subscription fee and TCO movements -----------------------------------------------------------


# 36 months, standard band, NCD 0. fee = (P(1-G)/36 + P(1+G)/2 x 4.5%/12 + running/12) x 1.12;
# only `running` moves, so the fee moves by (change in running) / 12 x 1.12.
# Run 3 fix batch 6: G = 0.5179 + brand/powertrain points (was 0.50 + points); recomputed
# by a standalone script that first reproduced the old row of every car. Old rows:
# 911 28,606.08 / 28,018.08 / 25,032.87; Macan 9,352.97 / 9,358.72 / 8,228.25;
# Alphard 10,801.01 / 10,799.28 / 9,457.75; XC60 7,427.20 / 7,433.09 / 6,630.05;
# XC90 10,310.28 / 10,316.17 / 9,157.08; BMW 5,701.93 / 5,701.93 / 5,050.15.
STEP_4 = [
    # key, fee before, fee after, net cost after
    ("911", "27863.49", "27275.49", "24290.28"),       # running -6,300.00 -> -588.00
    ("macan", "9109.42", "9115.17", "7984.70"),        # running +61.60
    ("alphard", "10516.44", "10514.70", "9173.17"),    # running -18.60
    ("xc60", "7256.41", "7262.30", "6459.26"),         # running +63.10
    ("xc90", "10084.44", "10090.33", "8931.24"),       # running +63.10
    ("bmw", "5563.90", "5563.90", "4912.12"),          # unchanged
]


def pre_batch_configuration():
    """Every car on the saloon table and no maintenance cap - how the app
    costed cars before this batch."""
    VehicleModel.objects.update(road_tax_class="saloon")
    OperatingCostRate.objects.update(maintenance_cap_annual=None)


def subscription_36(car):
    return build_comparison(vehicle=car, tenure_months=36, mileage_band="standard",
                            downpayment=ten_percent(car))["subscription"]


@pytest.mark.parametrize("key, fee_before, fee_after, net_after", STEP_4)
def test_step_4_subscription_fees(key, fee_before, fee_after, net_after):
    car = make_car(key)

    after = subscription_36(car)
    pre_batch_configuration()
    car.refresh_from_db()
    before = subscription_36(car)

    assert (before["monthly_instalment"], after["monthly_instalment"]) == (D(fee_before), D(fee_after))
    assert after["net_cost_after_bundled_benefits"] == D(net_after)
    assert after["refundable_deposit"] == 2 * D(fee_after)  # the deposit moves with the fee


@pytest.mark.parametrize("key, delta", [
    ("macan", "308.00"), ("alphard", "-93.00"), ("xc60", "315.50"), ("xc90", "315.50"), ("911", "-31500.00"),
    ("bmw", "0.00"), ("lexus", "0.00"), ("c200", "0.00"), ("macan_ev", "0.00"),
])
def test_step_4_tco_moves_by_exactly_five_years_of_the_running_cost_change(key, delta):
    car = make_car(key)

    def tco_and_running():
        report = build_tco_report(vehicle=car, tenure_months=60, mileage_band="standard", downpayment=ten_percent(car))
        return report["tco_gross"], report["tco_net"], running(estimate_operating_costs(car))

    gross_after, net_after, running_after = tco_and_running()
    pre_batch_configuration()
    car.refresh_from_db()
    gross_before, net_before, running_before = tco_and_running()

    assert gross_after - gross_before == net_after - net_before == D(delta)
    assert D(delta) == 5 * (running_after - running_before)
