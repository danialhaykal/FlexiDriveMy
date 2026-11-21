"""Run 1 fix batch 4 (UC006 step 6): TCO for every pathway, and GFV explained.

Goldens: BMW 320i (RM 265,800, 2.8% flat), downpayment 26,580, standard band,
NCD 0 - the batch prompt's table, hand-computed independently in
run1_hand_calcs/r14_pathway_tco.py. Running costs 7,821.40 a year; resale(60)
= 97,787.82 (the fallback curve, no model deployed).

Run 3 fix batch 6: the standard residuals were recalibrated (36 / 48 / 60 months:
0.5179 / 0.4379 / 0.3679, were 0.50 / 0.42 / 0.35); the same hand-calc script, fed
the new residuals and the new 36-month fee 5,563.90, gives the goldens below. Gross
HP figures are unchanged (payments and running costs do not depend on the band).
"""

import importlib
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient

from apps.exports import tasks
from apps.policy.models import InterestRate
from apps.profiles.models import FinancialProfile
from apps.scenarios.models import SavedScenario
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal
seed = importlib.import_module("apps.policy.migrations.0018_seed_residual_estimates_and_default_contract_rule")
SUBSCRIPTION_TENURES = "Subscription plans run for 12, 24 or 36 months."


@pytest.fixture
def bmw():
    brand = Brand.objects.create(name="BMW", tier_code="2")
    seed.seed_brand_adjustments(django_apps)
    InterestRate.objects.create(brand=brand, rate_percent="2.8000", is_active=True)
    return VehicleModel.objects.create(
        brand=brand, name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN, msrp="265800.00",
        engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998,
    )


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


def tco(client, vehicle, tenure):
    response = client.get("/api/depreciation/tco/", {
        "vehicle": vehicle.pk, "tenure_months": tenure, "mileage_band": "standard", "downpayment": "26580.00",
    })
    assert response.status_code == 200, response.data
    return response.data


# (tenure, pathway, gross, net, net per month, horizon)
GOLDENS = [
    (36, "hire_purchase", "325001.48", "227213.66", "3786.89", 60),  # net was 231,971.48
    (36, "gfv_retain", "325001.48", "227213.66", "3786.89", 60),
    (36, "gfv_return", "171700.86", "171700.86", "4769.47", 36),  # was 176,458.68
    (36, "subscription", "211428.20", "200300.40", "5563.90", 36),  # was 216,673.34 / 205,269.48
    (48, "hire_purchase", "331699.64", "233911.82", "3898.53", 60),  # net was 238,669.64
    (48, "gfv_retain", "331699.64", "233911.82", "3898.53", 60),
    (48, "gfv_return", "207484.42", "207484.42", "4322.59", 48),  # was 212,242.24
    (60, "hire_purchase", "338397.80", "240609.98", "4010.17", 60),  # net was 245,367.80
    (60, "gfv_retain", "338397.80", "240609.98", "4010.17", 60),
    (60, "gfv_return", "240609.98", "240609.98", "4010.17", 60),
]


@pytest.mark.parametrize("tenure, pathway, gross, net, per_month, horizon", GOLDENS)
def test_every_golden_row(client, bmw, tenure, pathway, gross, net, per_month, horizon):
    entry = tco(client, bmw, tenure)["pathway_tco"][pathway]

    assert entry["available"] is True and entry["unavailable_reason"] is None
    assert (entry["gross"], entry["net"], entry["net_per_month"], entry["horizon_months"]) == (
        gross, net, per_month, horizon,
    )
    assert entry["amount_back"] == str(D(gross) - D(net))


def test_the_36_month_components_add_up(client, bmw):
    """HP payments 259,314.48 (true-up, 36 instalments); GFV payments are the
    comparison's outlay - downpayment - balloon = 121,656.66 (balloon 137,657.82); running costs
    7,821.40 x 5 = 39,107.00 (owner, 60 months) or x 3 = 23,464.20 (returner)."""
    p = tco(client, bmw, 36)["pathway_tco"]

    hp, retain, ret, sub = p["hire_purchase"], p["gfv_retain"], p["gfv_return"], p["subscription"]
    assert (hp["upfront_cash"], hp["payments_total"], hp["running_costs_total"]) == ("26580.00", "259314.48", "39107.00")
    assert (hp["resale_credit"], hp["settlement_debit"]) == ("97787.82", "0.00")
    assert (retain["payments_total"], retain["balloon_paid"], retain["resale_credit"]) == (
        "121656.66", "137657.82", "97787.82")
    assert (ret["payments_total"], ret["balloon_paid"], ret["running_costs_total"], ret["resale_credit"]) == (
        "121656.66", "0.00", "23464.20", "0.00")
    assert (sub["upfront_cash"], sub["payments_total"], sub["deposit_refund"], sub["running_costs_total"]) == (
        "11127.80", "200300.40", "11127.80", "0.00")
    # Today's fallback curve is anchored to the residual the balloon uses, so
    # the buy-back guarantee is worth nothing on this forecast - correct.
    assert retain["gfv_guarantee_value"] == ret["gfv_guarantee_value"] == "0.00"
    assert "gfv_guarantee_value" not in hp and "gfv_guarantee_value" not in sub


