from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.policy.models import InterestRate, MileageBand, ResidualValueMatrix, SubscriptionPlan
from apps.vehicles.models import Brand, BodySegment, VehicleModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def user_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


@pytest.fixture
def brand():
    return Brand.objects.create(name="ReferenceBrand", tier_code="A")


@pytest.fixture
def vehicle(brand):
    # msrp matches the project spec's reference case price (P=400000).
    return VehicleModel.objects.create(
        brand=brand,
        name="Reference Model",
        trim="X",
        body_segment=BodySegment.SUV,
        msrp="400000.00",
        engine_capacity_kw="150.00",
        powertrain="petrol",
        engine_capacity_cc=1998,
    )


@pytest.fixture
def interest_rate(brand):
    return InterestRate.objects.create(brand=brand, rate_percent="3.0000")


@pytest.fixture
def residual_ratio(brand):
    return ResidualValueMatrix.objects.create(
        brand=brand,
        tenure_months=36,
        mileage_band=MileageBand.STANDARD,
        residual_value_ratio="0.5000",
    )


@pytest.fixture
def subscription_plan(vehicle):
    return SubscriptionPlan.objects.create(
        vehicle=vehicle,
        fee_monthly="2000.00",
        insurance_annual="3600.00",
        road_tax_annual="1200.00",
        maintenance_annual="1800.00",
    )


@pytest.fixture
def fully_configured(vehicle, interest_rate, residual_ratio, subscription_plan):
    return vehicle


def request_comparison(client, vehicle, tenure_months=36, mileage_band=MileageBand.STANDARD, downpayment="40000.00"):
    return client.get(
        "/api/comparisons/",
        {
            "vehicle": vehicle.id,
            "tenure_months": tenure_months,
            "mileage_band": mileage_band,
            "downpayment": downpayment,
        },
    )


# --- Access control -------------------------------------------------------


def test_requires_authentication(fully_configured):
    client = APIClient()
    response = request_comparison(client, fully_configured)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_vehicle_whose_brand_is_archived_is_rejected(user_client, fully_configured, brand):
    """QA audit H13: an archived brand's vehicles must not be comparable
    either, not just absent from the catalog - previously only the
    vehicle's own is_active was checked here.
    """
    brand.is_active = False
    brand.save(update_fields=["is_active"])

    response = request_comparison(user_client, fully_configured)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- The reference case, end to end through the real API -----------------


def test_gfv_reference_case_through_the_endpoint(user_client, fully_configured):
    response = request_comparison(user_client, fully_configured)

    assert response.status_code == status.HTTP_200_OK
    gfv = response.data["gfv_leasing"]
    # Decimal(...) on both sides is robust regardless of whether .data
    # holds Decimal or str internally.
    assert Decimal(gfv["balloon_payment"]) == Decimal("200000.00")
    assert Decimal(gfv["monthly_instalment"]) == Decimal("5344.44")

    # Confirm the actual over-the-wire JSON encodes currency as a string,
    # not a float - the frontend must display this exactly, never re-derive it.
    wire_json = response.json()
    assert wire_json["gfv_leasing"]["monthly_instalment"] == "5344.44"
    assert isinstance(wire_json["gfv_leasing"]["monthly_instalment"], str)


def test_hp_pathway_through_the_endpoint(user_client, fully_configured):
    response = request_comparison(user_client, fully_configured)

    hp = response.data["hire_purchase"]
    assert Decimal(hp["monthly_instalment"]) == Decimal("10900.00")
    assert Decimal(hp["upfront_cash"]) == Decimal("40000.00")
    assert Decimal(hp["total_contract_outlay"]) == Decimal("432400.00")  # 40000 + 10900*36


