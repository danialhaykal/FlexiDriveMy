"""The ONE definition of the mileage bands (audit batch 6, F6; Run 3 fix batch 6).

Every range, label, representative km, included km and the km-to-band mapping
comes from here, and here takes its numbers from ONE place: the active
SubscriptionPolicy's four included-km fields (low_km_cap, standard_km_cap,
high_km_cap, very_high_km_cap - policy data, editable in Django admin; the model
field defaults stand in when no policy is active). The four band KEYS (low /
standard / high / very_high) never change, so saved snapshots, URLs and fixtures
keep working.

Ranges are "up to and including" the band's limit:
    low        up to low_km_cap
    standard   low_km_cap + 1  to standard_km_cap
    high       standard_km_cap + 1 to high_km_cap
    very_high  above high_km_cap (modelled and sold up to very_high_km_cap)

Representative km a year (what the resale model is fed for a band) - the same
rule as before this batch: the midpoint of each band, taking very_high's upper
end as its modelling cap; low is fixed at LOW_REPRESENTATIVE_SHARE of its limit
(it has no lower edge to take a midpoint from: 8,000 km for a 10,000 limit, the
value it has always had). These are modelling ASSUMPTIONS, not market data.

Included km a year (what a Subscription in the band includes) = the band's limit.
"""

from dataclasses import dataclass
from decimal import Decimal

from .models import MileageBand, SubscriptionPolicy

BAND_ORDER = tuple(MileageBand.values)  # low, standard, high, very_high
CAP_FIELDS = {
    "low": "low_km_cap",
    "standard": "standard_km_cap",
    "high": "high_km_cap",
    "very_high": "very_high_km_cap",
}
_NAMES = {"low": "Low", "standard": "Standard", "high": "High", "very_high": "Very high"}
# Assumption: a low-band driver is modelled at 80% of the low limit (8,000 km for 10,000).
LOW_REPRESENTATIVE_SHARE = Decimal("0.8")


@dataclass(frozen=True)
class BandDefinition:
    key: str
    name: str
    lower_km: int  # the band starts ABOVE this (0 for low)
    upper_km: int  # up to and including this; for very_high, its modelling/selling cap
    included_km: int
    representative_km: Decimal
    label: str


def _active_policy():
    return SubscriptionPolicy.objects.filter(is_active=True).first()


def band_caps(policy=None):
    """{band: upper km} from the policy, else from the model field defaults (the seeded values)."""
    policy = policy if policy is not None else _active_policy()
    if policy is None:
        return {band: SubscriptionPolicy._meta.get_field(field).default for band, field in CAP_FIELDS.items()}
    return {band: getattr(policy, field) for band, field in CAP_FIELDS.items()}


def _label(key, lower, upper):
    name = _NAMES[key]
    if key == "low":
        return f"{name} — up to {upper:,} km/year"
    if key == "very_high":
        return f"{name} — above {lower:,} km/year"
    return f"{name} — {lower + 1:,} to {upper:,} km/year"


def band_definitions(policy=None):
    """The four bands, low to very high, as BandDefinition."""
    caps = band_caps(policy)
    bands, lower = [], 0
    for key in BAND_ORDER:
        upper = caps[key]
        if key == "low":
            representative = (Decimal(upper) * LOW_REPRESENTATIVE_SHARE).quantize(Decimal(1))
        else:
            representative = (Decimal(lower) + Decimal(upper)) / Decimal(2)
        bands.append(BandDefinition(key, _NAMES[key], lower, upper, upper, representative, _label(key, lower, upper)))
        lower = upper
    return bands


def band_definition(band, policy=None):
    for definition in band_definitions(policy):
        if definition.key == band:
            return definition
    raise KeyError(band)


def representative_km(band, policy=None):
    """The km a year the resale model is fed for this band (Decimal)."""
    return band_definition(band, policy).representative_km


def included_km(band, policy=None):
    """The km a year a Subscription in this band includes."""
    return band_definition(band, policy).included_km


def band_for_km(annual_km, policy=None):
    """The band an annual mileage falls in - "up to and including" each band's limit."""
    km = Decimal(str(annual_km))
    definitions = band_definitions(policy)
    for definition in definitions[:-1]:
        if km <= definition.upper_km:
            return definition.key
    return definitions[-1].key


def mileage_band_options():
    """[{value, label, lower_km, upper_km, included_km_per_year, representative_km_per_year}], low to very high -
    what GET /api/comparisons/mileage-bands/ serves and every screen shows."""
    return [
        {
            "value": d.key, "label": d.label, "lower_km": d.lower_km, "upper_km": d.upper_km,
            "included_km_per_year": d.included_km, "representative_km_per_year": int(d.representative_km),
        }
        for d in band_definitions()
    ]


def mileage_band_label(band):
    """The screen's label for one band - the PDF prints this, never the raw band code."""
    for option in mileage_band_options():
        if option["value"] == band:
            return option["label"]
    return str(band)


def bands_help_text(policy=None):
    """One line for admin help text, generated from the definition."""
    return "; ".join(d.label for d in band_definitions(policy)) + "."
