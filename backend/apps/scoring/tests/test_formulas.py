"""Formula-first tests for F007's MCDA scoring, independent of Django/DRF."""

from decimal import Decimal

import pytest

from apps.scoring import formulas


# --- Weight normalization (UC007 step 3) ------------------------------------


def test_normalize_priority_weights_sums_to_one():
    weights = formulas.normalize_priority_weights(
        upfront_cash_preservation=5, maintenance_protection=3, ownership_equity=2
    )

    assert weights["upfront_cash_preservation"] == Decimal("0.5")
    assert weights["maintenance_protection"] == Decimal("0.3")
    assert weights["ownership_equity"] == Decimal("0.2")
    assert sum(weights.values()) == Decimal("1.0")


def test_normalize_priority_weights_rejects_all_zero():
    with pytest.raises(ValueError):
        formulas.normalize_priority_weights(
            upfront_cash_preservation=0, maintenance_protection=0, ownership_equity=0
        )


# --- MCDA scoring against a manually reconciled example ---------------------


def test_scoring_manually_reconciled_example():
    """weights: 0.5 / 0.3 / 0.2 (upfront / maintenance / ownership).
    price=400000; upfront_cash: HP=40000, GFV=40000, Subscription=0.

    QA audit M4: upfront_cash_preservation is scored against the
    vehicle's own price, not a min-max spread across pathways - see
    formulas.score_upfront_cash_preservation's own docstring.
    cash score = 1 - upfront_cash/price: HP=1-40000/400000=0.90,
    GFV=0.90, Subscription=1-0/400000=1.00.
    maintenance_protection (fixed): HP=0, GFV=0, Subscription=1.
    ownership_equity (fixed): HP=1, GFV=0.5, Subscription=0.

    HP:           0.5*0.90 + 0.3*0 + 0.2*1.0 = 0.45 + 0 + 0.20 = 0.65
    GFV:          0.5*0.90 + 0.3*0 + 0.2*0.5 = 0.45 + 0 + 0.10 = 0.55
    Subscription: 0.5*1.00 + 0.3*1 + 0.2*0.0 = 0.50 + 0.3 + 0 = 0.80
    No DSR limit is hit, so final scores equal the raw weighted scores.
    """
    weights = formulas.normalize_priority_weights(
        upfront_cash_preservation=5, maintenance_protection=3, ownership_equity=2
    )
    upfront_cash_by_pathway = {
        "hire_purchase": Decimal("40000"),
        "gfv_leasing": Decimal("40000"),
        "subscription": Decimal("0"),
    }
    # High income, generous DSR limit: nothing gets zeroed here.
    dsr_by_pathway = {"hire_purchase": Decimal("0.1"), "gfv_leasing": Decimal("0.1"), "subscription": Decimal("0.05")}

    scores = formulas.calculate_pathway_scores(
        upfront_cash_by_pathway=upfront_cash_by_pathway,
        weights=weights,
        dsr_by_pathway=dsr_by_pathway,
        max_dsr=Decimal("0.4"),
        price=Decimal("400000"),
    )

    assert scores["hire_purchase"]["final_score"] == Decimal("0.65")
    assert scores["gfv_leasing"]["final_score"] == Decimal("0.55")
    assert scores["subscription"]["final_score"] == Decimal("0.80")
    assert scores["subscription"]["suitability_percent"] == Decimal("80.00")
    assert not any(scores[p]["exceeds_dsr"] for p in scores)


def test_subscription_always_scores_a_perfect_upfront_cash_score():
    """Subscription's upfront_cash is always 0, so 1 - 0/price = 1.0
    regardless of price or what HP/GFV's downpayment happens to be."""
    scores = formulas.score_upfront_cash_preservation(
        {"hire_purchase": Decimal("40000"), "gfv_leasing": Decimal("40000"), "subscription": Decimal("0")},
        price=Decimal("400000"),
    )
    assert scores["subscription"] == Decimal("1.0")


