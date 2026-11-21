"""Audit batch 3: the PDF labels the dealer's rate as FLAT, shows the derived
effective rate beside it, carries the same explanatory note as the on-screen
table, and says "profit rate" for a user who prefers Islamic financing - a
wording change only, never a figure change."""

from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.exports import tasks
from apps.exports.comparison_rows import ISLAMIC_NOTE, RATES_NOTE, build_export_context
from apps.exports.rendering import build_report_html
from apps.policy.models import InterestRate, MileageBand, ResidualValueMatrix, SubscriptionPlan
from apps.profiles.models import AnnualMileageBand, FinancialProfile, OwnershipPreference
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal


def comparison(hp_effective="5.3118", gfv_effective="3.7556"):
    hp = {
        "monthly_instalment": D("5541.93"), "upfront_cash": D("26580.00"),
        "total_contract_outlay": D("292592.64"), "interest_rate_percent": D("2.8000"),
    }
    gfv = {
        "monthly_instalment": D("3216.18"), "upfront_cash": D("26580.00"), "total_contract_outlay": D("292592.64"),
        "balloon_payment": D("111636.00"), "residual_value_ratio": D("0.4200"),
    }
    if hp_effective is not None:
        hp["effective_rate_percent"] = D(hp_effective)
    if gfv_effective is not None:
        gfv["effective_rate_percent"] = D(gfv_effective)
    return {
        "tenure_months": 48, "downpayment": D("26580.00"), "mileage_band": MileageBand.STANDARD,
        "hire_purchase": hp, "gfv_leasing": gfv,
        "subscription": {
            "monthly_instalment": D("6500.00"), "upfront_cash": D("0.00"), "total_contract_outlay": D("312000.00"),
        },
    }


def rows_by_label(context):
    return {row["label"]: row for row in context["pathways"]}


def test_hire_purchase_row_says_flat_and_adds_the_effective_rate():
    hp = rows_by_label(build_export_context(comparison()))["Hire Purchase"]

    # Run 2 fix batch 1: 2 decimals like the screen ("2.80%"), not the stored 4 ("2.8000%").
    assert hp["extra"] == [
        {"label": "Flat rate (p.a.)", "value": "2.80%"},
        {"label": "Effective rate (p.a.)", "value": "≈ 5.31%"},
    ]


def test_gfv_row_keeps_its_residual_and_balloon_and_adds_the_effective_rate():
    gfv = rows_by_label(build_export_context(comparison()))["GFV Leasing"]

    assert [item["label"] for item in gfv["extra"]] == [
        "Residual value", "Balloon payment (due at term end)", "Effective rate (p.a.)"]
    assert gfv["extra"][-1]["value"] == "≈ 3.76%"


def test_gfv_row_shows_where_the_residual_came_from_when_the_comparison_carries_a_basis():
    data = comparison()
    data["gfv_leasing"]["residual_basis"] = "Estimate: 42% baseline for 48 months / standard mileage, 0 points BMW, 0 points petrol"

    gfv = rows_by_label(build_export_context(data))["GFV Leasing"]

    assert gfv["extra"][1] == {
        "label": "Residual basis",
        "value": "Estimate: 42% baseline for 48 months / standard mileage, 0 points BMW, 0 points petrol",
    }


@pytest.mark.parametrize("effective, shown", [("5.3050", "5.31"), ("5.3049", "5.30"), ("3.7556", "3.76")])
def test_the_effective_rate_is_shown_to_two_places_rounding_half_up(effective, shown):
    hp = rows_by_label(build_export_context(comparison(hp_effective=effective)))["Hire Purchase"]

    assert hp["extra"][-1]["value"] == f"≈ {shown}%"


def test_a_comparison_without_an_effective_rate_just_shows_the_flat_label():
    context = build_export_context(comparison(hp_effective=None, gfv_effective=None))

    hp = rows_by_label(context)["Hire Purchase"]
    gfv = rows_by_label(context)["GFV Leasing"]
    assert hp["extra"] == [{"label": "Flat rate (p.a.)", "value": "2.80%"}]
    assert all(item["label"] != "Effective rate (p.a.)" for item in gfv["extra"])


