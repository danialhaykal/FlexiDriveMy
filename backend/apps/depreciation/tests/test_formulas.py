from decimal import Decimal

from apps.depreciation import formulas


# --- Straight-line fallback depreciation ------------------------------------


def test_straight_line_resale_value_at_month_zero_is_full_msrp():
    assert formulas.straight_line_resale_value(Decimal("100000.00"), 0) == Decimal("100000.00")


def test_straight_line_resale_value_declines_one_percent_per_month():
    # 100000 * (1 - 0.01*10) = 90000.00
    assert formulas.straight_line_resale_value(Decimal("100000.00"), 10) == Decimal("90000.00")


def test_straight_line_resale_value_floors_at_40_percent():
    # Even well past month 60, never depreciates below the 40% floor.
    assert formulas.straight_line_resale_value(Decimal("100000.00"), 90) == Decimal("40000.00")


# --- HP outstanding balance --------------------------------------------------


def test_hp_outstanding_balance_at_month_zero_is_full_principal():
    balance = formulas.hp_outstanding_balance(Decimal("200000.00"), Decimal("20000.00"), 36, 0)
    assert balance == Decimal("180000.00")


def test_hp_outstanding_balance_declines_linearly():
    # principal=180000, tenure=36: at month 18 (halfway), half the principal remains.
    balance = formulas.hp_outstanding_balance(Decimal("200000.00"), Decimal("20000.00"), 36, 18)
    assert balance == Decimal("90000.00")


def test_hp_outstanding_balance_is_zero_once_loan_is_repaid():
    balance = formulas.hp_outstanding_balance(Decimal("200000.00"), Decimal("20000.00"), 36, 36)
    assert balance == Decimal("0.00")
    balance_beyond = formulas.hp_outstanding_balance(Decimal("200000.00"), Decimal("20000.00"), 36, 50)
    assert balance_beyond == Decimal("0.00")


# --- Negative equity crossover (UC006 sub-flow 9.4-9.5) ---------------------


def test_crossover_pure_function_hand_constructed_case():
    resale_values = [Decimal("100000"), Decimal("95000"), Decimal("90000"), Decimal("80000"), Decimal("70000")]
    outstanding_balances = [Decimal("90000"), Decimal("85000"), Decimal("92000"), Decimal("75000"), Decimal("60000")]

    month, shortfall = formulas.find_negative_equity_crossover(resale_values, outstanding_balances)

    assert month == 2
    assert shortfall == Decimal("2000")


def test_no_crossover_when_resale_always_exceeds_balance():
    resale_values = [Decimal("100000"), Decimal("95000"), Decimal("90000")]
    outstanding_balances = [Decimal("50000"), Decimal("48000"), Decimal("46000")]

    month, shortfall = formulas.find_negative_equity_crossover(resale_values, outstanding_balances)

    assert month is None
    assert shortfall is None


def test_crossover_integrated_with_real_hp_and_straight_line_formulas():
    """Manually reconciled (independent of the code under test): price=100000,
    downpayment=5000, tenure=108 months.

    principal = 95000. balance(m) = 95000*(1 - m/108).
    resale(m) = 100000*(1 - 0.01*m) for m <= 60 (never reaches the 40% floor
    in this window).

    month 41: balance = 95000*(67/108) = 58935.185... -> 58935.19
              resale  = 100000*0.59 = 59000.00  (resale > balance: safe)
    month 42: balance = 95000*(66/108) = 58055.555... -> 58055.56
              resale  = 100000*0.58 = 58000.00  (resale < balance: crossover)
    shortfall at month 42 = 58055.56 - 58000.00 = 55.56
    """
    price = Decimal("100000.00")
    downpayment = Decimal("5000.00")
    tenure_months = 108

    resale_values = [formulas.straight_line_resale_value(price, m) for m in range(61)]
    outstanding_balances = [
        formulas.hp_outstanding_balance(price, downpayment, tenure_months, m) for m in range(61)
    ]

    assert outstanding_balances[41] == Decimal("58935.19")
    assert resale_values[41] == Decimal("59000.00")

    assert outstanding_balances[42] == Decimal("58055.56")
    assert resale_values[42] == Decimal("58000.00")

    month, shortfall = formulas.find_negative_equity_crossover(resale_values, outstanding_balances)

    assert month == 42
    assert shortfall == Decimal("55.56")


