"""F005 - pure financial calculation functions (the project spec formulas).

Deliberately framework-free: no Django/DRF imports here. Every function
takes/returns decimal.Decimal so callers control rounding precision, and
every monetary result is quantized to 2 decimal places (NUMERIC(12,2)
currency convention) using ROUND_HALF_UP, the standard financial rounding
convention - never Python's default banker's rounding.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


def round_currency(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# Solver settings for effective_annual_rate: 60 significant digits keeps
# (1 + i) ** -t exact enough that bisection, not rounding, limits accuracy.
_SOLVER_PRECISION = 60
_SOLVER_MAX_ITERATIONS = 300
_SOLVER_TOLERANCE = Decimal("1e-18")  # on the MONTHLY rate - far tighter than 1e-10
_SOLVER_UPPER_BOUND = Decimal("1000")  # 100,000% a month: past any real contract


def effective_monthly_rate(principal, monthly_payment, tenure_months, balloon=Decimal("0")):
    """The unrounded MONTHLY effective rate i that satisfies

        principal = monthly_payment x (1 - (1+i)^-t) / i + balloon x (1+i)^-t

    solved by Decimal bisection in a 60-digit context (no float/numpy).
    Shared by effective_annual_rate (which quotes it as a yearly percent) and
    settlement_balance (which rolls the loan forward at it). Pass the EXACT,
    unrounded monthly payment. Returns None - never raises - when no positive
    rate exists (total repaid does not exceed the principal) or the inputs
    aren't a loan.
    """
    try:
        with localcontext() as ctx:
            ctx.prec = _SOLVER_PRECISION
            principal = Decimal(principal)
            payment = Decimal(monthly_payment)
            balloon = Decimal(balloon)
            term = int(tenure_months)
            if term <= 0 or principal <= 0 or payment < 0 or balloon < 0:
                return None
            if payment * term + balloon <= principal:
                return None  # a zero or negative rate

            def present_value(monthly_rate):
                discount = (1 + monthly_rate) ** -term
                return payment * (1 - discount) / monthly_rate + balloon * discount

            low = Decimal("1e-15")  # PV(low) ~ total repaid > principal
            high = Decimal(1)
            while present_value(high) > principal:
                high *= 2
                if high > _SOLVER_UPPER_BOUND:
                    return None
            for _ in range(_SOLVER_MAX_ITERATIONS):
                middle = (low + high) / 2
                if present_value(middle) > principal:
                    low = middle
                else:
                    high = middle
                if high - low < _SOLVER_TOLERANCE:
                    break
            return (low + high) / 2
    except (InvalidOperation, ArithmeticError, ValueError, TypeError):
        return None


def effective_annual_rate(principal, monthly_payment, tenure_months, balloon=Decimal("0")):
    """The effective (reducing-balance) rate a bank would quote for a loan
    that is actually repaid as `monthly_payment` x `tenure_months` plus a
    `balloon` at the end: the NOMINAL ANNUAL rate compounded monthly, as a
    percent, i.e. the i x 12 x 100 that satisfies

        principal = monthly_payment x (1 - (1+i)^-t) / i + balloon x (1+i)^-t

    with i the monthly rate and t the tenure. The dealer's flat rate in
    the project spec's HP/GFV formulas is unchanged - this only re-expresses the
    same instalments in the way the Hire-Purchase (Amendment) Act 2026
    moves lenders to disclose them.

    Pass the EXACT, unrounded monthly payment (the same value
    true_up_total_outlay uses), not the rounded one. Solved by Decimal
    bisection (no float/numpy). Rounded to 4 dp; the UI shows 2. Returns
    None - never raises - when no positive rate exists (total repaid does
    not exceed the principal) or the inputs aren't a loan.
    """
    monthly_rate = effective_monthly_rate(principal, monthly_payment, tenure_months, balloon)
    if monthly_rate is None:
        return None
    with localcontext() as ctx:
        ctx.prec = _SOLVER_PRECISION
        annual_percent = monthly_rate * 12 * 100
        return annual_percent.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def settlement_balance(principal, exact_monthly, tenure_months, month, balloon=Decimal("0")):
    """The estimated amount needed to SETTLE the loan after `month` payments,
    by the reducing-balance method the Hire-Purchase (Amendment) Act 2026
    requires for new loans (no Rule of 78, no early-settlement penalty): the
    principal rolled forward at the effective monthly rate i, less the
    payments made, also rolled forward:

        B = principal x (1+i)^month - exact_monthly x ((1+i)^month - 1) / i

    i comes from effective_monthly_rate, fed the EXACT (unrounded) monthly
    payment, so for GFV the balance glides down to the balloon, which is due
    AT month t. `month >= tenure_months` is fully repaid (for GFV, after the
    balloon is paid): 0.00. Computed in the same 60-digit context and rounded
    once with round_currency.

    No positive rate (e.g. a 0% deal) falls back to straight line:
    (principal - balloon) x (1 - month/t) + balloon, rounded once.
    """
    return settlement_balances(principal, exact_monthly, tenure_months, [month], balloon)[0]


def settlement_balances(principal, exact_monthly, tenure_months, months, balloon=Decimal("0")):
    """settlement_balance for several months at once - the effective rate is
    solved ONCE, not per month (a 61-month chart would otherwise run the
    bisection 61 times). Same figures, month for month, as settlement_balance.
    """
    term = int(tenure_months)
    with localcontext() as ctx:
        ctx.prec = _SOLVER_PRECISION
        principal = Decimal(principal)
        payment = Decimal(exact_monthly)
        balloon = Decimal(balloon)
        monthly_rate = None
        if any(0 < int(month) < term for month in months):
            monthly_rate = effective_monthly_rate(principal, payment, term, balloon)
        balances = []
        for month in months:
            month = int(month)
            if month >= term:
                balances.append(Decimal("0.00"))
            elif month <= 0:
                balances.append(round_currency(principal))
            elif monthly_rate is None:
                straight_line = (principal - balloon) * (1 - Decimal(month) / Decimal(term)) + balloon
                balances.append(round_currency(straight_line))
            else:
                growth = (1 + monthly_rate) ** month
                balances.append(round_currency(principal * growth - payment * (growth - 1) / monthly_rate))
        return balances


def exact_hp_monthly(price: Decimal, downpayment: Decimal, tenure_months: int, annual_rate: Decimal) -> Decimal:
    """The unrounded HP_monthly value - exposed (not just the rounded
    calculate_hp_monthly below) so apps.comparisons.services can true up
    the total against the precise figure rather than accumulating per-
    month rounding error (QA audit L7)."""
    principal = price - downpayment
    return (principal / tenure_months) + (principal * annual_rate / Decimal(12))


def calculate_hp_monthly(
    price: Decimal, downpayment: Decimal, tenure_months: int, annual_rate: Decimal
) -> Decimal:
    """HP_monthly = (P - D) / t + [(P - D) * r] / 12.

    Hire Purchase Act 1967 flat-rate convention: the financed principal is
    spread evenly over the t monthly payments, plus a flat monthly interest
    slice (r/12 of the financed principal) for the life of the contract.
    """
    return round_currency(exact_hp_monthly(price, downpayment, tenure_months, annual_rate))


def calculate_gfv_balloon(price: Decimal, residual_ratio: Decimal) -> Decimal:
    """GFV_balloon = P * G_ratio."""
    return round_currency(price * residual_ratio)


def exact_gfv_monthly(
    price: Decimal,
    downpayment: Decimal,
    tenure_months: int,
    annual_rate: Decimal,
    gfv_balloon: Decimal,
) -> Decimal:
    """The unrounded GFV_monthly value - see exact_hp_monthly above."""
    principal = price - downpayment
    remaining_to_amortize = principal - gfv_balloon
    return (remaining_to_amortize / tenure_months) + (principal * annual_rate / Decimal(12))


def calculate_gfv_monthly(
    price: Decimal,
    downpayment: Decimal,
    tenure_months: int,
    annual_rate: Decimal,
    gfv_balloon: Decimal,
) -> Decimal:
    """GFV_monthly = (P - D - GFV_balloon) / t + [(P - D) * r] / 12.

    Same shape as HP_monthly, but the balloon is carved out of the
    principal before it's spread across the monthly payments.
    """
    return round_currency(exact_gfv_monthly(price, downpayment, tenure_months, annual_rate, gfv_balloon))


def true_up_total_outlay(*, downpayment: Decimal, exact_monthly: Decimal, tenure_months: int) -> Decimal:
    """QA audit L7: downpayment + rounded_monthly * tenure_months drifts
    from the precise (unrounded) total, since it compounds the same
    sub-cent rounding error over every one of the t payments (e.g.
    the project spec's own GFV reference case: monthly rounds to 5344.44 from an
    exact 5344.4444..., and 36 x that rounding-down is a real RM 0.16
    short of the precise total). The standard loan-amortization fix is a
    true-up: (tenure_months - 1) regular rounded payments, plus one final
    payment that absorbs the full rounding remainder - downpayment +
    rounded_monthly * (tenure_months - 1) + final_payment, with
    final_payment solved for algebraically. That construction is always
    exactly equal to rounding the precise total once at the end (see
    test_true_up_total_outlay.py for the algebraic proof, verified both
    symbolically and against the project spec's own GFV reference case), which
    is what this computes directly - never an accumulation of per-
    payment rounding error.
    """
    return round_currency(downpayment + exact_monthly * tenure_months)


def true_up_payments_through_month(*, exact_monthly: Decimal, tenure_months: int, month: int) -> Decimal:
    """Total instalments actually paid by the end of `month`, under the SAME
    true-up schedule true_up_total_outlay describes: payments 1..t-1 are the
    rounded instalment, and payment t absorbs the whole rounding remainder.

    So before the final payment it's rounded_monthly * month (exactly what
    has left the borrower's account), and from month t on it's the precise
    total rounded once - round(exact_monthly * t), the same figure
    true_up_total_outlay adds to the downpayment. Every screen that sums
    instalments (comparison outlay, TCO, cumulative cash flow) must use this
    one basis, or the same payments show up a few sen apart on different
    screens.
    """
    if month >= tenure_months:
        return round_currency(exact_monthly * tenure_months)
    return round_currency(exact_monthly) * month


def calculate_subscription_net_cost(
    fee_monthly: Decimal,
    insurance_annual: Decimal,
    tax_annual: Decimal,
    maintenance_annual: Decimal,
) -> Decimal:
    """NetCost = Fee_monthly - [(Ins_annual + Tax_annual + Maint_annual) / 12]
    (the project spec's "value-added offset" formula).

    QA audit H8: this is an economic *comparison* figure only - it nets
    out costs an HP/GFV owner pays separately (apps.policy.operating_costs), to
    make the three pathways comparable on a like-for-like basis. It is
    NOT what the subscriber is actually billed: insurance/tax/maintenance
    are bundled into the one invoice, not charged separately, so the real
    monthly cash outflow is fee_monthly in full. Never use this value as
    a DSR input or as the headline "monthly instalment" - see
    apps.comparisons.services.build_comparison's subscription block.
    """
    offset = (insurance_annual + tax_annual + maintenance_annual) / Decimal(12)
    return round_currency(fee_monthly - offset)
