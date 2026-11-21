"""The ONE operating-cost engine: annual road tax, insurance and maintenance
for a vehicle, derived from the vehicle's own fields and the admin-managed
rate tables (RoadTaxCcBand, EvRoadTaxGroup, OperatingCostRate). Every screen
that shows or nets these costs (TCO, cumulative cash flow, the Subscription
offset, Arena, the PDF, scoring) calls estimate_operating_costs() - nothing
is keyed in per car, and a vehicle that satisfies the new-vehicle contract
(see the project spec) is costed automatically.

  - Road tax: JPJ, Peninsular Malaysia. Every powertrain except BEV - petrol
    and diesel alike - uses the cc table for the car's registration class,
    saloon or non-saloon (base + (cc - threshold) * per-cc rate); BEV uses
    the kW groups in force from 1 Jan 2026 (base, then + increment per
    further 10 kW block, rounded UP), which are not split by class.
  - Insurance: a percentage of the vehicle's price (sum insured = MSRP), per
    powertrain, less the buyer's No-Claim Discount when one is given. Only
    OWNER running costs get the buyer's NCD; a subscription fee is priced
    with none (the provider insures its own fleet).
  - Maintenance: a percentage of price per powertrain, never below a floor
    and never above a cap (when the rate row has one).

Insurance and maintenance are labelled planning assumptions, not tariffs.
All arithmetic is Decimal; each figure is rounded once, to 2 dp, with the
project's round_currency. Python is the only layer that does this math.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from apps.comparisons.formulas import round_currency
from apps.vehicles.models import POWERTRAIN_PHRASE, Powertrain, RoadTaxClass, default_road_tax_class

from .models import EvRoadTaxGroup, OperatingCostRate, RoadTaxCcBand

HUNDRED = Decimal("100")
TEN = Decimal("10")
NO_NCD = Decimal("0")

_CLASS_PHRASE = {RoadTaxClass.SALOON: "saloon", RoadTaxClass.NON_SALOON: "non-saloon"}

# Short, lower-case names for the human-readable basis lines - the one list in
# apps.vehicles.models, also used by the catalog cards.
_POWERTRAIN_PHRASE = POWERTRAIN_PHRASE


class OperatingCostConfigError(Exception):
    """The vehicle can't be costed - its specs are incomplete, or no rate
    row covers its cc/kW/powertrain. A 4xx, never a 500 (same pattern as
    ComparisonConfigError). Re-exported from apps.depreciation.services so
    existing handlers keep working."""


@dataclass(frozen=True)
class OperatingCosts:
    road_tax_annual: Decimal
    insurance_annual: Decimal
    maintenance_annual: Decimal
    # {"road_tax": "...", "insurance": "...", "maintenance": "..."} - plain
    # English for the UI, e.g. "1,998 cc petrol - JPJ cc schedule".
    basis: dict
    # FX-3: the yearly maintenance cap of the rate row used (None = no cap),
    # so a screen can name it; it changes no figure above.
    maintenance_cap_annual: Decimal | None = None


def _percent_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if "." in text else f"{text}.0"


def _number_text(value: Decimal) -> str:
    """55 -> "55", 38.33 -> "38.33" (no trailing zeros)."""
    return format(value.normalize(), "f")


def road_tax_for_cc(cc: int, vehicle_class: str = RoadTaxClass.SALOON) -> tuple[Decimal, RoadTaxCcBand]:
    """base + (cc - threshold_cc) * per_cc_rate for the band holding `cc` in
    the table for `vehicle_class` (saloon / non-saloon). Petrol and diesel
    read the same table (the old diesel schedule is archived and never read).
    Only that class's table is ever read: a cc it doesn't cover is an error,
    never a silent reuse of the other class's table."""
    band = (
        RoadTaxCcBand.objects.filter(is_active=True, vehicle_class=vehicle_class, min_cc__lte=cc, max_cc__gte=cc)
        .order_by("min_cc")
        .first()
    )
    if band is None:
        class_phrase = _CLASS_PHRASE.get(vehicle_class, vehicle_class)
        raise OperatingCostConfigError(f"No active {class_phrase} road tax band covers an engine capacity of {cc:,} cc.")
    amount = band.base_amount + Decimal(cc - band.threshold_cc) * band.per_cc_rate
    return round_currency(amount), band


def road_tax_for_kw(kw: Decimal) -> tuple[Decimal, EvRoadTaxGroup]:
    """The first active group whose max_kw covers `kw` (matching on the
    upper bound alone leaves no gap between e.g. 100 and JPJ's "100.1"):
    base while kW <= base_until_kw, then + increment per further 10 kW
    block, rounded up. A group with no base_until_kw is a fixed amount."""
    groups = list(EvRoadTaxGroup.objects.filter(is_active=True).order_by("min_kw"))
    group = next((g for g in groups if g.max_kw is None or kw <= g.max_kw), None)
    if group is None:
        raise OperatingCostConfigError(f"No active EV road tax group covers a motor output of {kw} kW.")
    amount = group.base_amount
    if group.base_until_kw is not None and kw > group.base_until_kw:
        blocks = ((kw - group.base_until_kw) / TEN).to_integral_value(rounding=ROUND_CEILING)
        amount = amount + blocks * group.increment_per_10kw
    return round_currency(amount), group