# --- TCO ---------------------------------------------------------------


def test_calculate_tco_matches_project_spec_formula_shape():
    # downpayment=10000, hp_monthly=5000, tenure=60 (== horizon, no capping),
    # tax=1200/yr, ins=2400/yr, maint=1800/yr, residual@60=40000.
    tco = formulas.calculate_tco(
        downpayment=Decimal("10000.00"),
        exact_hp_monthly=Decimal("5000.00"),
        tenure_months=60,
        road_tax_annual=Decimal("1200.00"),
        insurance_annual=Decimal("2400.00"),
        maintenance_annual=Decimal("1800.00"),
        residual_value_month_60=Decimal("40000.00"),
    )

    # gross = 10000 + 5000*60 + (1200/12)*60 + (2400/12)*60 + (1800/12)*60 + 0
    #       = 10000 + 300000 + 6000 + 12000 + 9000 = 337000.00
    assert tco["gross"] == Decimal("337000.00")
    # net = 337000 - 40000 = 297000.00
    assert tco["net"] == Decimal("297000.00")


def test_calculate_tco_caps_monthly_payments_at_tenure_not_horizon():
    # tenure=36 (< 60-month horizon): the loan is repaid at month 36, so
    # M_payment only accrues for 36 months, while operating costs still
    # accrue for the full 60-month horizon (see formulas.py docstring).
    tco = formulas.calculate_tco(
        downpayment=Decimal("0.00"),
        exact_hp_monthly=Decimal("1000.00"),
        tenure_months=36,
        road_tax_annual=Decimal("0.00"),
        insurance_annual=Decimal("0.00"),
        maintenance_annual=Decimal("0.00"),
        residual_value_month_60=Decimal("0.00"),
    )

    assert tco["gross"] == Decimal("36000.00")  # 1000 * 36, not 1000 * 60


def test_calculate_tco_credits_net_equity_not_raw_resale_value_past_60_months():
    """QA audit H10: for tenure_months <= 60 the loan is fully repaid by
    month 60 (hp_outstanding_balance() already returns 0.00), so crediting
    the raw resale value is correct and this is a pure generalization -
    confirmed by the two tests above, both still byte-identical, since
    they don't pass hp_outstanding_balance_month_60 at all (defaults to
    0.00).

    For tenure_months=108, the loan is NOT repaid by month 60 - there's a
    real outstanding balance still owed, so crediting the full resale
    value overstates the owner's actual equity. Same gross inputs as
    test_calculate_tco_matches_project_spec_formula_shape above (just a
    different outstanding balance at month 60), to isolate exactly what
    H10 changed.
    """
    gross_kwargs = dict(
        downpayment=Decimal("10000.00"),
        exact_hp_monthly=Decimal("5000.00"),
        tenure_months=108,
        road_tax_annual=Decimal("1200.00"),
        insurance_annual=Decimal("2400.00"),
        maintenance_annual=Decimal("1800.00"),
        residual_value_month_60=Decimal("40000.00"),
    )
    # gross = 10000 + 5000*60 (payment_months capped at the 60-month
    # horizon, tenure_months=108 > 60) + (1200/12)*60 + (2400/12)*60 +
    # (1800/12)*60 = 10000 + 300000 + 6000 + 12000 + 9000 = 337000.00 -
    # identical gross inputs/result to the tenure=60 reference case above.
    without_balance = formulas.calculate_tco(**gross_kwargs)
    assert without_balance["gross"] == Decimal("337000.00")

    # A real outstanding balance of 15000.00 still owed at month 60 means
    # only 40000 - 15000 = 25000.00 of net equity to credit, not the full
    # 40000.00 as if the car were owned free and clear.
    with_balance = formulas.calculate_tco(**gross_kwargs, hp_outstanding_balance_month_60=Decimal("15000.00"))
    assert with_balance["gross"] == Decimal("337000.00")  # gross is unaffected
    assert with_balance["net"] == Decimal("312000.00")  # 337000 - (40000 - 15000)

    # The old (buggy) behavior - crediting the full resale value - is
    # exactly what omitting the new parameter still reproduces (the
    # default is 0.00, i.e. "no outstanding balance"). Less net equity is
    # credited once a real outstanding balance is accounted for, so net
    # TCO is HIGHER (a worse deal, honestly) by exactly that balance.
    assert with_balance["net"] - without_balance["net"] == Decimal("15000.00")