def test_subscription_pathway_through_the_endpoint(user_client, fully_configured):
    response = request_comparison(user_client, fully_configured)

    subscription = response.data["subscription"]
    # QA audit H8: monthly_instalment is the real, gross fee billed -
    # fee=2000.00 in full, never the netted-out comparison figure.
    assert Decimal(subscription["monthly_instalment"]) == Decimal("2000.00")
    # Audit batch 5: upfront cash is the refundable security deposit (policy
    # seed: 2 months of fee = 2 x 2000.00), returned at the end - so it is NOT
    # part of the outlay, which stays the fees alone.
    assert Decimal(subscription["upfront_cash"]) == Decimal("4000.00")
    assert Decimal(subscription["refundable_deposit"]) == Decimal("4000.00")
    assert Decimal(subscription["total_contract_outlay"]) == Decimal("72000.00")  # 2000 * 36
    # The fixture's plan is a provider quote, used exactly.
    assert subscription["fee_source"] == "quote"
    assert subscription["fee_basis"] == "Provider quote - fixed fee"
    # the standard band's limit, from the one band definition (Run 3 fix batch 6: 15,000, was 20,000)
    assert subscription["included_km_per_year"] == 15000
    assert subscription["mileage_note"] == (
        "Includes up to 15,000 km a year. Kilometres above that are billed per km "
        "(RM 0.50/km under the default contract rule)."
    )
    # NetCost (the project spec's "value-added offset" formula) is kept as
    # informational context only. Audit batch 2: the offset no longer uses
    # the plan's own cost columns (3600+1200+1800) - it comes from the one
    # operating-cost engine for THIS vehicle (msrp 400,000, 1,998 cc petrol SUV,
    # so the NON-SALOON road-tax table since run 1 fix batch 3; was 379.00 saloon):
    #   road tax    = 360 + (1998-1800)*0.40          =    439.20
    #   insurance   = 1.8% * 400,000                  =  7,200.00
    #   maintenance = max(1.0% * 400,000, floor 1,200) =  4,000.00 (under the 8,000 cap)
    #   offset = 11,639.20 / 12 = 969.9333...  ->  net = 2000 - 969.9333 = 1030.07
    assert Decimal(subscription["net_cost_after_bundled_benefits"]) == Decimal("1030.07")
    assert subscription["net_cost_unavailable_reason"] is None


def test_subscription_offset_matches_the_tco_tabs_costs_for_the_same_vehicle(user_client, fully_configured):
    """One source of truth: the Subscription offset is (road tax + insurance
    + maintenance) / 12 of the SAME figures the TCO tab shows."""
    from apps.comparisons.formulas import calculate_subscription_net_cost
    from apps.policy.operating_costs import estimate_operating_costs

    comparison = request_comparison(user_client, fully_configured).data
    tco = user_client.get(
        "/api/depreciation/tco/",
        {"vehicle": fully_configured.id, "tenure_months": 36, "mileage_band": MileageBand.STANDARD, "downpayment": "40000.00"},
    ).data

    annual = Decimal(tco["road_tax_annual"]) + Decimal(tco["insurance_annual"]) + Decimal(tco["maintenance_annual"])
    expected_net = calculate_subscription_net_cost(
        Decimal("2000.00"), Decimal(tco["insurance_annual"]), Decimal(tco["road_tax_annual"]),
        Decimal(tco["maintenance_annual"]),
    )
    assert Decimal(comparison["subscription"]["net_cost_after_bundled_benefits"]) == expected_net
    assert annual == Decimal("11639.20")  # 439.20 (non-saloon SUV) + 7,200.00 + 4,000.00
    costs = estimate_operating_costs(fully_configured)
    assert costs.road_tax_annual + costs.insurance_annual + costs.maintenance_annual == annual


def test_the_plans_own_deprecated_cost_columns_are_ignored(user_client, fully_configured, subscription_plan):
    SubscriptionPlan.objects.filter(pk=subscription_plan.pk).update(
        insurance_annual="99999.00", road_tax_annual="99999.00", maintenance_annual="99999.00"
    )

    response = request_comparison(user_client, fully_configured)

    assert Decimal(response.data["subscription"]["net_cost_after_bundled_benefits"]) == Decimal("1030.07")


def test_subscription_still_returns_with_no_offset_when_the_vehicle_cannot_be_costed(user_client, fully_configured):
    VehicleModel.objects.filter(pk=fully_configured.pk).update(powertrain="", engine_capacity_cc=None)

    response = request_comparison(user_client, fully_configured)

    assert response.status_code == status.HTTP_200_OK
    subscription = response.data["subscription"]
    assert Decimal(subscription["monthly_instalment"]) == Decimal("2000.00")  # the fee itself still shows
    assert Decimal(subscription["total_contract_outlay"]) == Decimal("72000.00")
    assert subscription["net_cost_after_bundled_benefits"] is None
    assert "is missing its specs (powertrain / engine capacity)" in subscription["net_cost_unavailable_reason"]
    assert response.data["unavailable"] == {}  # the pathway itself is not "unavailable"


