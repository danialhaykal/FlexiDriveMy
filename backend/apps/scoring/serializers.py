from decimal import Decimal

from rest_framework import serializers

from apps.common.constants import (
    DSR_LIMIT_ERROR_MESSAGES,
    MAX_TENURE_MONTHS,
    MIN_TENURE_MONTHS,
    POSITIVE_AMOUNT_ERROR_MESSAGES,
    dsr_limit_validators,
    minimum_downpayment_for,
    minimum_downpayment_message,
)
from apps.policy.models import MileageBand
from apps.vehicles.models import VehicleModel

from .formulas import INCOMPLETE_QUIZ_MESSAGE, PATHWAYS

TENURE_RANGE_MESSAGE = f"Tenure must be between {MIN_TENURE_MONTHS} and {MAX_TENURE_MONTHS} months."


class SuitabilityScoringRequestSerializer(serializers.Serializer):
    """UC007 main-flow inputs, mirroring F005/F006's comparison request
    shape, plus the quiz priority ratings and DSR affordability inputs.
    """

    # select_related("brand"): build_suitability_scoring() -> build_comparison()
    # always accesses vehicle.brand - avoids an N+1 query per request.
    vehicle = serializers.PrimaryKeyRelatedField(
        queryset=VehicleModel.objects.select_related("brand").visible()
    )
    tenure_months = serializers.IntegerField(
        min_value=MIN_TENURE_MONTHS,
        max_value=MAX_TENURE_MONTHS,
        error_messages={"min_value": TENURE_RANGE_MESSAGE, "max_value": TENURE_RANGE_MESSAGE},
    )
    mileage_band = serializers.ChoiceField(choices=MileageBand.choices)
    downpayment = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), error_messages=POSITIVE_AMOUNT_ERROR_MESSAGES
    )

    # Declared required=False/allow_null=True at the field level so the
    # custom validate() below (not DRF's own per-field "required" errors)
    # produces UC007's exact alternate-flow message when any is missing.
    upfront_cash_preservation = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=5)
    maintenance_protection = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=5)
    ownership_equity = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=5)

    monthly_income = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"), error_messages=POSITIVE_AMOUNT_ERROR_MESSAGES
    )
    max_dsr_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, error_messages=DSR_LIMIT_ERROR_MESSAGES, validators=dsr_limit_validators()
    )

    def validate(self, attrs):
        priority_fields = ("upfront_cash_preservation", "maintenance_protection", "ownership_equity")
        if any(attrs.get(field) is None for field in priority_fields):
            raise serializers.ValidationError({"priorities": INCOMPLETE_QUIZ_MESSAGE})

        vehicle = attrs["vehicle"]
        if attrs["downpayment"] >= vehicle.msrp:
            raise serializers.ValidationError(
                {"downpayment": "Downpayment must be less than the vehicle's price."}
            )
        if attrs["downpayment"] < minimum_downpayment_for(vehicle.msrp):
            raise serializers.ValidationError(
                {"downpayment": minimum_downpayment_message(vehicle.msrp)}
            )
        return attrs


# --- Output --------------------------------------------------------------
# Same reasoning as apps.comparisons/apps.depreciation: route Decimal
# through DecimalField.to_representation() so currency/weights stay quoted
# strings on the wire instead of DRF's float() fallback.


class PathwayScoreSerializer(serializers.Serializer):
    monthly_instalment = serializers.DecimalField(max_digits=12, decimal_places=2)
    upfront_cash = serializers.DecimalField(max_digits=12, decimal_places=2)
    # A tiny declared monthly_income can legitimately push DSR far past a
    # realistic percentage (that's the point of the hard DSR override) -
    # generous max_digits avoids a quantize() crash on that edge case
    # instead of relying on callers never submitting a low income.
    dsr_percent = serializers.DecimalField(max_digits=14, decimal_places=2)
    exceeds_dsr = serializers.BooleanField()
    # Run 3 fix batch 5 (F-23): "Just over your 50% limit (50.00003%)." when the
    # 2-dp figure equals the limit but is over it; null otherwise. Optional so a
    # saved snapshot without it still validates.
    dsr_note = serializers.CharField(allow_null=True, required=False, default=None)
    suitability_score = serializers.DecimalField(max_digits=5, decimal_places=2)


