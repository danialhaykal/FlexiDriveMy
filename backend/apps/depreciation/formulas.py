"""F006 - pure financial calculation functions (UC006), framework-free
like apps/comparisons/formulas.py. Every monetary result is quantized to
2 decimal places with ROUND_HALF_UP.
"""

from decimal import ROUND_HALF_UP, Decimal

from apps.comparisons.formulas import (
    exact_gfv_monthly,
    exact_hp_monthly,
    settlement_balance,
    settlement_balances,
    true_up_payments_through_month,
)

TWO_PLACES = Decimal("0.01")
HORIZON_MONTHS = 60

# the project spec specifies only that the ML-service-failure fallback must be "a
# deterministic straight-line depreciation formula", not its exact
# parameters. Placeholder assumption, flagged here (not derived from any
# real dataset): new cars retain ~40% of MSRP after 5 years/60 months in
# Malaysia, so monthly straight-line depreciation = (1 - 0.40) / 60 = 1%.
STRAIGHT_LINE_MONTHLY_RATE = Decimal("0.01")
STRAIGHT_LINE_FLOOR_RATIO = Decimal("0.40")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def straight_line_resale_value(msrp: Decimal, month: int) -> Decimal:
    """Deterministic fallback depreciation curve (UC006 exception flow)."""
    ratio = max(STRAIGHT_LINE_FLOOR_RATIO, Decimal(1) - STRAIGHT_LINE_MONTHLY_RATE * month)
    return round_currency(msrp * ratio)


def hp_outstanding_balance(
    price: Decimal, downpayment: Decimal, tenure_months: int, month: int, annual_rate: Decimal = Decimal("0")
) -> Decimal:
    """Estimated SETTLEMENT balance after `month` payments, reducing-balance
    method (apps.comparisons.formulas.settlement_balance): what the buyer
    would need to pay to clear the HP loan at that point, as the Hire-
    Purchase (Amendment) Act 2026 requires for new loans - no Rule of 78, no
    early-settlement penalty. Zero once the loan is fully repaid (month >=
    tenure_months).

    `annual_rate` is the dealer's FLAT rate as a decimal (0.028 for 2.8%) -
    the same one the instalment is built from; it fixes the exact monthly
    payment the effective rate is solved from. Left at 0 (a 0% deal), there
    is no positive effective rate and the balance is the straight-line
    principal - the fallback settlement_balance itself uses.
    """
    exact_monthly = exact_hp_monthly(price, downpayment, tenure_months, annual_rate)
    return settlement_balance(price - downpayment, exact_monthly, tenure_months, month)


def hp_settlement_schedule(
    price: Decimal, downpayment: Decimal, tenure_months: int, annual_rate: Decimal, months
) -> list:
    """hp_outstanding_balance for every month in `months`, solving the
    effective rate once (a 61-month chart would otherwise solve it 61 times).
    Month for month identical to hp_outstanding_balance."""
    exact_monthly = exact_hp_monthly(price, downpayment, tenure_months, annual_rate)
    return settlement_balances(price - downpayment, exact_monthly, tenure_months, list(months))


def find_negative_equity_crossover(resale_values, outstanding_balances):
    """UC006 sub-flow 9.4-9.5: the first month index where the predicted
    resale value falls below the outstanding loan balance.

    Both args are same-length sequences indexed by month (0..N). Returns
    (crossover_month, shortfall_amount) or (None, None) if no crossover
    occurs anywhere in the given horizon.
    """
    for month, (resale, balance) in enumerate(zip(resale_values, outstanding_balances)):
        if resale < balance:
            return month, round_currency(balance - resale)
    return None, None


