"""Run 3 fix batch 5:
  F-24  with tied top ratings the rationale no longer claims the buyer weighted the
        first criterion - a three-way tie says so, a two-way tie names both;
  F-23  a DSR that is over the limit but reads as the limit at 2 dp gets a note
        with enough decimals ("Just over your 50% limit (50.00003%).").
No score, weight, DSR figure or recommendation changes - words only."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.policy.models import InterestRate
from apps.scoring import formulas
from apps.vehicles.models import BodySegment, Brand, VehicleModel

pytestmark = pytest.mark.django_db

SCORES = {"subscription": {"suitability_percent": Decimal("65.24")}, "gfv_leasing": {"suitability_percent": Decimal("40.00")}}


def rationale(u, m, o, pathway="subscription", **kw):
    weights = formulas.normalize_priority_weights(upfront_cash_preservation=u, maintenance_protection=m, ownership_equity=o)
    return formulas.build_rationale(pathway, weights, SCORES, **kw)


# --- F-24 ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("ratings", [(3, 3, 3), (1, 1, 1), (5, 5, 5)])
def test_a_three_way_tie_says_the_priorities_were_rated_equally(ratings):
    assert rationale(*ratings) == (
        "Subscription best matches your priorities, scoring 65.24% suitability - reflecting that you rated your "
        "priorities equally."
    )


def test_5_5_1_names_both_tied_criteria():
    assert rationale(5, 5, 1).endswith(
        "reflecting the equal weight you placed on preserving upfront cash and maintenance cost protection.")


def test_1_5_5_names_both_tied_criteria():
    assert rationale(1, 5, 5).endswith(
        "reflecting the equal weight you placed on maintenance cost protection and building ownership equity.")


def test_5_1_5_names_both_tied_criteria():
    assert rationale(5, 1, 5).endswith(
        "reflecting the equal weight you placed on preserving upfront cash and building ownership equity.")


@pytest.mark.parametrize("ratings, criterion", [
    ((5, 2, 1), "preserving upfront cash"), ((1, 5, 2), "maintenance cost protection"), ((2, 1, 5), "building ownership equity"),
])
def test_a_single_top_priority_keeps_its_wording(ratings, criterion):
    assert rationale(*ratings).endswith(f"reflecting the weight you placed on {criterion}.")


def test_the_gfv_balloon_sentence_still_follows_a_tie():
    text = rationale(3, 3, 3, pathway="gfv_leasing", gfv_balloon=Decimal("133900.00"), tenure_months=36)

    assert text == (
        "GFV Leasing best matches your priorities, scoring 40.00% suitability - reflecting that you rated your "
        "priorities equally. This includes a balloon payment of RM 133,900.00 at month 36, or you can return the car."
    )


# --- F-23 ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("ratio, limit, expected", [
    (Decimal("0.5000003445"), Decimal("50.00"), "Just over your 50% limit (50.00003%)."),
    (Decimal("0.50004"), Decimal("50.00"), "Just over your 50% limit (50.004%)."),
    (Decimal("0.4000001"), Decimal("40.00"), "Just over your 40% limit (40.00001%)."),
    (Decimal("0.375000001"), Decimal("37.50"), "Just over your 37.5% limit (37.5000001%)."),
    (Decimal("0.50000000000001"), Decimal("50.00"), "Just over your 50% limit."),
])
def test_a_dsr_just_over_the_limit_gets_a_note(ratio, limit, expected):
    assert formulas.dsr_just_over_note(ratio, limit) == expected


@pytest.mark.parametrize("ratio, limit", [
    (Decimal("0.5"), Decimal("50.00")),          # exactly at the limit: not over
    (Decimal("0.4999"), Decimal("50.00")),       # under
    (Decimal("0.5012"), Decimal("50.00")),       # 50.12% already reads as over
    (Decimal("0.50005"), Decimal("50.00")),      # rounds half-up to 50.01%: reads as over
])
def test_no_note_when_the_two_dp_figure_already_tells_the_truth(ratio, limit):
    assert formulas.dsr_just_over_note(ratio, limit) is None


@pytest.fixture
def bmw():
    brand = Brand.objects.create(name="BMW", tier_code="2")
    InterestRate.objects.create(brand=brand, rate_percent="2.8000")
    car = VehicleModel.objects.create(
        brand=brand, name="3 Series", trim="320i Sport", body_segment=BodySegment.SEDAN, msrp="267800.00",
        engine_capacity_kw="135.00", powertrain="petrol", engine_capacity_cc=1998,
    )
    car.refresh_from_db()
    return car


@pytest.fixture
def client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


RUN3_EXAMPLE = {"tenure_months": 36, "mileage_band": "standard", "downpayment": "26780.00", "monthly_income": "14514.75",
                "max_dsr_percent": "50"}


def test_the_run3_example_on_the_scoring_endpoint(client, bmw):
    response = client.get("/api/scoring/", {"vehicle": bmw.pk, **RUN3_EXAMPLE, "upfront_cash_preservation": 3,
                                           "maintenance_protection": 3, "ownership_equity": 3})

    assert response.status_code == 200, response.data
    hp = response.data["pathways"]["hire_purchase"]
    assert (hp["monthly_instalment"], hp["dsr_percent"], hp["exceeds_dsr"], hp["suitability_score"]) == (
        "7257.38", "50.00", True, "0.00")  # the figures are unchanged
    assert hp["dsr_note"] == "Just over your 50% limit (50.00003%)."
    assert response.data["rationale"].endswith("reflecting that you rated your priorities equally.")
    for other in set(response.data["pathways"]) - {"hire_purchase"}:
        assert response.data["pathways"][other]["dsr_note"] is None


def test_the_run3_example_on_the_dsr_simulator(client, bmw):
    response = client.get("/api/scoring/dsr-simulator/", {"vehicle": bmw.pk, **RUN3_EXAMPLE})

    assert response.status_code == 200, response.data
    hp = response.data["pathways"]["hire_purchase"]
    assert (hp["dsr_percent"], hp["exceeds_dsr"]) == ("50.00", True)
    assert hp["dsr_note"] == "Just over your 50% limit (50.00003%)."
