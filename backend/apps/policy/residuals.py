"""The one residual-value estimator (audit batch 4).

GFV's G_ratio and the depreciation fallback curve both come from here, so a
car's GFV residual and its month-36/48/60 resale value in the TCO always
agree - and a new car, or a new brand, gets a sensible residual with nothing
keyed per car or per brand.

Resolution order for (vehicle, tenure_months, mileage_band):

  1. Override - an active ResidualValueMatrix row for the vehicle's brand,
     tenure and band is used exactly.
  2. Estimate - baseline(tenure, band) + brand adjustment + powertrain
     adjustment, clamped to [RESIDUAL_FLOOR_RATIO, MAX_GFV_RESIDUAL_RATIO]. A
     brand or powertrain with no active adjustment row gets 0 points.
  3. A tenure with no baseline row (GFV is offered for 12 to 60 months in
     12-month steps) raises ResidualConfigError carrying a customer-safe
     message.

Every seeded baseline and adjustment is a planning assumption, not market
data: real GFV residuals are set by the lender. See each row's source_note.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal

from apps.common.constants import MAX_GFV_RESIDUAL_RATIO

from .models import ResidualAdjustment, ResidualBaseline, ResidualValueMatrix
# The same buyer-readable powertrain names the running-cost basis uses
# ("plug-in hybrid", "electric"), so the two lines never word it differently.
from .operating_costs import _POWERTRAIN_PHRASE

RESIDUAL_FLOOR_RATIO = Decimal("0.10")
RATIO_PLACES = Decimal("0.0001")

SOURCE_OVERRIDE = "override"
SOURCE_ESTIMATE = "estimate"


class ResidualConfigError(Exception):
    """No residual can be resolved (no baseline for this tenure/band).
    str(exc) is the customer-safe message, not an admin/log one."""


@dataclass(frozen=True)
class ResidualResult:
    ratio: Decimal
    basis: str
    source: str  # "override" | "estimate"


def _pct(value: Decimal) -> str:
    """0.42 -> '42', 0.425 -> '42.5' (a ratio as a percent, no trailing zeros)."""
    text = f"{(value * 100).normalize():f}"
    return text


def _points(delta: Decimal) -> str:
    """0.06 -> '+6', -0.04 -> '-4', 0 -> '0' (ratio points)."""
    if delta == 0:
        return "0"
    return f"{(delta * 100).normalize():+f}"


def _band_label(mileage_band: str) -> str:
    return mileage_band.replace("_", " ")


def available_gfv_tenures(brand=None, mileage_band=None):
    """Tenures GFV can be priced for: every baseline tenure, plus any tenure
    this brand has an override row for at `mileage_band`."""
    tenures = set(
        ResidualBaseline.objects.filter(is_active=True).values_list("tenure_months", flat=True)
    )
    if brand is not None:
        overrides = ResidualValueMatrix.objects.filter(brand=brand, is_active=True)
        if mileage_band:
            overrides = overrides.filter(mileage_band=mileage_band)
        tenures |= set(overrides.values_list("tenure_months", flat=True))
    return sorted(tenures)


def _tenures_phrase(tenures):
    if not tenures:
        return "isn't offered for this model"
    if len(tenures) >= 3:
        step = tenures[1] - tenures[0]
        if step > 0 and all(b - a == step for a, b in zip(tenures, tenures[1:])):
            return f"is offered for {tenures[0]} to {tenures[-1]} months in {step}-month steps"
    return "is offered for " + ", ".join(str(t) for t in tenures) + " months"


def unavailable_message(tenure_months, brand=None, mileage_band=None):
    """Customer-facing reason GFV can't be shown for this tenure."""
    phrase = _tenures_phrase(available_gfv_tenures(brand, mileage_band))
    return f"GFV leasing isn't offered for {tenure_months} months - it {phrase}."