def test_all_three_pathways_returned_in_a_single_call(user_client, fully_configured):
    response = request_comparison(user_client, fully_configured)

    assert response.status_code == status.HTTP_200_OK
    assert set(response.data.keys()) >= {"hire_purchase", "gfv_leasing", "subscription"}


# --- Missing/null config -> that ONE pathway only, never a blanket
# failure (UC005's own purpose: show HP/GFV/Subscription simultaneously
# side-by-side - a gap in one pathway's config has nothing to do with
# whether the other two can be computed). Always 200 once the request
# itself is valid; the affected pathway is null with its reason recorded
# in `unavailable`, the other pathways are present and correct.


def test_missing_interest_rate_only_disables_hp_and_gfv(user_client, vehicle, residual_ratio, subscription_plan):
    # HP and GFV both depend on the brand's interest rate; Subscription
    # doesn't.
    response = request_comparison(user_client, vehicle)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["hire_purchase"] is None
    assert response.data["gfv_leasing"] is None
    assert response.data["subscription"] is not None
    assert "financing rate hasn't been set up" in response.data["unavailable"]["hire_purchase"]
    assert "financing rate hasn't been set up" in response.data["unavailable"]["gfv_leasing"]


def test_inactive_interest_rate_only_disables_hp_and_gfv(
    user_client, vehicle, residual_ratio, subscription_plan, brand
):
    InterestRate.objects.create(brand=brand, rate_percent="3.0000", is_active=False)

    response = request_comparison(user_client, vehicle)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["hire_purchase"] is None
    assert response.data["gfv_leasing"] is None
    assert response.data["subscription"] is not None
    assert "financing rate hasn't been set up" in response.data["unavailable"]["hire_purchase"]
    assert "financing rate hasn't been set up" in response.data["unavailable"]["gfv_leasing"]


def test_no_residual_override_still_offers_gfv_from_the_estimate(
    user_client, vehicle, interest_rate, subscription_plan
):
    """Audit batch 4 (D2/F1): a brand with no residual rows used to show
    "GFV isn't offered" - the wrong reason - so every new brand silently had
    no GFV. Now the estimator supplies the ratio: here the 36-month/standard
    baseline, nothing keyed anywhere. Run 3 fix batch 6: that baseline is 0.5179
    (was 0.50), so the estimate no longer lands on the project spec's 50% reference case -
    which stays covered through the override fixture (test above) and test_formulas.
    By hand: balloon 400,000 x 0.5179 = 207,160.00; monthly (360,000 - 207,160) / 36
    + 360,000 x 0.03 / 12 = 4,245.5556 + 900.00 = 5,145.56."""
    response = request_comparison(user_client, vehicle)

    assert response.status_code == status.HTTP_200_OK
    gfv = response.data["gfv_leasing"]
    assert gfv is not None
    assert response.data["unavailable"] == {}
    assert Decimal(gfv["residual_value_ratio"]) == Decimal("0.5179")
    assert gfv["residual_basis"] == (
        "Estimate: 51.79% baseline for 36 months / standard mileage, 0 points ReferenceBrand, 0 points petrol"
    )
    assert Decimal(gfv["balloon_payment"]) == Decimal("207160.00")
    assert Decimal(gfv["monthly_instalment"]) == Decimal("5145.56")


def test_a_tenure_with_no_baseline_only_disables_gfv_the_live_bug_scenario(
    user_client, vehicle, interest_rate, residual_ratio, subscription_plan
):
    """The exact live bug: an unsupported tenure used to wipe out the whole
    response (a blanket 400) even though Hire Purchase and Subscription had
    everything they needed. Now: 200, HP and Subscription present and
    correctly computed, only GFV unavailable. 40 months is not a 12-month
    step, so it has neither a baseline nor an override."""
    response = request_comparison(user_client, vehicle, tenure_months=40)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["gfv_leasing"] is None
    # Audit batch 5: Subscription also runs only on the baseline's 12-month
    # steps within 12-36, so it is unavailable at 40 months too - each with
    # its own plain reason.
    assert set(response.data["unavailable"].keys()) == {"gfv_leasing", "subscription"}
    # Plain wording listing the tenures that ARE offered (queried from the
    # real tables, not hard-coded).
    assert response.data["unavailable"]["gfv_leasing"] == (
        "GFV leasing isn't offered for 40 months - it is offered for 12 to 60 months in 12-month steps."
    )
    assert response.data["unavailable"]["subscription"] == "Subscription plans run for 12, 24 or 36 months."

    # HP: (400000-40000)/40 + (400000-40000)*0.03/12 = 9000.00 + 900.00 = 9900.00.
    hp = response.data["hire_purchase"]
    assert hp is not None
    assert Decimal(hp["monthly_instalment"]) == Decimal("9900.00")
    assert Decimal(hp["upfront_cash"]) == Decimal("40000.00")

    assert response.data["subscription"] is None


