from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.constants import DSR_RANGE_MESSAGE, MAX_TENURE_MONTHS, MIN_TENURE_MONTHS, dsr_limit_validators
from apps.common.models import TimeStampedModel
from apps.policy.models import MileageBand

POSITIVE_AMOUNT_MESSAGE = "Please enter a valid positive numerical amount."
TENURE_RANGE_MESSAGE = "Preferred tenure must be between 12 and 108 months (1 to 9 years)."
# DSR_RANGE_MESSAGE and the 1-100 validators are shared (apps.common.constants): the
# profile, the AI Recommendation request and the DSR simulator use the same ones.


class AnnualMileageBand(models.TextChoices):
    """LEGACY (audit batch 6, F6): the profile's original three literal-km
    values. The profile now stores the SAME four named bands the compare
    screens use (apps.policy.models.MileageBand: low / standard / high /
    very_high), so one list serves both. These values are kept only so a
    profile saved before then still loads - see normalize_mileage_band."""

    KM_10000 = "10000", "10,000 km/year"
    KM_20000 = "20000", "20,000 km/year"
    KM_30000 = "30000", "30,000 km/year"


# How an OLD stored value maps to a current band. The mapping is FROZEN as the
# band the user effectively chose when the value was saved (each legacy value was
# the lower edge of a band in the scheme of that time), so a profile's meaning
# never changes. Run 3 fix batch 6 recalibrated the band ranges (apps.policy.mileage
# is the one definition) but deliberately kept this mapping: it records the old
# choice, not a km figure to re-band. None maps to "low".
ANNUAL_MILEAGE_BAND_TO_POLICY_BAND = {
    AnnualMileageBand.KM_10000: "standard",
    AnnualMileageBand.KM_20000: "high",
    AnnualMileageBand.KM_30000: "very_high",
}


def normalize_mileage_band(value):
    """The current policy band for a stored profile value: a current band is
    returned as is, a legacy km value is mapped, anything else is None (callers
    treat that as "nothing declared", never an error)."""
    if value in MileageBand.values:
        return value
    return ANNUAL_MILEAGE_BAND_TO_POLICY_BAND.get(value)


class OwnershipPreference(models.TextChoices):
    RETAIN = "retain", "Retain the vehicle"
    UPGRADE = "upgrade", "Upgrade at contract end"


# Run 1 fix batch 3 (C3): Malaysia's standard No-Claim Discount steps, in
# percent (0 for a new driver, then 25, 30, 38.33, 45 and 55% after five
# claim-free years).
NCD_STEPS = [Decimal("0.00"), Decimal("25.00"), Decimal("30.00"), Decimal("38.33"), Decimal("45.00"), Decimal("55.00")]
NCD_LABEL = "No-Claim Discount (NCD) on your current car insurance"
NCD_HELP_TEXT = "Check your last insurance renewal notice. New drivers start at 0%."


class FinancialProfile(TimeStampedModel):
    """F003 - a user's financial & lifestyle profiling baseline (UC003).
    One per user; saved via an upsert (PUT), not per-row CRUD."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="financial_profile"
    )
    monthly_budget = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"), message=POSITIVE_AMOUNT_MESSAGE)],
    )
    preferred_tenure_months = models.PositiveIntegerField(
        validators=[
            MinValueValidator(MIN_TENURE_MONTHS, message=TENURE_RANGE_MESSAGE),
            MaxValueValidator(MAX_TENURE_MONTHS, message=TENURE_RANGE_MESSAGE),
        ]
    )
    # The same four bands as the compare screens (audit batch 6). A row saved
    # before then may still hold a legacy km value; the API maps it on read.
    annual_mileage_band = models.CharField(max_length=10, choices=MileageBand.choices)
    ownership_preference = models.CharField(max_length=10, choices=OwnershipPreference.choices)
    shariah_compliant_required = models.BooleanField(default=False)
    # Run 1 fix batch 5 (A5): prefill the AI Recommendation and Affordability
    # inputs (the buyer can still change them per comparison; a saved
    # scenario keeps what was actually sent). Income is optional.
    monthly_income = models.DecimalField(
        "monthly income (RM)",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"), message=POSITIVE_AMOUNT_MESSAGE)],
    )
    max_dsr_percent = models.DecimalField(
        "max DSR limit (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("60.00"),
        validators=dsr_limit_validators(),
    )
    # Applied to insurance in the OWNER's running costs only (HP, GFV, TCO,
    # the subscription's net-cost offset) - never to a subscription fee.
    ncd_percent = models.DecimalField(
        NCD_LABEL,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        choices=[(step, f"{format(step.normalize(), 'f')}%") for step in NCD_STEPS],
        help_text=NCD_HELP_TEXT,
    )

    def __str__(self):
        return f"Financial profile for {self.user.email}"


def declared_mileage_band_for(user):
    """The user's declared mileage band (UC006 step 9's mismatch alert), or
    None when they have no saved profile - the one lookup the live TCO
    endpoint and a saved scenario's snapshot both use."""
    financial_profile = FinancialProfile.objects.filter(user=user).first()
    if financial_profile is None:
        return None
    return normalize_mileage_band(financial_profile.annual_mileage_band)


def ncd_percent_for(user):
    """The user's No-Claim Discount from their own profile (Decimal("0.00")
    with no profile). Every calculation endpoint reads it here - never from
    the request - so a client can't claim a discount it doesn't have."""
    value = FinancialProfile.objects.filter(user=user).values_list("ncd_percent", flat=True).first()
    return value if value is not None else Decimal("0.00")


def prefers_islamic_financing(user):
    """True only if the user ticked "I prefer Islamic financing" (wording
    only: "profit rate" for "interest rate" - no figure changes). Shared by
    the PDF export and a saved scenario's snapshot."""
    return FinancialProfile.objects.filter(user=user, shariah_compliant_required=True).exists()