def test_unavailable_rows_keep_the_comparisons_own_reasons(client, bmw):
    at_48 = tco(client, bmw, 48)["pathway_tco"]["subscription"]
    at_84 = tco(client, bmw, 84)["pathway_tco"]

    assert (at_48["available"], at_48["unavailable_reason"], at_48["gross"]) == (False, SUBSCRIPTION_TENURES, None)
    gfv_reason = "GFV leasing isn't offered for 84 months - it is offered for 12 to 60 months in 12-month steps."
    assert at_84["gfv_retain"]["unavailable_reason"] == at_84["gfv_return"]["unavailable_reason"] == gfv_reason
    assert at_84["gfv_retain"]["available"] is at_84["gfv_return"]["available"] is False
    assert at_84["gfv_retain"]["gfv_guarantee_value"] is None
    assert at_84["subscription"]["unavailable_reason"] == SUBSCRIPTION_TENURES


@pytest.mark.parametrize("tenure", [36, 60, 84])
def test_the_hire_purchase_entry_is_exactly_tco_gross_and_net(client, bmw, tenure):
    data = tco(client, bmw, tenure)
    hp = data["pathway_tco"]["hire_purchase"]

    assert (hp["gross"], hp["net"]) == (data["tco_gross"], data["tco_net"])
    if tenure == 84:
        # The >60-month rule: the reducing-balance amount still owed at month 60.
        assert (hp["net"], hp["settlement_debit"]) == ("249723.39", "77461.81")  # net was 254,481.21 (resale 93,030.00)


def test_ncd_moves_only_the_entries_that_carry_running_costs(client, bmw, regular_user):
    """NCD 55%: insurance 4,784.40 -> 2,152.98, so running costs fall by
    2,631.42 a year - 13,157.10 over 60 months, 7,894.26 over 36 months.
    Subscription's net is fees only (its running costs are bundled)."""
    before = tco(client, bmw, 36)["pathway_tco"]
    FinancialProfile.objects.create(
        user=regular_user, monthly_budget="8000.00", preferred_tenure_months=36, annual_mileage_band="standard",
        ownership_preference="retain", ncd_percent=D("55.00"),
    )
    after = tco(client, bmw, 36)["pathway_tco"]

    def drop(key):
        return D(before[key]["net"]) - D(after[key]["net"])

    assert (drop("hire_purchase"), drop("gfv_retain"), drop("gfv_return"), drop("subscription")) == (
        D("13157.10"), D("13157.10"), D("7894.26"), D("0.00"))


def test_a_new_car_added_through_the_api_gets_pathway_tco_with_no_extra_data(admin_user, regular_user):
    admin = APIClient()
    admin.force_authenticate(user=admin_user)
    brand = Brand.objects.create(name="NewBrand", tier_code="3")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000", is_active=True)
    created = admin.post("/api/vehicles/models/", {
        "brand": brand.pk, "name": "Launch", "trim": "Edition", "body_segment": "suv", "msrp": "200000.00",
        "engine_capacity_kw": "150.00", "powertrain": "hybrid", "engine_capacity_cc": 1987,
    }, format="json")
    assert created.status_code == 201, created.data
    buyer = APIClient()
    buyer.force_authenticate(user=regular_user)

    data = buyer.get("/api/depreciation/tco/", {
        "vehicle": created.data["id"], "tenure_months": 36, "mileage_band": "standard", "downpayment": "20000.00",
    }).data

    assert set(data["pathway_tco"]) == {"hire_purchase", "gfv_retain", "gfv_return", "subscription"}
    assert all(entry["available"] for entry in data["pathway_tco"].values())


def test_the_guarantee_value_is_balloon_minus_the_forecast_when_a_model_is_below_it(client, bmw, tmp_path):
    """With a deployed model forecasting below the residual, GFV's buy-back
    guarantee is worth balloon - resale(t), and GFV-Retain credits the
    (lower) forecast at month 60."""
    import joblib

    from apps.depreciation.tests.test_tco_endpoint import DecliningResaleEstimator
    from apps.ml.models import ModelType, PredictionTarget, ProductionModel

    model_path = tmp_path / "model.joblib"
    joblib.dump(DecliningResaleEstimator(initial_value=1.0, monthly_decline=0.015), model_path)
    production = ProductionModel.get_singleton()
    production.model_type = ModelType.RANDOM_FOREST
    production.model_file_path = str(model_path)
    production.prediction_target = PredictionTarget.LOG_RESALE_PRICE
    production.save()

    data = tco(client, bmw, 36)
    retain = data["pathway_tco"]["gfv_retain"]
    resale_36 = D(data["monthly_forecast"][36]["predicted_resale_value"])

    assert data["model_degraded"] is False
    # balloon 137,657.82 (51.79% residual); resale(36) = 265,800 x (1 - 0.015 x 36) = 122,268.00
    assert resale_36 == D("122268.00")
    assert retain["gfv_guarantee_value"] == data["pathway_tco"]["gfv_return"]["gfv_guarantee_value"] == "15389.82"
    assert retain["resale_credit"] == data["monthly_forecast"][60]["predicted_resale_value"]


