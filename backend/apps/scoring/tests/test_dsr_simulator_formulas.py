"""Formula-first tests for Sprint 11's standalone DSR Simulator, independent
of Django/DRF - same pattern as test_formulas.py."""

from decimal import Decimal

from apps.scoring import formulas


def test_zero_existing_commitments_matches_simple_dsr_ratio():
    """With no other debt declared, total DSR is just the pathway's own
    instalment over income - 3000 / 10000 = 30.00%."""
    dsr_percent = formulas.calculate_total_dsr_percent(
        monthly_instalment=Decimal("3000.00"),
        existing_monthly_commitments=Decimal("0"),
        monthly_income=Decimal("10000.00"),
    )
    assert dsr_percent == Decimal("30.00")


def test_nonzero_existing_commitments_adds_to_dsr():
    """Existing debt is added to the new pathway's instalment before
    dividing by income - (3000 + 2000) / 10000 = 50.00%, not 30.00%."""
    dsr_percent = formulas.calculate_total_dsr_percent(
        monthly_instalment=Decimal("3000.00"),
        existing_monthly_commitments=Decimal("2000.00"),
        monthly_income=Decimal("10000.00"),
    )
    assert dsr_percent == Decimal("50.00")


def test_dsr_boundary_value_exactly_at_full_income():
    """Existing commitments plus the new instalment exactly consume 100%
    of declared income (500 + 500 = 1000, over 1000 income) - the sharpest
    possible boundary for an affordability check, hand-verifiable exactly."""
    dsr_percent = formulas.calculate_total_dsr_percent(
        monthly_instalment=Decimal("500.00"),
        existing_monthly_commitments=Decimal("500.00"),
        monthly_income=Decimal("1000.00"),
    )
    assert dsr_percent == Decimal("100.00")


def test_ccris_reportable_labels_are_structural_not_computed():
    assert formulas.CCRIS_REPORTABLE_PATHWAYS == {
        "hire_purchase": True,
        "gfv_leasing": True,
        "subscription": False,
    }