# FX-3 (X14): a read-only snapshot of the three residual tables for the length of one
# block (Vehicle Readiness resolves 20 tenure x band cells per car, and each
# resolve read the same rows again: ~830 of ~1,040 queries for 9 cars). Inside
# `residual_tables_snapshot()` every lookup below reads the snapshot instead of
# the database; each dict keeps the FIRST active row per key in the model's own
# Meta ordering - exactly the row `.filter(...).first()` returns - so every
# ratio, basis and source is unchanged. Outside the block nothing changes.
_SNAPSHOT = ContextVar("residual_tables_snapshot", default=None)


def _load_snapshot():
    overrides, baselines, brand_rows, power_rows = {}, {}, {}, {}
    for row in ResidualValueMatrix.objects.filter(is_active=True):
        overrides.setdefault((row.brand_id, row.tenure_months, row.mileage_band), row)
    for row in ResidualBaseline.objects.filter(is_active=True):
        baselines.setdefault((row.tenure_months, row.mileage_band), row)
    for row in ResidualAdjustment.objects.filter(is_active=True):
        if row.brand_id is not None:
            brand_rows.setdefault(row.brand_id, row)
        else:
            power_rows.setdefault(row.powertrain, row)
    return {"overrides": overrides, "baselines": baselines, "brand_rows": brand_rows, "power_rows": power_rows}


@contextmanager
def residual_tables_snapshot():
    token = _SNAPSHOT.set(_load_snapshot())
    try:
        yield
    finally:
        _SNAPSHOT.reset(token)


def resolve_residual_ratio(vehicle, tenure_months, mileage_band) -> ResidualResult:
    brand = vehicle.brand
    snapshot = _SNAPSHOT.get()

    if snapshot is not None:
        override = snapshot["overrides"].get((brand.pk, tenure_months, mileage_band))
    else:
        override = ResidualValueMatrix.objects.filter(
            brand=brand, tenure_months=tenure_months, mileage_band=mileage_band, is_active=True
        ).first()
    if override is not None:
        return ResidualResult(
            ratio=override.residual_value_ratio,
            basis=f"Admin override for {brand.name}, {tenure_months} months, {_band_label(mileage_band)} mileage",
            source=SOURCE_OVERRIDE,
        )

    if snapshot is not None:
        baseline = snapshot["baselines"].get((tenure_months, mileage_band))
    else:
        baseline = ResidualBaseline.objects.filter(
            tenure_months=tenure_months, mileage_band=mileage_band, is_active=True
        ).first()
    if baseline is None:
        raise ResidualConfigError(unavailable_message(tenure_months, brand, mileage_band))

    if snapshot is not None:
        brand_row = snapshot["brand_rows"].get(brand.pk)
    else:
        brand_row = ResidualAdjustment.objects.filter(brand=brand, is_active=True).first()
    brand_delta = brand_row.delta_points if brand_row is not None else Decimal("0")

    powertrain = vehicle.powertrain or ""
    if not powertrain:
        power_row = None
    elif snapshot is not None:
        power_row = snapshot["power_rows"].get(powertrain)
    else:
        power_row = ResidualAdjustment.objects.filter(brand__isnull=True, powertrain=powertrain, is_active=True).first()
    power_delta = power_row.delta_points if power_row is not None else Decimal("0")

    raw = baseline.ratio + brand_delta + power_delta
    ratio = min(max(raw, RESIDUAL_FLOOR_RATIO), MAX_GFV_RESIDUAL_RATIO).quantize(RATIO_PLACES)

    basis = (
        f"Estimate: {_pct(baseline.ratio)}% baseline for {tenure_months} months / {_band_label(mileage_band)} "
        f"mileage, {_points(brand_delta)} points {brand.name}, {_points(power_delta)} points "
        f"{_POWERTRAIN_PHRASE.get(powertrain, powertrain) if powertrain else 'no powertrain set'}"
    )
    if ratio != raw:
        basis += f" (limited to {_pct(ratio)}%)"
    return ResidualResult(ratio=ratio, basis=basis, source=SOURCE_ESTIMATE)
