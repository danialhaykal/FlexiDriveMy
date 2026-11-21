from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from rest_framework import serializers

from .effective_dates import EffectiveFromNotFutureSerializerMixin
from .models import (
    ContractPenaltyRule,
    InterestRate,
    MCDACriteriaWeight,
    MCDACriterion,
    EvRoadTaxGroup,
    OperatingCostRate,
    ResidualAdjustment,
    ResidualBaseline,
    ResidualValueMatrix,
    RoadTaxCcBand,
    SubscriptionPlan,
    SubscriptionPolicy,
    contract_rule_errors,
)
from apps.vehicles.models import Brand

# The three weights are 4 dp (max_digits 5) and must add up to exactly this.
WEIGHT_SUM = Decimal("1.0000")

# QA audit L1: exact UC011 alternate-flow copy. "%%" (not a literal "%")
# is deliberate - Django's MinValueValidator/MaxValueValidator format
# their `message` as `message % params` when raising (params={"limit_value":
# ...}), so a literal "%" in the string is misread as the start of a
# printf-style conversion specifier and crashes instead of displaying -
# confirmed the hard way (ValueError: unsupported format character), not
# a hypothetical concern.
INTEREST_RATE_RANGE_MESSAGE = "Interest rate input exceeds acceptable limits (0.01%% – 15.00%%)."

ARCHIVED_VEHICLE_MESSAGE = "Vehicle is archived and cannot be assigned to new records."


class ActiveBrandOnlyMixin:
    """Same guard as VehicleModelSerializer.validate_brand: a new row can't
    be filed under an archived brand. Unlike that one, editing a row may
    keep the row's OWN brand after it was archived (AdminPolicyPage keeps
    it selectable) - only switching TO a different archived brand fails."""

    def validate_brand(self, value):
        if value is None:  # only serializers whose brand may be null (the default contract rule)
            return value
        keeping_own_brand = self.instance is not None and self.instance.brand_id == value.pk
        if not value.is_active and not keeping_own_brand:
            raise serializers.ValidationError("Brand is archived and cannot be assigned to new records.")
        return value