def test_upfront_cash_score_genuinely_responds_to_downpayment_size():
    """QA audit M4: the old min-max-across-pathways approach made HP's
    score always exactly 1.0 regardless of the real downpayment size
    (scale-invariant by construction: HP/GFV's upfront_cash are always
    identical to each other, so the spread was always exactly
    downpayment - 0, giving (downpayment-0)/downpayment = 1, always).
    Scored against the vehicle's own price instead: a near-zero
    downpayment scores close to 1.0, a downpayment close to the full
    price scores close to 0.0 - genuinely different.
    """
    price = Decimal("200000")

    tiny_downpayment_scores = formulas.score_upfront_cash_preservation(
        {"hire_purchase": Decimal("1"), "gfv_leasing": Decimal("1"), "subscription": Decimal("0")}, price=price
    )
    large_downpayment_scores = formulas.score_upfront_cash_preservation(
        {"hire_purchase": Decimal("199000"), "gfv_leasing": Decimal("199000"), "subscription": Decimal("0")},
        price=price,
    )

    # 1 - 1/200000 = 0.999995
    assert tiny_downpayment_scores["hire_purchase"] == Decimal("1") - Decimal("1") / Decimal("200000")
    # 1 - 199000/200000 = 0.005
    assert large_downpayment_scores["hire_purchase"] == Decimal("0.005")
    assert tiny_downpayment_scores["hire_purchase"] > large_downpayment_scores["hire_purchase"]
    assert tiny_downpayment_scores["gfv_leasing"] > large_downpayment_scores["gfv_leasing"]


# --- Hard DSR-zeroing rule (UC007 Rule 1) -----------------------------------


def test_dsr_override_zeroes_pathway_regardless_of_weighted_score():
    """weights entirely on ownership_equity: HP would otherwise win with
    the maximum possible raw score (1.0), since HP has the best ownership
    equity score. But HP's DSR (60%) exceeds the 40% limit, so it must be
    forced to 0 - "regardless of weighted score" (the project spec) - letting GFV
    (uncapped, raw score 0.5) win instead.
    """
    weights = formulas.normalize_priority_weights(
        upfront_cash_preservation=0, maintenance_protection=0, ownership_equity=1
    )
    upfront_cash_by_pathway = {
        "hire_purchase": Decimal("20000"),
        "gfv_leasing": Decimal("20000"),
        "subscription": Decimal("0"),
    }
    dsr_by_pathway = {
        "hire_purchase": Decimal("0.60"),  # 60% - exceeds the limit
        "gfv_leasing": Decimal("0.30"),
        "subscription": Decimal("0.00"),
    }

    scores = formulas.calculate_pathway_scores(
        upfront_cash_by_pathway=upfront_cash_by_pathway,
        weights=weights,
        dsr_by_pathway=dsr_by_pathway,
        max_dsr=Decimal("0.40"),
        # Weight on upfront_cash_preservation is 0 here, so the cash
        # score (and therefore this price choice) has no effect on the
        # weighted result - only ownership_equity (fixed, price-
        # independent) drives it.
        price=Decimal("200000"),
    )

    # HP's *raw* weighted score is still the maximum (proves the override
    # applies on top of, not instead of, the real weighted calculation).
    assert scores["hire_purchase"]["raw_score"] == Decimal("1.0")
    assert scores["hire_purchase"]["exceeds_dsr"] is True
    assert scores["hire_purchase"]["final_score"] == Decimal("0")
    assert scores["hire_purchase"]["suitability_percent"] == Decimal("0.00")

    assert scores["gfv_leasing"]["exceeds_dsr"] is False
    assert scores["gfv_leasing"]["final_score"] == Decimal("0.5")


def test_dsr_exactly_at_limit_does_not_exceed():
    weights = formulas.normalize_priority_weights(
        upfront_cash_preservation=1, maintenance_protection=1, ownership_equity=1
    )
    scores = formulas.calculate_pathway_scores(
        upfront_cash_by_pathway={"hire_purchase": Decimal("0"), "gfv_leasing": Decimal("0"), "subscription": Decimal("0")},
        weights=weights,
        dsr_by_pathway={"hire_purchase": Decimal("0.40"), "gfv_leasing": Decimal("0.10"), "subscription": Decimal("0.10")},
        max_dsr=Decimal("0.40"),
        # All upfront_cash are 0 here, so 1 - 0/price = 1.0 for every
        # pathway regardless of which price is used.
        price=Decimal("100000"),
    )
    assert scores["hire_purchase"]["exceeds_dsr"] is False  # equal to the limit, not exceeding it
