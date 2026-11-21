"""Direct unit tests of compute_arena_winners against hand-built input
dicts - same reasoning as test_formulas.py existing for the pathway
math: no Django/DRF/database needed, this is a plain function over
plain data."""

from decimal import Decimal

from apps.comparisons.arena import compute_arena_winners


def _ok_entry(vehicle_id, hp, gfv, subscription, tco_net, model_degraded=False):
    return {
        "vehicle_id": vehicle_id,
        "ok": True,
        "error": None,
        "comparison": {
            "hire_purchase": {"monthly_instalment": Decimal(hp)},
            "gfv_leasing": {"monthly_instalment": Decimal(gfv)},
            "subscription": {"monthly_instalment": Decimal(subscription)},
        },
        "tco_net": Decimal(tco_net),
        "model_degraded": model_degraded,
    }


def _error_entry(vehicle_id, error="Downpayment must be less than the vehicle's price."):
    return {
        "vehicle_id": vehicle_id,
        "ok": False,
        "error": error,
        "comparison": None,
        "tco_net": None,
        "model_degraded": None,
    }


def _winner(vehicle_id, tied_with):
    return {"winner_id": vehicle_id, "tied_with": tied_with}


def test_each_category_picks_the_genuinely_cheapest_vehicle():
    results = [
        _ok_entry(1, hp="1200.00", gfv="900.00", subscription="700.00", tco_net="90000.00"),
        _ok_entry(2, hp="1000.00", gfv="950.00", subscription="750.00", tco_net="85000.00"),
        _ok_entry(3, hp="1100.00", gfv="800.00", subscription="650.00", tco_net="95000.00"),
    ]

    winners = compute_arena_winners(results)

    assert winners["cheapest_hp"] == _winner(2, [2])  # 1000.00 is the lowest HP
    assert winners["cheapest_gfv"] == _winner(3, [3])  # 800.00 is the lowest GFV
    assert winners["cheapest_subscription"] == _winner(3, [3])  # 650.00 is the lowest subscription
    assert winners["lowest_tco"] == _winner(2, [2])  # 85000.00 is the lowest net TCO


def test_none_when_fewer_than_2_vehicles_succeeded():
    results = [
        _ok_entry(1, hp="1200.00", gfv="900.00", subscription="700.00", tco_net="90000.00"),
        _error_entry(2),
    ]

    winners = compute_arena_winners(results)

    assert winners == {
        "cheapest_hp": None,
        "cheapest_gfv": None,
        "cheapest_subscription": None,
        "lowest_tco": None,
    }


def test_none_when_zero_vehicles_succeeded():
    results = [_error_entry(1), _error_entry(2)]

    winners = compute_arena_winners(results)

    assert winners == {
        "cheapest_hp": None,
        "cheapest_gfv": None,
        "cheapest_subscription": None,
        "lowest_tco": None,
    }


def test_failed_vehicle_is_excluded_but_others_still_win_categories():
    results = [
        _ok_entry(1, hp="1200.00", gfv="900.00", subscription="700.00", tco_net="90000.00"),
        _ok_entry(2, hp="1000.00", gfv="950.00", subscription="750.00", tco_net="85000.00"),
        _error_entry(3),
    ]

    winners = compute_arena_winners(results)

    assert winners["cheapest_hp"] == _winner(2, [2])
    assert winners["cheapest_gfv"] == _winner(1, [1])
    assert winners["cheapest_subscription"] == _winner(1, [1])
    assert winners["lowest_tco"] == _winner(2, [2])


def test_degraded_vehicles_excluded_from_lowest_tco_but_not_other_categories():
    # A degraded vehicle still has real HP/GFV/subscription figures (those
    # don't depend on the ML model at all) - only the TCO race, which
    # depends on a real (non-degraded) resale-value prediction, excludes it.
    results = [
        _ok_entry(1, hp="1200.00", gfv="900.00", subscription="700.00", tco_net="80000.00", model_degraded=True),
        _ok_entry(2, hp="1000.00", gfv="950.00", subscription="750.00", tco_net="85000.00", model_degraded=False),
    ]

    winners = compute_arena_winners(results)

    assert winners["cheapest_hp"] == _winner(2, [2])  # still computed normally
    # Only one non-degraded candidate for TCO - not enough to have a "winner".
    assert winners["lowest_tco"] is None