# --- GFV explained (B4) -------------------------------------------------------------------------------


def test_the_gfv_card_notes_come_from_the_comparison(client, bmw):
    gfv = client.get("/api/comparisons/", {
        "vehicle": bmw.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "26580.00",
    }).data["gfv_leasing"]

    assert gfv["end_of_term_note"] == (
        "At month 36 you choose: pay the balloon of RM 137,657.82 and keep the car, hand the car back (within the "
        "mileage and condition terms), or refinance the balloon."
    )
    assert gfv["same_total_note"] == (
        "Same total as Hire Purchase because both use the same flat rate on the same amount. GFV's benefits are the "
        "lower monthly payment and the guaranteed buy-back value."
    )


def test_a_gfv_recommendation_mentions_the_balloon(client, bmw):
    """60 months, income 10,000, DSR limit 40%: HP 4,545.18 is 45.5% (scored
    0), GFV 2,915.38 is 29.2% (was 2,994.68 before Run 3 fix batch 6), Subscription isn't offered at 60 months."""
    data = client.get("/api/scoring/", {
        "vehicle": bmw.pk, "tenure_months": 60, "mileage_band": "standard", "downpayment": "26580.00",
        "upfront_cash_preservation": 4, "maintenance_protection": 3, "ownership_equity": 2,
        "monthly_income": "10000", "max_dsr_percent": "40",
    }).data

    assert data["recommended_pathway"] == "gfv_leasing"
    assert data["rationale"].endswith(
        "This includes a balloon payment of RM 97,787.82 at month 60, or you can return the car."
    )


def test_a_hire_purchase_recommendation_says_nothing_about_a_balloon(client, bmw):
    data = client.get("/api/scoring/", {
        "vehicle": bmw.pk, "tenure_months": 60, "mileage_band": "standard", "downpayment": "26580.00",
        "upfront_cash_preservation": 2, "maintenance_protection": 2, "ownership_equity": 5,
        "monthly_income": "30000", "max_dsr_percent": "60",
    }).data

    assert data["recommended_pathway"] == "hire_purchase"
    assert "balloon" not in data["rationale"]


# --- the snapshot and the PDF carry it too -----------------------------------------------------------


def test_a_saved_snapshot_includes_pathway_tco(client, bmw, regular_user):
    response = client.post("/api/scenarios/", {"title": "Pathways", "vehicle": bmw.pk, "inputs": {
        "tenure_months": 36, "mileage_band": "standard", "downpayment": "26580.00", "include_tco": True,
    }}, format="json")

    payload = SavedScenario.objects.get(pk=response.data["id"]).payload
    assert payload["tco"]["pathway_tco"]["gfv_return"]["net"] == "171700.86"


def test_an_old_snapshot_without_pathway_tco_still_serializes(client, bmw, regular_user):
    old = {"tenureMonths": 36, "mileageBand": "standard", "downpayment": "26580.00",
           "comparison": {"gfv_leasing": {"balloon_payment": "132900.00"}}, "tco": {"tco_net": "1.00"}, "scoring": None}
    scenario = SavedScenario.objects.create(user=regular_user, title="Old", vehicle=bmw, payload=old)

    assert client.get(f"/api/scenarios/{scenario.pk}/").data["payload"] == old


def test_the_pdf_prints_the_pathway_table_and_the_end_of_term_sentence(client, bmw, monkeypatch):
    captured = []
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: captured.append(html) or b"%PDF")

    response = client.post("/api/exports/pdf/", {
        "vehicle": bmw.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "26580.00",
        "chart_svg": "",
    }, format="json")

    assert response.status_code == 200
    html = captured[0]
    assert "Total cost of ownership by pathway" in html
    for text in ("GFV - hand the car back", "over 36 months, car returned", "over 60 months, you keep the car",
                 "RM 171,700.86", "RM 4,769.47", "RM 200,300.40", "RM 11,127.80"):
        assert text in html
    assert "pay the balloon of RM 137,657.82 and keep the car" in html


def test_the_pdf_still_exports_when_the_tco_cannot_be_built(client, monkeypatch):
    captured = []
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: captured.append(html) or b"%PDF")
    brand = Brand.objects.create(name="NoRateBrand", tier_code="2")
    car = VehicleModel.objects.create(
        brand=brand, name="M", trim="X", body_segment=BodySegment.SEDAN, msrp="300000.00",
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
    )

    response = client.post("/api/exports/pdf/", {
        "vehicle": car.pk, "tenure_months": 36, "mileage_band": "standard", "downpayment": "30000.00",
        "chart_svg": "",
    }, format="json")

    assert response.status_code == 200
    assert "financing rate hasn&#x27;t been set up" in captured[0] or "financing rate hasn't been set up" in captured[0]
