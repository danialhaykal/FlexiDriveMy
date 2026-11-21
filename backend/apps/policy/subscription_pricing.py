"""The one Subscription fee estimator (audit batch 5).

A new car - for any allowed tenure and mileage band - gets a sensible
Subscription price with no plan keyed. Resolution order for (vehicle,
tenure_months, mileage_band):

  1. Tenure gate. Subscription is offered only for tenures that are inside
     SubscriptionPolicy's min..max AND have a residual baseline (12-month
     steps, so 12, 24 and 36 today). Anything else raises
     SubscriptionConfigError with a customer-safe message built from the real
     tables.
  2. Provider quote. An active SubscriptionPlan for the vehicle is used
     exactly (a quoted fee does not move with tenure or band).
  3. Estimate, from the provider's side of the table:

       depreciation_monthly = price x (1 - residual) / tenure
       funding_monthly      = price x (1 + residual) / 2 x funding% / 100 / 12
                              (the average capital employed over the term)
       bundled_monthly      = (road tax + insurance + maintenance) / 12
       fee = (depreciation + funding + bundled) x (1 + margin% / 100)

     residual comes from apps.policy.residuals (so a higher mileage band,
     with its lower residual, is dearer); the three running costs from
     apps.policy.operating_costs. Intermediates stay unrounded Decimals and
     the fee is rounded ONCE, at the end. A vehicle that can't be costed, or
     whose residual can't be resolved, raises - never a guess.

Every SubscriptionPolicy value is a planning assumption, not provider data.
"""

from dataclasses import dataclass
from decimal import Decimal

from apps.comparisons.formulas import round_currency

from . import mileage
from .models import ResidualBaseline, SubscriptionPlan, SubscriptionPolicy
from .operating_costs import OperatingCostConfigError, estimate_operating_costs
from .residuals import ResidualConfigError, resolve_residual_ratio

SOURCE_QUOTE = "quote"
SOURCE_ESTIMATE = "estimate"



class SubscriptionConfigError(Exception):
    """Subscription can't be priced for this request (tenure not offered, no
    policy, vehicle can't be costed). str(exc) is the customer-safe reason."""


@dataclass(frozen=True)
class SubscriptionQuote:
    fee_monthly: Decimal
    source: str  # "quote" | "estimate"
    basis: str
    components: dict | None  # None for a provider quote


def get_active_policy():
    policy = SubscriptionPolicy.objects.filter(is_active=True).first()
    if policy is None:
        raise SubscriptionConfigError("Subscription pricing isn't configured.")
    return policy


def offered_tenures(policy):
    """Tenures that are inside the policy's range AND have a residual baseline."""
    baseline = set(ResidualBaseline.objects.filter(is_active=True).values_list("tenure_months", flat=True))
    return sorted(t for t in baseline if policy.min_tenure_months <= t <= policy.max_tenure_months)


def tenure_message(tenures):
    if not tenures:
        return "Subscription plans aren't offered for any tenure right now."
    if len(tenures) == 1:
        return f"Subscription plans run for {tenures[0]} months."
    return f"Subscription plans run for {', '.join(str(t) for t in tenures[:-1])} or {tenures[-1]} months."


def included_km_per_year(policy, mileage_band):
    """The km a year a Subscription in this band includes - the band's limit, from the
    one definition (apps.policy.mileage, Run 3 fix batch 6; policy data, not a constant)."""
    return mileage.included_km(mileage_band, policy)


def _pct(value: Decimal) -> str:
    return f"{value.normalize():f}"


def resolve_subscription_fee(vehicle, tenure_months, mileage_band) -> SubscriptionQuote:
    policy = get_active_policy()
    tenures = offered_tenures(policy)
    if tenure_months not in tenures:
        raise SubscriptionConfigError(tenure_message(tenures))

    plan = SubscriptionPlan.objects.filter(vehicle=vehicle, is_active=True).first()
    if plan is not None:
        return SubscriptionQuote(
            fee_monthly=plan.fee_monthly, source=SOURCE_QUOTE, basis="Provider quote - fixed fee", components=None
        )

    try:
        residual = resolve_residual_ratio(vehicle, tenure_months, mileage_band).ratio
    except ResidualConfigError as exc:
        raise SubscriptionConfigError(str(exc)) from exc
    try:
        # NCD 0 on purpose: the provider insures its own fleet, so the
        # buyer's No-Claim Discount doesn't price the fee. Only the owner's
        # running costs (and the "net cost after bundled benefits" offset)
        # use the buyer's NCD.
        costs = estimate_operating_costs(vehicle, ncd_percent=Decimal("0"))
    except OperatingCostConfigError as exc:
        raise SubscriptionConfigError(str(exc)) from exc

    price = vehicle.msrp
    depreciation = price * (Decimal(1) - residual) / Decimal(tenure_months)
    funding = price * (Decimal(1) + residual) / Decimal(2) * policy.funding_rate_percent / Decimal(100) / Decimal(12)
    bundled = (costs.road_tax_annual + costs.insurance_annual + costs.maintenance_annual) / Decimal(12)
    fee = round_currency((depreciation + funding + bundled) * (Decimal(1) + policy.margin_percent / Decimal(100)))

    components = {
        "depreciation_monthly": round_currency(depreciation),
        "funding_monthly": round_currency(funding),
        "bundled_monthly": round_currency(bundled),
        "margin_percent": policy.margin_percent,
        "residual_ratio": residual,
    }
    basis = (
        f"Estimate: depreciation RM {components['depreciation_monthly']:,.2f} + funding RM "
        f"{components['funding_monthly']:,.2f} + road tax, insurance and maintenance RM "
        f"{components['bundled_monthly']:,.2f}, plus {_pct(policy.margin_percent)}% margin"
    )
    return SubscriptionQuote(fee_monthly=fee, source=SOURCE_ESTIMATE, basis=basis, components=components)