class InterestRateSerializer(ActiveBrandOnlyMixin, serializers.ModelSerializer):
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    # Declared explicitly (rather than left to ModelSerializer's auto
    # min/max kwargs, which do NOT carry over a model validator's custom
    # `message=` - DRF builds its own generic "Ensure this value is..."
    # text for an auto-derived field regardless of what the underlying
    # model validator says) so UC011's exact copy actually reaches the
    # API response, matching apps.vehicles.serializers.
    # VehicleModelSerializer's same pattern for msrp/engine_capacity_kw.
    rate_percent = serializers.DecimalField(
        max_digits=6,
        decimal_places=4,
        validators=[
            MinValueValidator(Decimal("0.01"), message=INTEREST_RATE_RANGE_MESSAGE),
            MaxValueValidator(Decimal("15.00"), message=INTEREST_RATE_RANGE_MESSAGE),
        ],
    )

    class Meta:
        model = InterestRate
        fields = ["id", "brand", "brand_name", "rate_percent", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def validate(self, attrs):
        # QA audit H12: is_active is read-only above (every new row is
        # created active, per the model's own default) and the DB now
        # enforces at most one active rate per brand - without this
        # check, creating a second one for a brand that already has an
        # active rate would be a raw IntegrityError (an unhandled 500),
        # not a clean validation message. Archive the old rate first
        # (DELETE, which soft-deletes) to replace it.
        if self.instance is None:
            brand = attrs.get("brand")
            if brand and InterestRate.objects.filter(brand=brand, is_active=True).exists():
                raise serializers.ValidationError(
                    {
                        "brand": (
                            f"'{brand.name}' already has an active interest rate. "
                            "Archive it first, then create the replacement."
                        )
                    }
                )
        return attrs


class ResidualValueMatrixSerializer(ActiveBrandOnlyMixin, serializers.ModelSerializer):
    brand_name = serializers.CharField(source="brand.name", read_only=True)

    class Meta:
        model = ResidualValueMatrix
        fields = [
            "id",
            "brand",
            "brand_name",
            "tenure_months",
            "mileage_band",
            "residual_value_ratio",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def validate(self, attrs):
        # QA audit M18/H12: the model's uniqueness constraint is now
        # scoped to active rows only (condition=Q(is_active=True), so an
        # archived cell can be replaced) - DRF's ModelSerializer only
        # auto-generates a validator for an UNCONDITIONAL UniqueConstraint,
        # so a conditional one like this needs its own explicit check here,
        # otherwise a genuine duplicate active row would only be caught as
        # a raw IntegrityError (an unhandled 500) at save time.
        if self.instance is None:
            brand = attrs.get("brand")
            tenure_months = attrs.get("tenure_months")
            mileage_band = attrs.get("mileage_band")
            if (
                brand
                and ResidualValueMatrix.objects.filter(
                    brand=brand, tenure_months=tenure_months, mileage_band=mileage_band, is_active=True
                ).exists()
            ):
                raise serializers.ValidationError(
                    f"'{brand.name}' already has an active residual ratio for {tenure_months} months / "
                    f"'{mileage_band}' mileage band. Archive it first, then create the replacement."
                )
        return attrs


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """Batch 6A. One active plan per vehicle - see
    apps.policy.models.SubscriptionPlan's own docstring for why the
    underlying field is a ForeignKey + conditional UniqueConstraint
    (not a OneToOneField) now, making the same "archive first, then
    create the replacement" guard below (InterestRateSerializer's own
    pattern) actually work end to end."""

    vehicle_label = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = [
            "id",
            "vehicle",
            "vehicle_label",
            "fee_monthly",
            # Deprecated (audit batch 2): insurance/road tax/maintenance are
            # derived by apps.policy.operating_costs and nothing reads these
            # three. Still returned (existing rows, history) but optional on
            # write - a plan needs only fee_monthly.
            "insurance_annual",
            "road_tax_annual",
            "maintenance_annual",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]
        extra_kwargs = {
            "insurance_annual": {"required": False},
            "road_tax_annual": {"required": False},
            "maintenance_annual": {"required": False},
        }

    def get_vehicle_label(self, obj):
        vehicle = obj.vehicle
        return f"{vehicle.brand.name} {vehicle.name} {vehicle.trim}"

    def validate_vehicle(self, value):
        # Run 3 fix batch 4 (F-13): same rule as ActiveBrandOnlyMixin - a quote
        # may not be filed under an archived car; editing one may keep its OWN car.
        keeping_own_vehicle = self.instance is not None and self.instance.vehicle_id == value.pk
        if not value.is_active and not keeping_own_vehicle:
            raise serializers.ValidationError(ARCHIVED_VEHICLE_MESSAGE)
        return value

    def validate(self, attrs):
        if self.instance is None:
            vehicle = attrs.get("vehicle")
            if vehicle and SubscriptionPlan.objects.filter(vehicle=vehicle, is_active=True).exists():
                raise serializers.ValidationError(
                    {
                        "vehicle": (
                            f"'{vehicle}' already has an active subscription plan. "
                            "Archive it first, then create the replacement."
                        )
                    }
                )
        return attrs


class RoadTaxCcBandReadSerializer(EffectiveFromNotFutureSerializerMixin, serializers.ModelSerializer):
    """Read-only view of the JPJ cc road-tax tables (Policy Configuration
    "Operating Costs" tab). Edited in Django admin, not through the API.
    fuel_schedule is kept only to label the archived diesel rows."""

    vehicle_class_label = serializers.CharField(source="get_vehicle_class_display", read_only=True)

    class Meta:
        model = RoadTaxCcBand
        fields = [
            "id", "vehicle_class", "vehicle_class_label", "fuel_schedule", "min_cc", "max_cc", "base_amount",
            "threshold_cc", "per_cc_rate", "source_note", "effective_from", "is_active",
        ]


class EvRoadTaxGroupReadSerializer(EffectiveFromNotFutureSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = EvRoadTaxGroup
        fields = [
            "id", "label", "min_kw", "max_kw", "base_amount", "base_until_kw", "increment_per_10kw",
            "source_note", "effective_from",
        ]


class OperatingCostRateReadSerializer(EffectiveFromNotFutureSerializerMixin, serializers.ModelSerializer):
    powertrain_label = serializers.CharField(source="get_powertrain_display", read_only=True)

    class Meta:
        model = OperatingCostRate
        fields = [
            "id", "powertrain", "powertrain_label", "insurance_rate_percent", "maintenance_rate_percent",
            "maintenance_floor_annual", "maintenance_cap_annual", "source_note", "effective_from",
        ]

class ResidualBaselineReadSerializer(EffectiveFromNotFutureSerializerMixin, serializers.ModelSerializer):
    """Read-only (Policy Configuration "Residual Estimates" tab). Edited in
    Django admin, not through the API."""

    class Meta:
        model = ResidualBaseline
        fields = ["id", "tenure_months", "mileage_band", "ratio", "source_note", "effective_from"]


class ResidualAdjustmentReadSerializer(EffectiveFromNotFutureSerializerMixin, serializers.ModelSerializer):
    brand_name = serializers.CharField(source="brand.name", read_only=True, default=None)
    powertrain_label = serializers.CharField(source="get_powertrain_display", read_only=True)

    class Meta:
        model = ResidualAdjustment
        fields = [
            "id", "brand", "brand_name", "powertrain", "powertrain_label", "delta_points",
            "source_note", "effective_from",
        ]


class SubscriptionPolicyReadSerializer(EffectiveFromNotFutureSerializerMixin, serializers.ModelSerializer):
    """Read-only (Policy Configuration "Subscription Estimates" tab): the
    planning assumptions the Subscription fee is estimated from. Edited in
    Django admin, not through the API."""

    class Meta:
        model = SubscriptionPolicy
        fields = [
            "id", "min_tenure_months", "max_tenure_months", "funding_rate_percent", "margin_percent",
            "deposit_months", "low_km_cap", "standard_km_cap", "high_km_cap", "very_high_km_cap", "source_note",
            "effective_from",
        ]


class ContractPenaltyRuleSerializer(ActiveBrandOnlyMixin, serializers.ModelSerializer):
    """brand = null is the single DEFAULT rule every brand without its own
    row falls back to. early_termination_months is N months of the
    instalment (a brand rule may leave it empty to inherit the default's);
    the deprecated early_termination_fee column is not exposed."""

    brand = serializers.PrimaryKeyRelatedField(
        queryset=Brand.objects.all(), allow_null=True, required=False
    )
    brand_name = serializers.CharField(source="brand.name", read_only=True, default=None)

    class Meta:
        model = ContractPenaltyRule
        fields = [
            "id",
            "brand",
            "brand_name",
            "excess_mileage_charge_per_km",
            "early_termination_months",
            "wear_tear_tolerance_description",
            "source_note",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def validate(self, attrs):
        # Same "archive first, then create the replacement" guard as
        # InterestRateSerializer - one active rule per brand, and one
        # active default (no brand).
        brand = attrs.get("brand", self.instance.brand if self.instance is not None else None)
        clashes = ContractPenaltyRule.objects.filter(brand=brand, is_active=True)
        if self.instance is not None:
            clashes = clashes.exclude(pk=self.instance.pk)
        if brand is None:
            if clashes.exists():
                raise serializers.ValidationError(
                    {"brand": "A default contract penalty rule already exists. Archive it first, then create the replacement."}
                )
            months = attrs.get(
                "early_termination_months", self.instance.early_termination_months if self.instance else None
            )
            if months is None:
                raise serializers.ValidationError(
                    {"early_termination_months": "The default rule must state its early termination months."}
                )
        elif clashes.exists():
            raise serializers.ValidationError(
                {
                    "brand": (
                        f"'{brand.name}' already has an active contract penalty rule. "
                        "Archive it first, then create the replacement."
                    )
                }
            )
        # Run 3 fix batch 4 (F-15, F-16): the same check Django admin runs (the model's clean()).
        errors = contract_rule_errors(
            brand_id=brand.pk if brand is not None else None,
            early_termination_months=attrs.get(
                "early_termination_months", self.instance.early_termination_months if self.instance else None
            ),
            wear_tear_tolerance_description=attrs.get(
                "wear_tear_tolerance_description",
                self.instance.wear_tear_tolerance_description if self.instance else "",
            ),
        )
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class MCDACriteriaWeightSerializer(serializers.ModelSerializer):
    class Meta:
        model = MCDACriteriaWeight
        fields = ["id", "criterion", "default_weight", "is_active", "updated_at"]
        read_only_fields = fields


class MCDAWeightItemSerializer(serializers.Serializer):
    criterion = serializers.ChoiceField(choices=MCDACriterion.choices)
    default_weight = serializers.DecimalField(max_digits=5, decimal_places=4, min_value=Decimal("0"), max_value=Decimal("1"))


class MCDAWeightSetSerializer(serializers.Serializer):
    """Replaces all three MCDA criteria weights at once (see apps/policy/views.py
    for why this isn't a per-row CRUD endpoint): the Sum(w_j) = 1 rule from
    the project spec spans all three rows, so partial per-row updates can never
    satisfy it on their own.
    """

    weights = MCDAWeightItemSerializer(many=True)

    def validate_weights(self, value):
        criteria_seen = [item["criterion"] for item in value]
        expected = set(MCDACriterion.values)
        if set(criteria_seen) != expected or len(criteria_seen) != len(expected):
            raise serializers.ValidationError(
                f"Must supply exactly these criteria, each once: {', '.join(sorted(expected))}."
            )
        total = sum((item["default_weight"] for item in value), Decimal("0"))
        # Run 3 fix batch 4 (F-11): exactly 1.0000 at the field's 4 dp - the old
        # 0.0001 tolerance let 0.3333 x 3 = 0.9999 through.
        if total != WEIGHT_SUM:
            raise serializers.ValidationError(f"Weights must sum to 1.0 (got {total}).")
        return value