# --- One instalment basis for TCO, cash flow and total outlay ---------------
#
# Hand-derived reference: P=110000, D=10000, r=3%, t=36.
#   principal = 100000
#   exact HP_monthly = 100000/36 + 100000*0.03/12 = 2777.7777... + 250
#                    = 3027.7777...            -> displayed 3027.78
#   true-up total of the 36 payments = 3027.7777... * 36 = 109000.00 exactly
#     (35 x 3027.78 = 105972.30, final payment 109000.00 - 105972.30 = 3027.70)
#   the old rounded basis was 3027.78 * 36 = 109000.08 - the few-sen drift
#   between the TCO screen and the comparison's total contract outlay.

EXACT_3027_78 = (Decimal("100000") / 36) + (Decimal("100000") * Decimal("0.03") / 12)


def test_tco_gross_reconciles_with_total_contract_outlay_to_the_sen():
    from apps.comparisons.formulas import true_up_total_outlay

    tco = formulas.calculate_tco(
        downpayment=Decimal("10000.00"),
        exact_hp_monthly=EXACT_3027_78,
        tenure_months=36,
        road_tax_annual=Decimal("1200.00"),
        insurance_annual=Decimal("2400.00"),
        maintenance_annual=Decimal("1800.00"),
        residual_value_month_60=Decimal("0.00"),
    )
    outlay = true_up_total_outlay(downpayment=Decimal("10000.00"), exact_monthly=EXACT_3027_78, tenure_months=36)

    # gross = 10000 + 109000.00 + (100 + 200 + 150) * 60 = 10000 + 109000 + 27000
    assert tco["gross"] == Decimal("146000.00")  # was 146000.08 on the rounded basis
    assert outlay == Decimal("119000.00")
    assert tco["gross"] - Decimal("27000.00") == outlay


def test_cumulative_cash_flow_pays_rounded_instalments_then_the_true_up_final_payment():
    flow = formulas.build_cumulative_cash_flow(
        downpayment=Decimal("10000.00"),
        exact_hp_monthly=EXACT_3027_78,
        tenure_months=36,
        road_tax_annual=Decimal("0.00"),
        insurance_annual=Decimal("0.00"),
        maintenance_annual=Decimal("0.00"),
    )

    assert flow[1]["cumulative_cash_outflow"] == Decimal("13027.78")  # 10000 + 3027.78
    assert flow[35]["cumulative_cash_outflow"] == Decimal("115972.30")  # 10000 + 3027.78 * 35
    assert flow[36]["cumulative_cash_outflow"] == Decimal("119000.00")  # + final payment 3027.70
    assert flow[60]["cumulative_cash_outflow"] == Decimal("119000.00")  # nothing more after payoff


def test_tco_for_tenure_over_60_counts_the_60_rounded_instalments_actually_paid():
    # t=72: exact = 100000/72 + 250 = 1638.8888... -> 1638.89. The true-up
    # payment is month 72, after the horizon, so the 60 payments made by
    # month 60 are 60 x 1638.89 = 98333.40 (not exact*60 = 98333.33).
    exact = (Decimal("100000") / 72) + (Decimal("100000") * Decimal("0.03") / 12)

    tco = formulas.calculate_tco(
        downpayment=Decimal("10000.00"),
        exact_hp_monthly=exact,
        tenure_months=72,
        road_tax_annual=Decimal("0.00"),
        insurance_annual=Decimal("0.00"),
        maintenance_annual=Decimal("0.00"),
        residual_value_month_60=Decimal("0.00"),
    )

    assert tco["gross"] == Decimal("108333.40")  # 10000 + 98333.40