class PriorityWeightsSerializer(serializers.Serializer):
    upfront_cash_preservation = serializers.DecimalField(max_digits=6, decimal_places=4)
    maintenance_protection = serializers.DecimalField(max_digits=6, decimal_places=4)
    ownership_equity = serializers.DecimalField(max_digits=6, decimal_places=4)


class SuitabilityScoringResultSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField()
    weights = PriorityWeightsSerializer()
    monthly_income = serializers.DecimalField(max_digits=12, decimal_places=2)
    max_dsr_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    # Only the pathways that could actually be scored (UC007 step 3:
    # "scores each available pathway") - a pathway missing its own F010/
    # F011 config is listed in `unavailable` with its reason instead,
    # never silently scored as 0 or omitted without explanation.
    pathways = serializers.DictField(child=PathwayScoreSerializer())
    ranking = serializers.ListField(child=serializers.ChoiceField(choices=PATHWAYS))
    recommended_pathway = serializers.ChoiceField(choices=PATHWAYS, allow_null=True)
    unavailable = serializers.DictField(child=serializers.CharField())
    rationale = serializers.CharField()


# --- Sprint 11: Affordability / DSR Simulator -------------------------------
# A separate endpoint, not a modification of SuitabilityScoringRequestSerializer/
# SuitabilityScoringResultSerializer above - this tool only reports DSR/CCRIS
# figures, it doesn't rank or recommend, so it carries no priority-rating
# fields at all.


class DSRSimulatorRequestSerializer(serializers.Serializer):
    vehicle = serializers.PrimaryKeyRelatedField(
        queryset=VehicleModel.objects.select_related("brand").visible()
    )
    tenure_months = serializers.IntegerField(
        min_value=MIN_TENURE_MONTHS,
        max_value=MAX_TENURE_MONTHS,
        error_messages={"min_value": TENURE_RANGE_MESSAGE, "max_value": TENURE_RANGE_MESSAGE},
    )
    mileage_band = serializers.ChoiceField(choices=MileageBand.choices)
    downpayment = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), error_messages=POSITIVE_AMOUNT_ERROR_MESSAGES
    )
    monthly_income = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"), error_messages=POSITIVE_AMOUNT_ERROR_MESSAGES
    )
    max_dsr_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, error_messages=DSR_LIMIT_ERROR_MESSAGES, validators=dsr_limit_validators()
    )
    # Optional: omitting it means "no other debt declared", never a
    # validation error - defaults to 0 rather than requiring every caller
    # to pass it explicitly.
    existing_monthly_commitments = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
        default=Decimal("0"),
        error_messages=POSITIVE_AMOUNT_ERROR_MESSAGES,
    )

    def validate(self, attrs):
        vehicle = attrs["vehicle"]
        if attrs["downpayment"] >= vehicle.msrp:
            raise serializers.ValidationError(
                {"downpayment": "Downpayment must be less than the vehicle's price."}
            )
        if attrs["downpayment"] < minimum_downpayment_for(vehicle.msrp):
            raise serializers.ValidationError(
                {"downpayment": minimum_downpayment_message(vehicle.msrp)}
            )
        return attrs


class DSRSimulatorPathwaySerializer(serializers.Serializer):
    monthly_instalment = serializers.DecimalField(max_digits=12, decimal_places=2)
    existing_monthly_commitments = serializers.DecimalField(max_digits=12, decimal_places=2)
    # Same generous max_digits reasoning as PathwayScoreSerializer.dsr_percent
    # above: a tiny declared income can legitimately push this far past a
    # realistic percentage.
    dsr_percent = serializers.DecimalField(max_digits=14, decimal_places=2)
    exceeds_dsr = serializers.BooleanField()
    dsr_note = serializers.CharField(allow_null=True, required=False, default=None)  # Run 3 fix batch 5 (F-23)
    is_ccris_reportable = serializers.BooleanField()


class DSRSimulatorResultSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField()
    monthly_income = serializers.DecimalField(max_digits=12, decimal_places=2)
    max_dsr_percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    # Only the pathways that could actually be simulated - a pathway
    # missing its own F010/F011 config is listed in `unavailable` with
    # its reason instead.
    pathways = serializers.DictField(child=DSRSimulatorPathwaySerializer())
    unavailable = serializers.DictField(child=serializers.CharField())