def test_the_rates_note_is_carried_for_everyone_and_the_islamic_note_only_for_those_who_prefer_it():
    plain = build_export_context(comparison())
    islamic = build_export_context(comparison(), prefers_islamic_financing=True)

    assert plain["notes"] == [RATES_NOTE]
    assert islamic["notes"] == [RATES_NOTE, ISLAMIC_NOTE]
    assert "31 March 2027" in RATES_NOTE and "reducing-balance" in RATES_NOTE
    assert ISLAMIC_NOTE == "Indicative: Islamic financing is not priced separately in this app."


def test_an_islamic_financing_preference_says_profit_rate_and_changes_no_figure():
    plain = build_export_context(comparison())
    islamic = build_export_context(comparison(), prefers_islamic_financing=True)

    hp = rows_by_label(islamic)["Hire Purchase"]
    assert hp["extra"][0] == {"label": "Profit rate (flat, p.a.)", "value": "2.80%"}
    assert not any("nterest" in item["label"] for row in islamic["pathways"] for item in row["extra"])
    for key in ("monthly_instalment", "upfront_cash", "total_contract_outlay"):
        assert [r[key] for r in islamic["pathways"]] == [r[key] for r in plain["pathways"]]


def test_the_notes_are_rendered_into_the_pdf_html():
    context = build_export_context(comparison(), prefers_islamic_financing=True)

    html = build_report_html(vehicle_label="BMW 3 Series 320i Sport", chart_svg="", **context)

    assert "Flat rate" not in html  # the Islamic variant says profit rate instead
    assert "Profit rate (flat, p.a.)" in html
    assert "Effective rate (p.a.): ≈ 5.31%" in html
    assert RATES_NOTE in html and ISLAMIC_NOTE in html


# --- through the endpoint: the flag comes from the requesting user's own profile ----------------


@pytest.fixture
def configured_vehicle():
    brand = Brand.objects.create(name="RateLabelBrand", tier_code="2")
    vehicle = VehicleModel.objects.create(
        brand=brand, name="Model", trim="X", body_segment=BodySegment.SEDAN, msrp="100000.00",
        engine_capacity_kw="90.00", powertrain="petrol", engine_capacity_cc=1498,
    )
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    ResidualValueMatrix.objects.create(
        brand=brand, tenure_months=36, mileage_band=MileageBand.STANDARD, residual_value_ratio="0.5000"
    )
    SubscriptionPlan.objects.create(vehicle=vehicle, fee_monthly="1450.00")
    return vehicle


def export_with_islamic_flag(regular_user, vehicle, monkeypatch, shariah):
    FinancialProfile.objects.create(
        user=regular_user, monthly_budget="3000.00", preferred_tenure_months=36,
        annual_mileage_band=AnnualMileageBand.KM_10000,
        ownership_preference=OwnershipPreference.RETAIN, shariah_compliant_required=shariah,
    )
    captured = {}
    monkeypatch.setattr(tasks, "build_report_html", lambda **kwargs: captured.update(kwargs) or "<html></html>")
    monkeypatch.setattr(tasks, "render_pdf_with_timeout", lambda html, timeout_seconds: b"%PDF-1.7 fake")
    client = APIClient()
    client.force_authenticate(user=regular_user)
    response = client.post(
        "/api/exports/pdf/",
        {"vehicle": vehicle.id, "tenure_months": 36, "mileage_band": MileageBand.STANDARD,
         "downpayment": "10000.00", "chart_svg": ""},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    return captured


def test_the_endpoint_uses_flat_wording_by_default(regular_user, configured_vehicle, monkeypatch):
    captured = export_with_islamic_flag(regular_user, configured_vehicle, monkeypatch, shariah=False)

    hp = next(row for row in captured["pathways"] if row["label"] == "Hire Purchase")
    assert hp["extra"][0]["label"] == "Flat rate (p.a.)"
    assert hp["extra"][1]["label"] == "Effective rate (p.a.)"
    assert captured["notes"] == [RATES_NOTE]


def test_the_endpoint_says_profit_rate_when_the_users_profile_prefers_islamic_financing(
    regular_user, configured_vehicle, monkeypatch
):
    captured = export_with_islamic_flag(regular_user, configured_vehicle, monkeypatch, shariah=True)

    hp = next(row for row in captured["pathways"] if row["label"] == "Hire Purchase")
    assert hp["extra"][0]["label"] == "Profit rate (flat, p.a.)"
    assert hp["monthly_instalment"] == "RM 2,725.00"  # same figure as without the preference
    assert captured["notes"] == [RATES_NOTE, ISLAMIC_NOTE]