def test_a_tenure_beyond_60_months_has_no_gfv(user_client, vehicle, interest_rate, residual_ratio, subscription_plan):
    response = request_comparison(user_client, vehicle, tenure_months=72)

    assert response.data["gfv_leasing"] is None
    assert response.data["hire_purchase"] is not None
    assert "12 to 60 months" in response.data["unavailable"]["gfv_leasing"]


def test_an_override_for_one_band_leaves_the_other_bands_on_the_estimate(
    user_client, vehicle, interest_rate, residual_ratio, subscription_plan
):
    # residual_ratio fixture overrides 'standard' only; 'high' falls back to
    # the baseline (36 months / high = 0.4750 since Run 3 fix batch 6; was 0.45).
    high = request_comparison(user_client, vehicle, mileage_band=MileageBand.HIGH)
    standard = request_comparison(user_client, vehicle)

    assert Decimal(high.data["gfv_leasing"]["residual_value_ratio"]) == Decimal("0.4750")
    assert high.data["gfv_leasing"]["residual_basis"].startswith("Estimate: 47.5% baseline for 36 months / high")
    assert standard.data["gfv_leasing"]["residual_basis"] == (
        "Admin override for ReferenceBrand, 36 months, standard mileage"
    )


def test_a_car_with_no_plan_gets_an_estimated_subscription(user_client, vehicle, interest_rate, residual_ratio):
    """Audit batch 5 (C1): a missing plan used to make Subscription "not
    available" for every car added after the seed. Now the fee is estimated.
    Hand derivation, msrp 400,000, 36 months, residual 0.50 (the override
    fixture), costs 439.20 (1,998 cc SUV, non-saloon table since run 1 fix
    batch 3) + 7,200.00 + 4,000.00 = 11,639.20 a year:
      depreciation = 400000 x 0.50 / 36            = 5,555.5556
      funding      = 400000 x 1.50 / 2 x 4.5% / 12 = 1,125.0000
      bundled      = 11639.20 / 12                 =   969.9333
      fee = (5555.5556 + 1125 + 969.9333) x 1.12 = 8,568.5476 -> 8,568.55
    (was 8,562.93 on the saloon table: bundled 964.9167)
    """
    response = request_comparison(user_client, vehicle)

    assert response.status_code == status.HTTP_200_OK
    subscription = response.data["subscription"]
    assert subscription is not None
    assert response.data["unavailable"] == {}
    assert subscription["fee_source"] == "estimate"
    assert Decimal(subscription["monthly_instalment"]) == Decimal("8568.55")
    assert subscription["fee_basis"] == (
        "Estimate: depreciation RM 5,555.56 + funding RM 1,125.00 + road tax, insurance and maintenance "
        "RM 969.93, plus 12% margin"
    )
    # deposit = 2 x fee; outlay = fees only
    assert Decimal(subscription["refundable_deposit"]) == Decimal("17137.10")
    assert Decimal(subscription["upfront_cash"]) == Decimal("17137.10")
    assert Decimal(subscription["total_contract_outlay"]) == Decimal("308467.80")  # 8568.55 x 36


def test_subscription_is_only_unavailable_for_a_tenure_it_does_not_run(
    user_client, vehicle, interest_rate, residual_ratio, subscription_plan
):
    response = request_comparison(user_client, vehicle, tenure_months=48)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["subscription"] is None
    assert response.data["hire_purchase"] is not None
    assert response.data["gfv_leasing"] is not None
    assert response.data["unavailable"] == {"subscription": "Subscription plans run for 12, 24 or 36 months."}


