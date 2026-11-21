"""Audit batch 5: the Subscription pathway block in build_comparison - the
refundable deposit (upfront cash, NOT outlay), the included km, and every
consumer treating an unavailable Subscription like any other unavailable
pathway (scoring, DSR, Arena, the TCO radar, the PDF rows)."""

from decimal import ROUND_HALF_UP, Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.comparisons.arena import build_arena, compute_arena_winners
from apps.comparisons.services import build_comparison
from apps.exports.comparison_rows import build_export_context
from apps.policy.mileage import included_km
from apps.policy.models import InterestRate, MileageBand, SubscriptionPlan, SubscriptionPolicy
from apps.scoring.services import build_dsr_simulation, build_suitability_scoring
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

D = Decimal


def q(value):
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def make_vehicle(name="A", msrp="300000.00"):
    brand = Brand.objects.create(name=f"SubBrand{name}", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="3.0000")
    vehicle = VehicleModel.objects.create(
        brand=brand, name=f"Model{name}", trim="X", body_segment=BodySegment.SEDAN, msrp=msrp,
        engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    vehicle.refresh_from_db()
    return vehicle


def comparison(vehicle, tenure=36, band=MileageBand.STANDARD):
    return build_comparison(vehicle=vehicle, tenure_months=tenure, mileage_band=band, downpayment=D("30000.00"))


# --- deposit and outlay -------------------------------------------------------------


@pytest.mark.parametrize("tenure", [12, 24, 36])
def test_upfront_cash_is_the_refundable_deposit_and_the_outlay_is_fees_only(tenure):
    sub = comparison(make_vehicle(), tenure)["subscription"]

    fee = sub["monthly_instalment"]
    assert sub["refundable_deposit"] == sub["upfront_cash"] == q(D("2") * fee)
    assert sub["total_contract_outlay"] == fee * tenure  # the deposit is refunded, so it is not in the outlay


def test_the_deposit_follows_the_policys_deposit_months_and_is_rounded_to_the_sen():
    vehicle = make_vehicle()
    SubscriptionPolicy.objects.update(deposit_months=D("1.50"))

    sub = comparison(vehicle, 24)["subscription"]

    assert sub["upfront_cash"] == q(D("1.5") * sub["monthly_instalment"])
    assert sub["total_contract_outlay"] == sub["monthly_instalment"] * 24


def test_a_zero_deposit_policy_restores_zero_upfront_cash():
    vehicle = make_vehicle()
    SubscriptionPolicy.objects.update(deposit_months=D("0"))

    assert comparison(vehicle)["subscription"]["upfront_cash"] == D("0.00")


def test_monthly_instalment_stays_the_fee_the_dsr_input_and_never_the_net_cost():
    vehicle = make_vehicle()

    sub = comparison(vehicle)["subscription"]

    assert sub["net_cost_after_bundled_benefits"] < sub["monthly_instalment"]
    result = build_dsr_simulation(
        vehicle=vehicle, tenure_months=36, mileage_band=MileageBand.STANDARD, downpayment=D("30000.00"),
        monthly_income=D("20000.00"), existing_monthly_commitments=D("0.00"), max_dsr_percent=D("60"),
    )
    assert result["pathways"]["subscription"]["monthly_instalment"] == sub["monthly_instalment"]


def test_the_net_cost_offset_still_comes_from_the_operating_cost_engine():
    vehicle = make_vehicle()
    sub = comparison(vehicle)["subscription"]

    # msrp 300,000, 1,998 cc petrol: road tax 379.00 + insurance 1.8% = 5,400.00
    # + maintenance 1.0% = 3,000.00 -> 8,779.00 a year = 731.5833/month
    assert sub["net_cost_after_bundled_benefits"] == q(sub["monthly_instalment"] - D("8779.00") / D(12))


def test_the_included_km_follows_the_selected_band():
    vehicle = make_vehicle()

    km = {band: comparison(vehicle, 36, band)["subscription"]["included_km_per_year"]
          for band in ("low", "standard", "high", "very_high")}

    # Run 3 fix batch 6: each band's limit from the one definition (was 10,000 / 20,000 / 30,000 / 40,000).
    assert km == {band: included_km(band) for band in km}
    assert km == {"low": 10000, "standard": 15000, "high": 25000, "very_high": 35000}


@pytest.mark.parametrize("tenure", [12, 24, 36])
def test_the_fee_never_falls_from_low_to_very_high_at_any_tenure(tenure):
    """Run 3 fix batch 6 (d): more km a year never makes a Subscription cheaper - the
    recalibrated residuals fall band by band, so the fee rises band by band."""
    vehicle = make_vehicle()

    fees = [comparison(vehicle, tenure, band)["subscription"]["monthly_instalment"] for band in MileageBand.values]

    assert fees == sorted(fees) and len(set(fees)) == len(fees)


def test_excess_mileage_is_described_but_never_added_to_any_total():
    vehicle = make_vehicle()
    standard = comparison(vehicle, 36, MileageBand.STANDARD)["subscription"]

    assert "RM 0.50/km" in standard["mileage_note"]
    # the outlay is exactly the fees: no excess-mileage amount hides in it
    assert standard["total_contract_outlay"] == standard["monthly_instalment"] * 36


# --- an unavailable Subscription is just another unavailable pathway -----------------


def test_scoring_ranks_only_the_available_pathways_when_subscription_is_unavailable():
    vehicle = make_vehicle()

    result = build_suitability_scoring(
        vehicle=vehicle, tenure_months=48, mileage_band=MileageBand.STANDARD, downpayment=D("30000.00"),
        priority_ratings={"upfront_cash_preservation": 3, "maintenance_protection": 3, "ownership_equity": 3},
        monthly_income=D("30000.00"), max_dsr_percent=D("60"),
    )

    assert "subscription" not in result["pathways"] and "subscription" not in result["ranking"]
    assert result["unavailable"] == {"subscription": "Subscription plans run for 12, 24 or 36 months."}
    assert set(result["ranking"]) == {"hire_purchase", "gfv_leasing"}
    assert result["recommended_pathway"] in {"hire_purchase", "gfv_leasing"}


def test_dsr_simulation_skips_an_unavailable_subscription():
    vehicle = make_vehicle()

    result = build_dsr_simulation(
        vehicle=vehicle, tenure_months=60, mileage_band=MileageBand.STANDARD, downpayment=D("30000.00"),
        monthly_income=D("30000.00"), existing_monthly_commitments=D("1000.00"), max_dsr_percent=D("60"),
    )

    assert set(result["pathways"]) == {"hire_purchase", "gfv_leasing"}
    assert "subscription" in result["unavailable"]


def test_arena_excludes_an_unavailable_subscription_from_its_race_only():
    a, b = make_vehicle("A", "300000.00"), make_vehicle("B", "250000.00")

    results = build_arena(
        vehicles=[a, b], tenure_months=48, mileage_band=MileageBand.STANDARD, downpayment=D("30000.00")
    )
    winners = compute_arena_winners(results)

    assert all(r["ok"] and r["comparison"]["subscription"] is None for r in results)
    assert winners["cheapest_subscription"] is None  # nothing to race
    assert winners["cheapest_hp"] is not None and winners["cheapest_gfv"] is not None


def test_the_tco_radar_and_endpoint_cope_with_an_unavailable_subscription(regular_user):
    vehicle = make_vehicle()
    client = APIClient()
    client.force_authenticate(user=regular_user)

    response = client.get(
        "/api/depreciation/tco/",
        {"vehicle": vehicle.id, "tenure_months": 60, "mileage_band": "standard", "downpayment": "30000.00"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert "subscription" not in response.data["risk_radar"]
    assert response.data["radar_unavailable"]["subscription"] == "Subscription plans run for 12, 24 or 36 months."


def test_a_subscription_with_a_deposit_scores_just_under_a_perfect_upfront_cash_score():
    """Scoring formulas are unchanged: upfront-cash score = 1 - upfront/price.
    Subscription's upfront cash is now its deposit, so it falls from 1.0."""
    vehicle = make_vehicle()

    result = build_suitability_scoring(
        vehicle=vehicle, tenure_months=36, mileage_band=MileageBand.STANDARD, downpayment=D("30000.00"),
        priority_ratings={"upfront_cash_preservation": 1, "maintenance_protection": 0, "ownership_equity": 0},
        monthly_income=D("100000.00"), max_dsr_percent=D("90"),
    )

    sub = comparison(vehicle)["subscription"]
    expected = (D("1") - sub["upfront_cash"] / vehicle.msrp) * 100
    assert result["pathways"]["subscription"]["upfront_cash"] == sub["upfront_cash"]
    assert result["pathways"]["subscription"]["suitability_score"] == q(expected)
    assert result["pathways"]["subscription"]["suitability_score"] < D("100.00")


# --- the PDF rows ------------------------------------------------------------------------


def test_the_pdf_subscription_rows_carry_source_deposit_and_mileage():
    vehicle = make_vehicle()
    data = comparison(vehicle, 36)

    extra = {row["label"]: row["value"] for row in build_export_context(data)["pathways"][2]["extra"]}

    assert extra["Fee source"] == "Estimate"
    assert extra["Fee basis"].startswith("Estimate: depreciation RM")
    assert extra["Refundable deposit (in upfront cash, returned at term end)"].startswith("RM ")
    assert extra["Included mileage"].startswith("Includes up to 15,000 km a year.")  # was 20,000 before Run 3 fix batch 6


def test_the_pdf_shows_a_provider_quote_as_such_and_an_old_snapshot_without_the_new_rows():
    vehicle = make_vehicle()
    SubscriptionPlan.objects.create(vehicle=vehicle, fee_monthly="7000.00")
    quote = comparison(vehicle, 36)
    assert {r["label"]: r["value"] for r in build_export_context(quote)["pathways"][2]["extra"]}["Fee source"] == (
        "Provider quote"
    )

    old = dict(quote)
    old["subscription"] = {
        "monthly_instalment": D("7000.00"), "upfront_cash": D("0.00"), "total_contract_outlay": D("252000.00"),
    }
    assert build_export_context(old)["pathways"][2]["extra"] == []