def vehicle_road_tax_class(vehicle) -> str:
    """The class stored on the car, or - for a row written without save()
    (bulk_create / queryset.update) - its body type's default, the same rule
    save() applies. "" only for an unknown body type."""
    return vehicle.road_tax_class or default_road_tax_class(vehicle.body_segment)


def _maintenance(rate, price):
    """(amount, basis): pct x price, never below the floor, never above the
    cap (when set); rounded once."""
    pct_text = _percent_text(rate.maintenance_rate_percent)
    from_rate = price * rate.maintenance_rate_percent / HUNDRED
    floor = rate.maintenance_floor_annual
    cap = rate.maintenance_cap_annual
    amount = max(from_rate, floor)
    if cap is not None and amount > cap:
        return round_currency(cap), f"{pct_text}% of price, capped at RM {cap:,.0f} (floor RM {floor:,.0f})"
    if from_rate >= floor:
        return round_currency(amount), f"{pct_text}% of price (floor RM {floor:,.0f})"
    return round_currency(amount), f"floor RM {floor:,.0f} ({pct_text}% of price is lower)"


def estimate_operating_costs(vehicle, *, ncd_percent=NO_NCD) -> OperatingCosts:
    """Annual road tax, insurance and maintenance for `vehicle`. Raises
    OperatingCostConfigError if the vehicle can't be costed - never guesses
    a powertrain.

    `ncd_percent` is the buyer's No-Claim Discount (0-55), applied to
    insurance only: insurance = price x rate% / 100 x (1 - NCD/100), rounded
    once. Callers costing an OWNER's running costs pass the buyer's NCD
    (apps.profiles.models.ncd_percent_for); the subscription fee estimate
    passes none."""
    ncd_percent = Decimal(str(ncd_percent))
    if not NO_NCD <= ncd_percent < HUNDRED:
        raise ValueError(f"No-Claim Discount must be at least 0% and under 100%, not {ncd_percent}%.")
    if not vehicle.spec_complete:
        raise OperatingCostConfigError(
            f"{vehicle} is missing its specs (powertrain / engine capacity). "
            "Complete them in Fleet Management."
        )

    powertrain = vehicle.powertrain
    phrase = _POWERTRAIN_PHRASE.get(powertrain, powertrain)
    if powertrain == Powertrain.BEV:
        # str() round-trip: an instance built in memory may still hold a str/float.
        kw = Decimal(str(vehicle.engine_capacity_kw))
        road_tax, group = road_tax_for_kw(kw)
        road_tax_basis = f"{format(kw.normalize(), 'f')} kW {phrase} - JPJ EV kW schedule, group {group.label}"
    else:
        cc = int(vehicle.engine_capacity_cc)
        # Petrol, diesel, mild hybrid, hybrid and PHEV all read the cc table
        # for the car's registration class - there is no diesel table.
        vehicle_class = vehicle_road_tax_class(vehicle)
        if not vehicle_class:
            raise OperatingCostConfigError(
                f"{vehicle} has no road-tax class (saloon / non-saloon). Set it in Fleet Management."
            )
        road_tax, _band = road_tax_for_cc(cc, vehicle_class)
        road_tax_basis = f"{cc:,} cc {phrase}, {_CLASS_PHRASE[vehicle_class]} - JPJ cc schedule"

    rate = OperatingCostRate.objects.filter(is_active=True, powertrain=powertrain).first()
    if rate is None:
        raise OperatingCostConfigError(f"No active insurance/maintenance rate is configured for {phrase} vehicles.")

    price = Decimal(str(vehicle.msrp))
    insurance = round_currency(price * rate.insurance_rate_percent / HUNDRED * (Decimal(1) - ncd_percent / HUNDRED))
    insurance_basis = f"{_percent_text(rate.insurance_rate_percent)}% of RM {price:,.2f}"
    if ncd_percent > NO_NCD:
        insurance_basis += f", less {_number_text(ncd_percent)}% NCD"
    maintenance, maintenance_basis = _maintenance(rate, price)

    return OperatingCosts(
        road_tax_annual=road_tax,
        insurance_annual=insurance,
        maintenance_annual=maintenance,
        basis={
            "road_tax": road_tax_basis,
            "insurance": insurance_basis,
            "maintenance": maintenance_basis,
        },
        maintenance_cap_annual=rate.maintenance_cap_annual,
    )