def test_nothing_configured_still_returns_200_with_hp_and_gfv_unavailable_but_a_subscription_estimate(
    user_client, vehicle
):
    response = request_comparison(user_client, vehicle)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["hire_purchase"] is None
    assert response.data["gfv_leasing"] is None
    # Subscription needs no interest rate and no plan (audit batch 5).
    assert response.data["subscription"] is not None
    assert set(response.data["unavailable"].keys()) == {"hire_purchase", "gfv_leasing"}
    # The request's own echoed fields are still correct even though every
    # pathway is unavailable.
    assert response.data["vehicle_id"] == vehicle.id


# --- C6: 10% minimum downpayment (FYP1 Ch.2 2.1.1 / A3 Update) -----------


def test_exactly_10_percent_downpayment_is_accepted(user_client, fully_configured):
    # msrp=400000.00 -> minimum is exactly 40000.00, request_comparison's
    # own default - every other test in this file already relies on this
    # boundary passing; this test names it explicitly.
    response = request_comparison(user_client, fully_configured, downpayment="40000.00")
    assert response.status_code == status.HTTP_200_OK


def test_one_sen_below_10_percent_downpayment_is_rejected(user_client, fully_configured):
    response = request_comparison(user_client, fully_configured, downpayment="39999.99")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Minimum downpayment is 10% of the vehicle price (RM 40,000.00)." in str(
        response.data["downpayment"]
    )


# --- C5: GFV must never go negative --------------------------------------


def test_gfv_at_exactly_the_financed_boundary_gives_a_pure_interest_instalment(
    user_client, vehicle, interest_rate, residual_ratio, subscription_plan
):
    # balloon = 400000*0.50 = 200000.00; financed_amount = price -
    # downpayment - balloon = 0 at downpayment=200000.00 - allowed, and
    # gives a pure-interest instalment: 0/36 + (400000-200000)*0.03/12
    # = 500.00.
    response = request_comparison(user_client, vehicle, downpayment="200000.00")

    assert response.status_code == status.HTTP_200_OK
    gfv = response.data["gfv_leasing"]
    assert gfv is not None
    assert Decimal(gfv["monthly_instalment"]) == Decimal("500.00")
    assert "gfv_leasing" not in response.data["unavailable"]


def test_gfv_one_sen_over_the_financed_boundary_is_unavailable_not_negative(
    user_client, vehicle, interest_rate, residual_ratio, subscription_plan
):
    response = request_comparison(user_client, vehicle, downpayment="200000.01")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["gfv_leasing"] is None
    assert "exceeds the amount financed under GFV" in response.data["unavailable"]["gfv_leasing"]
    assert "RM 200,000.00" in response.data["unavailable"]["gfv_leasing"]
    # HP and Subscription are unaffected by GFV's own balloon math.
    assert response.data["hire_purchase"] is not None
    assert response.data["subscription"] is not None


# --- Request validation ----------------------------------------------------


@pytest.mark.parametrize("tenure_months", [11, 109, 0, -5])
def test_tenure_outside_12_to_108_rejected(user_client, fully_configured, tenure_months):
    response = request_comparison(user_client, fully_configured, tenure_months=tenure_months)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "tenure_months" in response.data


def test_downpayment_must_be_less_than_price(user_client, fully_configured):
    response = request_comparison(user_client, fully_configured, downpayment="400000.00")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "downpayment" in response.data


def test_downpayment_cannot_be_negative(user_client, fully_configured):
    response = request_comparison(user_client, fully_configured, downpayment="-1.00")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "downpayment" in response.data


def test_negative_downpayment_uses_the_exact_uc003_copy(user_client, fully_configured):
    # QA audit L1: UC003's own alternate-flow copy, not DRF's generic
    # "Ensure this value is greater than or equal to 0." text.
    response = request_comparison(user_client, fully_configured, downpayment="-1.00")
    assert response.data["downpayment"][0] == "Please enter a valid positive numerical amount."


def test_unknown_vehicle_rejected(user_client):
    response = user_client.get(
        "/api/comparisons/",
        {"vehicle": 999999, "tenure_months": 36, "mileage_band": MileageBand.STANDARD, "downpayment": "1000.00"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "vehicle" in response.data


def test_archived_vehicle_rejected(user_client, fully_configured):
    fully_configured.is_active = False
    fully_configured.save(update_fields=["is_active"])

    response = request_comparison(user_client, fully_configured)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "vehicle" in response.data