def test_lowest_tco_is_none_when_every_vehicle_is_degraded():
    results = [
        _ok_entry(1, hp="1200.00", gfv="900.00", subscription="700.00", tco_net="80000.00", model_degraded=True),
        _ok_entry(2, hp="1000.00", gfv="950.00", subscription="750.00", tco_net="75000.00", model_degraded=True),
    ]

    winners = compute_arena_winners(results)

    assert winners["cheapest_hp"] == _winner(2, [2])  # unaffected by degradation
    assert winners["lowest_tco"] is None


def test_lowest_tco_is_picked_correctly_when_only_some_vehicles_are_degraded():
    results = [
        _ok_entry(1, hp="1200.00", gfv="900.00", subscription="700.00", tco_net="70000.00", model_degraded=True),
        _ok_entry(2, hp="1000.00", gfv="950.00", subscription="750.00", tco_net="85000.00", model_degraded=False),
        _ok_entry(3, hp="1100.00", gfv="800.00", subscription="650.00", tco_net="82000.00", model_degraded=False),
    ]

    winners = compute_arena_winners(results)

    # Vehicle 1 has the lowest tco_net (70000.00) but is degraded, so it's
    # excluded from the race - vehicle 3 (82000.00) correctly wins among
    # the two genuinely-comparable (non-degraded) candidates.
    assert winners["lowest_tco"] == _winner(3, [3])


def test_empty_results_list_is_all_none():
    assert compute_arena_winners([]) == {
        "cheapest_hp": None,
        "cheapest_gfv": None,
        "cheapest_subscription": None,
        "lowest_tco": None,
    }


# --- L10: ties are reported, not silently resolved to one "winner" ---------


def test_two_vehicles_tied_at_the_cheapest_hp_are_both_reported():
    results = [
        _ok_entry(1, hp="1000.00", gfv="900.00", subscription="700.00", tco_net="90000.00"),
        _ok_entry(2, hp="1000.00", gfv="950.00", subscription="750.00", tco_net="85000.00"),
        _ok_entry(3, hp="1100.00", gfv="800.00", subscription="650.00", tco_net="95000.00"),
    ]

    winners = compute_arena_winners(results)

    assert winners["cheapest_hp"]["tied_with"] == [1, 2]
    assert winners["cheapest_hp"]["winner_id"] in winners["cheapest_hp"]["tied_with"]
    # Not tied, so a single-element list each - same shape either way.
    assert winners["cheapest_gfv"] == _winner(3, [3])


def test_all_three_vehicles_tied_lists_all_three():
    results = [
        _ok_entry(1, hp="1000.00", gfv="900.00", subscription="700.00", tco_net="90000.00"),
        _ok_entry(2, hp="1000.00", gfv="900.00", subscription="700.00", tco_net="90000.00"),
        _ok_entry(3, hp="1000.00", gfv="900.00", subscription="700.00", tco_net="90000.00"),
    ]

    winners = compute_arena_winners(results)

    assert winners["cheapest_hp"]["tied_with"] == [1, 2, 3]
    assert winners["cheapest_gfv"]["tied_with"] == [1, 2, 3]
    assert winners["cheapest_subscription"]["tied_with"] == [1, 2, 3]
    assert winners["lowest_tco"]["tied_with"] == [1, 2, 3]


def test_a_degraded_vehicle_tied_on_tco_with_a_non_degraded_one_is_still_excluded():
    """A tie is only ever reported among candidates actually IN the race -
    a degraded vehicle whose tco_net happens to numerically match a
    non-degraded one is still excluded from the TCO race entirely, same
    as before L10 (ties don't change WHO is eligible, only how a genuine
    tie among eligible candidates is reported)."""
    results = [
        _ok_entry(1, hp="1200.00", gfv="900.00", subscription="700.00", tco_net="85000.00", model_degraded=True),
        _ok_entry(2, hp="1000.00", gfv="950.00", subscription="750.00", tco_net="85000.00", model_degraded=False),
        _ok_entry(3, hp="1100.00", gfv="800.00", subscription="650.00", tco_net="90000.00", model_degraded=False),
    ]

    winners = compute_arena_winners(results)

    assert winners["lowest_tco"] == _winner(2, [2])
