"""F005 - retrieves F010/F011 config for a vehicle/tenure/mileage-band
combination and calls into formulas.py to build the side-by-side
HP/GFV/Subscription comparison (UC005 main flow)."""

import logging
from decimal import Decimal

from apps.common.constants import minimum_downpayment_for, minimum_downpayment_message
from apps.depreciation.inference import FORECAST_SOURCE_ML, forecast_outlook
from apps.policy import contract_rules, residuals, subscription_pricing
from apps.policy.models import InterestRate
from apps.policy.operating_costs import OperatingCostConfigError, estimate_operating_costs

from . import formulas

logger = logging.getLogger(__name__)


class ComparisonConfigError(Exception):
    """Raised when a pathway can't be calculated because required admin-
    managed pricing/rate configuration is missing or inactive (UC005
    alternate flow: 'System encounters missing or null interest rate
    configurations ... flags an internal calculation exception'). The view
    maps this to a 4xx response, never an unhandled 500.

    str(exc) is the text a BUYER sees; `admin_message` is the technical one
    for admins and the log (Vehicle Readiness reads it). They are the same
    unless the raiser gives both.
    """

    def __init__(self, message, admin_message=None):
        super().__init__(message)
        self.admin_message = admin_message or message


# What a buyer is told when a brand has no financing rate yet - plain words,
# no configuration jargon. The technical reason goes to admin_message.
RATE_NOT_SET_MESSAGE = (
    "Hire Purchase and GFV aren't available for this car yet because its financing rate hasn't been set up."
)


GFV_SAME_TOTAL_NOTE = (
    "Same total as Hire Purchase because both use the same flat rate on the same amount. GFV's benefits are the "
    "lower monthly payment and the guaranteed buy-back value."
)


# Run 2 fix batch 2 (E3): what the GFV residual IS, so it isn't read as a
# prediction of the car's market value. A fixed sentence on the GFV block; the
# TCO tab's resale_views_note puts the two numbers side by side.
GFV_RESALE_NOTE = (
    "This residual is the lender's conservative guaranteed buy-back value. The expected market value (shown on "
    "the TCO tab) is usually higher."
)


def gfv_end_of_term_note(balloon_payment, tenure_months):
    """The GFV card's end-of-term choice, from the comparison's own balloon."""
    return (
        f"At month {tenure_months} you choose: pay the balloon of RM {balloon_payment:,.2f} and keep the car, hand "
        "the car back (within the mileage and condition terms), or refinance the balloon."
    )


def get_active_interest_rate(brand):
    rate = InterestRate.objects.filter(brand=brand, is_active=True).first()
    if rate is None:
        admin_message = f"No active interest rate configured for brand '{brand.name}'."
        logger.info("Interest rate unavailable: %s", admin_message)
        raise ComparisonConfigError(RATE_NOT_SET_MESSAGE, admin_message=admin_message)
    return rate


def _mileage_note(brand, included_km):
    """What the selected mileage band's Subscription includes. The fee is
    already priced for that band (through the residual), so excess mileage is
    only DESCRIBED here with the contract rule's per-km rate - never added to
    any total, which would double count."""
    note = f"Includes up to {included_km:,} km a year."
    rate = contract_rules.excess_mileage_rate(brand)
    if rate is not None:
        per_km, source = rate
        owner = "this brand's contract rule" if source == "brand" else "the default contract rule"
        note += f" Kilometres above that are billed per km (RM {per_km:.2f}/km under {owner})."
    return note


def gfv_residual_ratio_user_message(brand, tenure_months, mileage_band, admin_reason):
    """Plain, customer-facing explanation for a GFV residual that can't be
    resolved (apps.policy.residuals.ResidualConfigError - a tenure with no
    baseline row and no brand override). The raw `admin_reason` is logged
    for admins (QA audit L2) while this returns the plain version, listing
    the tenures that ARE offered, queried from the real tables so it stays
    accurate as config changes. Shared (not underscore-private) since
    apps.depreciation.services.build_total_loss_sandbox reuses it for the
    exact same case.
    """
    logger.info("GFV residual ratio unavailable: %s", admin_reason)
    return residuals.unavailable_message(tenure_months, brand, mileage_band)