def calculate_tco(
    *,
    downpayment: Decimal,
    exact_hp_monthly: Decimal,
    tenure_months: int,
    road_tax_annual: Decimal,
    insurance_annual: Decimal,
    maintenance_annual: Decimal,
    residual_value_month_60: Decimal,
    hp_outstanding_balance_month_60: Decimal = Decimal("0.00"),
    horizon_months: int = HORIZON_MONTHS,
):
    """the project spec's 60-month TCO, for the HP ownership pathway:

    TCO_gross = C_upfront + (M_payment x 60) + (C_tax x 60) + (C_ins x 60)
                + (C_maint x 60) + C_residual
    TCO_net = TCO_gross - V_residual

    C_residual (a contractual balloon due at contract end) is 0 for HP -
    there's no balloon.

    QA audit H10: V_residual must credit NET equity at month 60, not the
    raw predicted resale value - residual_value_month_60 - hp_outstanding_balance_month_60.
    For tenure_months <= 60 the loan is fully repaid by month 60
    (hp_outstanding_balance() already returns 0.00 once month >=
    tenure_months), so hp_outstanding_balance_month_60 is 0 and this is a
    pure generalization - every tenure-<=60 case is unaffected, byte-
    identical to the old formula. For tenure_months > 60 (e.g. 108
    months), there's a real loan balance still owed at month 60 (the car
    isn't owned free and clear yet) - crediting the full resale value
    anyway previously made a long tenure look cheaper than a short one
    despite far more interest paid overall, and Arena's "lowest TCO"
    winner ranks directly on this number.

    Deviation, flagged: M_payment is only charged for min(tenure_months,
    horizon_months) months (once the loan is repaid there's nothing left
    to pay), while the ongoing operating costs (tax/insurance/maintenance)
    accrue for the full horizon regardless of loan payoff timing - the project spec's
    formula doesn't disambiguate this for tenure != 60, so this is a
    judgment call, not a proven correction like the HP/GFV formula fix.

    M_payment x n is summed on the comparison's true-up basis
    (true_up_payments_through_month), not rounded_monthly x n: for tenure
    <= 60 that's exactly the comparison's total_contract_outlay minus the
    downpayment, so TCO and outlay never disagree by a few sen; for tenure
    > 60 the final true-up payment falls after the horizon, so it's the 60
    rounded instalments actually paid by then.
    """
    payment_months = min(tenure_months, horizon_months)
    monthly_tax = road_tax_annual / Decimal(12)
    monthly_insurance = insurance_annual / Decimal(12)
    monthly_maintenance = maintenance_annual / Decimal(12)

    gross = (
        downpayment
        + true_up_payments_through_month(
            exact_monthly=exact_hp_monthly, tenure_months=tenure_months, month=payment_months
        )
        + monthly_tax * horizon_months
        + monthly_insurance * horizon_months
        + monthly_maintenance * horizon_months
    )
    net_equity_month_60 = residual_value_month_60 - hp_outstanding_balance_month_60
    net = gross - net_equity_month_60

    return {
        "gross": round_currency(gross),
        "net": round_currency(net),
    }


def build_cumulative_cash_flow(
    *,
    downpayment: Decimal,
    exact_hp_monthly: Decimal,
    tenure_months: int,
    road_tax_annual: Decimal,
    insurance_annual: Decimal,
    maintenance_annual: Decimal,
    horizon_months: int = HORIZON_MONTHS,
):
    """UC006 step 6's cumulative cash flow chart - the running total of
    cash actually paid out under the HP pathway, month by month. Built
    from the exact same per-month cost components as calculate_tco()'s
    own `gross` figure above (same payment_months cap, same monthly_tax/
    insurance/maintenance division) - by construction, entry[horizon_months]
    here must equal calculate_tco(...)["gross"] for the same inputs. Test
    that invariant explicitly - if it ever drifts, this and calculate_tco
    have silently diverged.
    """
    payment_months = min(tenure_months, horizon_months)
    monthly_tax = road_tax_annual / Decimal(12)
    monthly_insurance = insurance_annual / Decimal(12)
    monthly_maintenance = maintenance_annual / Decimal(12)
    entries = []
    for month in range(horizon_months + 1):
        hp_paid_months = min(month, payment_months)
        cumulative = (
            downpayment
            + true_up_payments_through_month(
                exact_monthly=exact_hp_monthly, tenure_months=tenure_months, month=hp_paid_months
            )
            + (monthly_tax + monthly_insurance + monthly_maintenance) * month
        )
        entries.append({"month": month, "cumulative_cash_outflow": round_currency(cumulative)})
    return entries


# --- Sprint 12: Total-Loss Exposure Sandbox ---------------------------------


def gfv_outstanding_balance(*, price, downpayment, tenure_months, month, gfv_balloon, annual_rate=Decimal("0")):
    """Estimated amount needed to SETTLE a GFV Leasing agreement early (e.g.
    on a total loss) at `month`, reducing-balance method
    (apps.comparisons.formulas.settlement_balance): the financed amount
    rolled forward at the lease's effective monthly rate, less the payments
    made - so it glides down to the balloon, which is due AT month
    tenure_months and is still owed in full on an early exit.

    FX-1 (X1): at month == tenure_months the amount to settle is the balloon
    itself. A car written off in the balloon month has not yet been paid
    off, handed back or refinanced, so the balloon is still owed to the
    lender - settlement_balance's 0.00 at month t (right for the chart and
    TCO, where the balloon is accounted for separately) would hand the whole
    insurance payout to the buyer. Only this sandbox helper changes;
    settlement_balance and every other screen that uses it are unchanged.
    Months after the term (refused by the serializer) still read 0.00.

    `annual_rate` is the dealer's FLAT rate as a decimal; left at 0 (a 0%
    deal) the balance is the straight line from the financed amount down to
    the balloon - settlement_balance's own fallback.
    """
    if month == tenure_months:
        return round_currency(gfv_balloon)
    exact_monthly = exact_gfv_monthly(price, downpayment, tenure_months, annual_rate, gfv_balloon)
    return settlement_balance(price - downpayment, exact_monthly, tenure_months, month, gfv_balloon)
