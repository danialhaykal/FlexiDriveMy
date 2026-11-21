from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from rest_framework import serializers

from .models import (
    NCD_HELP_TEXT,
    NCD_STEPS,
    POSITIVE_AMOUNT_MESSAGE,
    TENURE_RANGE_MESSAGE,
    FinancialProfile,
    normalize_mileage_band,
)
from apps.common.constants import (
    DSR_LIMIT_ERROR_MESSAGES,
    MAX_TENURE_MONTHS,
    MIN_TENURE_MONTHS,
    dsr_limit_validators,
)
from apps.policy.models import MileageBand


class MileageBandField(serializers.ChoiceField):
    """The profile's mileage band: the same four bands as the compare screens
    (apps.policy.models.MileageBand). A legacy km value ("10000" / "20000" /
    "30000" - a row saved before audit batch 6, or an older client) is mapped
    to its band both ways, so it never errors: read gives the band, write
    stores the band."""

    def __init__(self, **kwargs):
        super().__init__(choices=MileageBand.choices, **kwargs)

    def to_internal_value(self, data):
        mapped = normalize_mileage_band(data) if isinstance(data, str) else None
        return super().to_internal_value(mapped if mapped is not None else data)

    def to_representation(self, value):
        mapped = normalize_mileage_band(value)
        return super().to_representation(mapped if mapped is not None else value)


class FinancialProfileSerializer(serializers.ModelSerializer):
    annual_mileage_band = MileageBandField()
    # Declared explicitly so both the "not a number" and "out of range"
    # cases surface UC003's exact wording, rather than DRF's generic
    # "A valid number is required." / "Ensure this value is..." messages.
    monthly_budget = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        error_messages={"invalid": POSITIVE_AMOUNT_MESSAGE},
        validators=[MinValueValidator(Decimal("0.01"), message=POSITIVE_AMOUNT_MESSAGE)],
    )
    preferred_tenure_months = serializers.IntegerField(
        error_messages={"invalid": TENURE_RANGE_MESSAGE},
        validators=[
            MinValueValidator(MIN_TENURE_MONTHS, message=TENURE_RANGE_MESSAGE),
            MaxValueValidator(MAX_TENURE_MONTHS, message=TENURE_RANGE_MESSAGE),
        ],
    )

    # Run 1 fix batch 3: a DecimalField checked against the six steps, rather
    # than a ChoiceField, so "55", "55.0" and "55.00" all mean 55%. Optional
    # (an older client that doesn't send it keeps the stored value / 0%).
    ncd_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, help_text=NCD_HELP_TEXT)
    # Run 1 fix batch 5 (A5): optional prefills for the AI Recommendation and
    # Affordability tabs. Declared so the messages are UC003's plain wording.
    monthly_income = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        error_messages={"invalid": POSITIVE_AMOUNT_MESSAGE},
        validators=[MinValueValidator(Decimal("0.01"), message=POSITIVE_AMOUNT_MESSAGE)],
    )
    max_dsr_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        error_messages=DSR_LIMIT_ERROR_MESSAGES,
        validators=dsr_limit_validators(),
    )

    class Meta:
        model = FinancialProfile
        fields = [
            "id",
            "monthly_budget",
            "preferred_tenure_months",
            "annual_mileage_band",
            "ownership_preference",
            "shariah_compliant_required",
            "ncd_percent",
            "monthly_income",
            "max_dsr_percent",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_ncd_percent(self, value):
        if value not in NCD_STEPS:
            steps = ", ".join(f"{format(step.normalize(), 'f')}%" for step in NCD_STEPS)
            raise serializers.ValidationError(f"Choose one of the standard NCD steps: {steps}.")
        return value