def _resolve_interest_rate_for_hp_and_gfv(*, brand, price, downpayment):
    """HP and GFV share two dependencies: a minimum 10% downpayment
    (the project spec / FYP1 Ch.2 2.1.1 - "Conventional HP loans mandate a
    minimum 10% downpayment"; Subscription has no downpayment, so it's
    unaffected) and the brand's active interest rate. Either gap disables
    both pathways identically. Returns (interest_rate_row, reason) -
    reason is None iff interest_rate_row is not None.
    """
    minimum_downpayment = minimum_downpayment_for(price)
    if downpayment < minimum_downpayment:
        return None, minimum_downpayment_message(price)
    try:
        return get_active_interest_rate(brand), None
    except ComparisonConfigError as exc:
        return None, str(exc)


def build_comparison(*, vehicle, tenure_months, mileage_band, downpayment, ncd_percent=Decimal("0")):
    """Retrieve F010/F011 config for `vehicle` and return all three
    pathways side by side. Each pathway is computed independently - a
    missing/inactive config for one pathway only removes *that* pathway
    from the response (as `None`, with its reason recorded in the
    sibling `unavailable` map), never the others. This never raises
    ComparisonConfigError itself: UC005's own purpose is to show HP/GFV/
    Subscription "simultaneously side-by-side", and the three pathways
    have genuinely independent config dependencies (confirmed by reading
    formulas.py: HP needs only the brand's interest rate; GFV needs that
    *and* a residual ratio for this exact tenure/mileage-band;
    Subscription needs only its policy, the vehicle's residual and running
    costs, or an optional provider quote - never an interest rate) - a
    missing residual ratio has nothing to do with whether HP or
    Subscription can be computed. Same graceful-degradation philosophy
    Sprint 10's Arena feature already established across vehicles,
    applied here within one vehicle's three pathways.

    Also guards two numeric edge cases, never returning a nonsensical
    figure: a downpayment below the 10% minimum (shared by HP/GFV, same
    as a missing interest rate - single-vehicle callers like
    ComparisonRequestSerializer already reject this with a 400 before
    this function is ever reached, but Arena shares one downpayment
    across 2-3 cars and can't reject the whole request just because it's
    short for one of them, so this function handles it gracefully too),
    and a GFV downpayment that would exceed what GFV actually finances
    (price - balloon), which would otherwise produce a negative monthly
    instalment.

    Callers that still need to know about *every* pathway (F007's
    suitability scoring and DSR simulator score/report only the
    pathways that ARE available, per UC007 step 3's "scores each
    available pathway") read the `unavailable` map themselves - see
    apps/scoring/services.py.

    `ncd_percent` (run 1 fix batch 3) is the buyer's No-Claim Discount, from
    their own profile (apps.profiles.models.ncd_percent_for - never the
    request). It only lowers the insurance in the Subscription's "net cost
    after bundled benefits" offset (an owner's running costs); the
    subscription fee itself is priced with no NCD, and no instalment,
    outlay or rate depends on it.
    """
    brand = vehicle.brand
    price = vehicle.msrp
    unavailable = {}

    interest_rate_row, hp_gfv_reason = _resolve_interest_rate_for_hp_and_gfv(
        brand=brand, price=price, downpayment=downpayment
    )
    if hp_gfv_reason:
        unavailable["hire_purchase"] = hp_gfv_reason
        unavailable["gfv_leasing"] = hp_gfv_reason

    hire_purchase = None
    gfv_leasing = None
    max_downpayment_for_gfv = None

    if interest_rate_row is not None:
        annual_rate = interest_rate_row.rate_percent / Decimal(100)
        exact_hp_monthly = formulas.exact_hp_monthly(price, downpayment, tenure_months, annual_rate)
        hp_monthly = formulas.round_currency(exact_hp_monthly)
        hire_purchase = {
            "monthly_instalment": hp_monthly,
            "upfront_cash": downpayment,
            # QA audit L7: true-up, not rounded_monthly * tenure_months -
            # see formulas.true_up_total_outlay's own docstring.
            "total_contract_outlay": formulas.true_up_total_outlay(
                downpayment=downpayment, exact_monthly=exact_hp_monthly, tenure_months=tenure_months
            ),
            # The dealer's FLAT rate, unchanged (what the instalment above is
            # built from) ...
            "interest_rate_percent": interest_rate_row.rate_percent,
            # ... and the same instalments re-expressed as the effective
            # (reducing-balance) rate a bank would disclose - derived from
            # the EXACT monthly payment, never the rounded one.
            "effective_rate_percent": formulas.effective_annual_rate(
                price - downpayment, exact_hp_monthly, tenure_months
            ),
        }

        try:
            residual = residuals.resolve_residual_ratio(vehicle, tenure_months, mileage_band)
        except residuals.ResidualConfigError as exc:
            unavailable["gfv_leasing"] = gfv_residual_ratio_user_message(
                brand, tenure_months, mileage_band, str(exc)
            )
        else:
            residual_ratio = residual.ratio
            gfv_balloon = formulas.calculate_gfv_balloon(price, residual_ratio)
            financed_amount = price - downpayment - gfv_balloon
            # FX-3: the GFV downpayment limit for this term (price less the
            # balloon), sent as its own field whenever the term is offered -
            # the same figure the "exceeds" sentence below quotes.
            max_downpayment_for_gfv = formulas.round_currency(price - gfv_balloon)
            if financed_amount < 0:
                unavailable["gfv_leasing"] = (
                    "Your downpayment exceeds the amount financed under GFV (maximum "
                    f"RM {max_downpayment_for_gfv:,.2f} for this term)."
                )
            else:
                exact_gfv_monthly = formulas.exact_gfv_monthly(
                    price, downpayment, tenure_months, annual_rate, gfv_balloon
                )
                gfv_monthly = formulas.round_currency(exact_gfv_monthly)
                gfv_leasing = {
                    "monthly_instalment": gfv_monthly,
                    "upfront_cash": downpayment,
                    "balloon_payment": gfv_balloon,
                    # QA audit H9: the balloon due at contract end was
                    # never added in, making GFV look dramatically
                    # cheaper than it is (especially in the PDF, which
                    # has no separate balloon footnote to compensate).
                    # QA audit L7: true-up on the monthly-payment series,
                    # then the (already-exact) balloon added on top.
                    "total_contract_outlay": formulas.round_currency(
                        formulas.true_up_total_outlay(
                            downpayment=downpayment, exact_monthly=exact_gfv_monthly, tenure_months=tenure_months
                        )
                        + gfv_balloon
                    ),
                    "residual_value_ratio": residual_ratio,
                    # Plain-English origin of that ratio (admin override or
                    # the baseline + adjustments estimate).
                    "residual_basis": residual.basis,
                    # Effective (reducing-balance) rate of the GFV lease:
                    # same principal, the exact monthly payment, and the
                    # balloon paid at term end.
                    "effective_rate_percent": formulas.effective_annual_rate(
                        price - downpayment, exact_gfv_monthly, tenure_months, gfv_balloon
                    ),
                    # Run 1 fix batch 4 (B4): what happens at the end, and why
                    # the total matches Hire Purchase (GFV payments + balloon =
                    # HP payments: the same flat rate on the same amount).
                    "end_of_term_note": gfv_end_of_term_note(gfv_balloon, tenure_months),
                    "same_total_note": GFV_SAME_TOTAL_NOTE,
                    # Run 2 fix batch 3: only where the TCO tab really shows a machine-
                    # learning "expected market value" to set this residual against;
                    # an estimated curve (electric car, model switched off...) is
                    # anchored to this very residual, so there is nothing "higher".
                    "resale_note": GFV_RESALE_NOTE if forecast_outlook(vehicle)[0] == FORECAST_SOURCE_ML else None,
                }

    subscription = None
    try:
        fee_quote = subscription_pricing.resolve_subscription_fee(vehicle, tenure_months, mileage_band)
    except subscription_pricing.SubscriptionConfigError as exc:
        # Same shape as the other pathways: unavailable with a customer-safe
        # reason, so scoring/radar/DSR/Arena skip it instead of failing.
        unavailable["subscription"] = str(exc)
    else:
        # QA audit H8: the subscriber is billed the full fee every month
        # (insurance/tax/maintenance are bundled into that one invoice,
        # not charged separately) - calculate_subscription_net_cost's
        # NetCost is a real the project spec-specified figure, but it's an
        # economic comparison number, not the real cash outflow, so it
        # must never be the headline "monthly instalment" or a DSR
        # input (apps.scoring.services reads monthly_instalment directly
        # for both). Kept under its own name for informational context.
        # Audit batch 5: the fee is a provider quote if an admin keyed one,
        # else an estimate derived from the vehicle (no plan needed).
        fee_monthly = fee_quote.fee_monthly
        # Audit batch 2: the bundled insurance/road tax/maintenance are the
        # SAME figures the TCO tab shows for this car, from the single
        # operating-cost engine - the plan's own (now deprecated) cost
        # columns are no longer read, so the two screens can't disagree.
        # A vehicle that can't be costed (incomplete specs, no rate row)
        # keeps its subscription pathway and fee; only the offset is None,
        # with the reason beside it. (Deliberately NOT put in the
        # pathway-keyed `unavailable` map: scoring/radar/DSR UIs render every
        # key there as a pathway, so a non-pathway key would show up as a
        # bogus "Not available" card.)
        net_cost_after_bundled_benefits = None
        net_cost_unavailable_reason = None
        try:
            costs = estimate_operating_costs(vehicle, ncd_percent=ncd_percent)
        except OperatingCostConfigError as exc:
            net_cost_unavailable_reason = str(exc)
        else:
            net_cost_after_bundled_benefits = formulas.calculate_subscription_net_cost(
                fee_monthly, costs.insurance_annual, costs.road_tax_annual, costs.maintenance_annual
            )
        # The refundable security deposit is the cash genuinely needed on day
        # one, so it IS the upfront cash - but it is returned at the end, so it
        # is NOT part of the contract outlay (the fees alone are).
        policy = subscription_pricing.get_active_policy()
        refundable_deposit = formulas.round_currency(policy.deposit_months * fee_monthly)
        included_km = subscription_pricing.included_km_per_year(policy, mileage_band)
        subscription = {
            "monthly_instalment": fee_monthly,
            "upfront_cash": refundable_deposit,
            "total_contract_outlay": formulas.true_up_total_outlay(
                downpayment=Decimal("0.00"), exact_monthly=fee_monthly, tenure_months=tenure_months
            ),
            "refundable_deposit": refundable_deposit,
            "fee_source": fee_quote.source,
            "fee_basis": fee_quote.basis,
            "included_km_per_year": included_km,
            "mileage_note": _mileage_note(brand, included_km),
            "net_cost_after_bundled_benefits": net_cost_after_bundled_benefits,
            "net_cost_unavailable_reason": net_cost_unavailable_reason,
        }

    return {
        "vehicle_id": vehicle.id,
        "tenure_months": tenure_months,
        "mileage_band": mileage_band,
        "downpayment": downpayment,
        # The NCD the running-cost figures above assume (0 = before NCD).
        "ncd_percent": Decimal(str(ncd_percent)),
        "hire_purchase": hire_purchase,
        "gfv_leasing": gfv_leasing,
        "subscription": subscription,
        "unavailable": unavailable,
        # FX-3: null when GFV has no term (or rate) to set a limit for.
        "gfv_max_downpayment": max_downpayment_for_gfv,
    }
