import copy
import json
from collections.abc import Mapping

from rest_framework import serializers
from rest_framework.serializers import as_serializer_error

from apps.comparisons.serializers import ComparisonRequestSerializer
from apps.scoring.serializers import SuitabilityScoringRequestSerializer
from apps.vehicles.models import VehicleModel

from .models import SavedScenario

# FX-1 (X8): "comparison" and "title", the words the app uses everywhere else (it said "A scenario with this label ...").
DUPLICATE_TITLE_MESSAGE = (
    "A comparison with this title already exists. Please choose a different title "
    "or overwrite the existing comparison."
)

# Run 1 fix batch 2 (G6): an old browser tab still sending its own figures
# learns why the save failed instead of having them silently dropped.
PAYLOAD_NOT_ACCEPTED_MESSAGE = (
    "Saved comparisons are now calculated by the server. Please refresh the page and save again."
)
FIGURES_ARE_FIXED_MESSAGE = (
    "A saved comparison's figures can't be changed. Save a new comparison instead; only the title can be renamed."
)

# QA audit M3: 256 KB comfortably covers a real saved snapshot (comparison +
# TCO + scoring results, all plain strings/numbers) with headroom. The server
# builds the payload now, so this is a safety check on what it built.
MAX_PAYLOAD_BYTES = 256_000


def _same_rules_as(serializer_class, field_name):
    """A copy of a live request serializer's own field, so a saved
    scenario's inputs follow exactly the rules the live endpoint applies
    (ranges, choices, error wording) without restating them."""
    return copy.deepcopy(serializer_class._declared_fields[field_name])


class ScenarioScoringInputsSerializer(serializers.Serializer):
    """The AI Recommendation request the buyer actually sent: the three
    priority ratings, income and DSR limit."""

    upfront_cash_preservation = _same_rules_as(SuitabilityScoringRequestSerializer, "upfront_cash_preservation")
    maintenance_protection = _same_rules_as(SuitabilityScoringRequestSerializer, "maintenance_protection")
    ownership_equity = _same_rules_as(SuitabilityScoringRequestSerializer, "ownership_equity")
    monthly_income = _same_rules_as(SuitabilityScoringRequestSerializer, "monthly_income")
    max_dsr_percent = _same_rules_as(SuitabilityScoringRequestSerializer, "max_dsr_percent")


class ScenarioInputsSerializer(serializers.Serializer):
    """What a new saved scenario is calculated from. The cross-field rules
    that need the vehicle (price, 10% minimum downpayment, unrated
    priorities) run in SavedScenarioSerializer.validate, via the live
    request serializers' own validate()."""

    tenure_months = _same_rules_as(ComparisonRequestSerializer, "tenure_months")
    mileage_band = _same_rules_as(ComparisonRequestSerializer, "mileage_band")
    downpayment = _same_rules_as(ComparisonRequestSerializer, "downpayment")
    include_tco = serializers.BooleanField(required=False, default=False)
    scoring = ScenarioScoringInputsSerializer(required=False, allow_null=True, default=None)


class SavedScenarioSerializer(serializers.ModelSerializer):
    vehicle = serializers.PrimaryKeyRelatedField(
        queryset=VehicleModel.objects.select_related("brand").visible()
    )
    vehicle_label = serializers.SerializerMethodField()
    # Write-only: what the server calculates the snapshot from (see
    # apps.scenarios.snapshot). Required on create; refused on a rename.
    inputs = ScenarioInputsSerializer(write_only=True, required=False)

    class Meta:
        model = SavedScenario
        fields = ["id", "title", "vehicle", "vehicle_label", "inputs", "payload", "created_at", "updated_at"]
        # payload is built by the server (run 1 fix batch 2, G6), never written by a client.
        read_only_fields = ["id", "payload", "created_at", "updated_at"]
        # The model's (user, title) UniqueConstraint is handled explicitly
        # in the view (reject-and-rename vs. overwrite, UC009 alt flow) -
        # "user" isn't even in `fields` above, so DRF's own auto-generated
        # UniqueTogetherValidator would either be silently skipped or
        # produce a generic error that preempts that custom handling.
        # Disabling it here makes that explicit rather than relying on it.
        validators = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None:
            self.fields["inputs"].required = True
        else:
            # A rename: only the title can change.
            self.fields["vehicle"].required = False

    def get_vehicle_label(self, obj):
        return f"{obj.vehicle.brand.name} {obj.vehicle.name} {obj.vehicle.trim}"

    def to_internal_value(self, data):
        # Checked before any field so the reason is the first thing a client
        # sees, not a "this field is required" for inputs.
        if isinstance(data, Mapping):
            if "payload" in data:
                raise serializers.ValidationError({"payload": [PAYLOAD_NOT_ACCEPTED_MESSAGE]})
            if self.instance is not None and "inputs" in data:
                raise serializers.ValidationError({"inputs": [FIGURES_ARE_FIXED_MESSAGE]})
        return super().to_internal_value(data)

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Title must not be blank.")
        return value

    def validate(self, attrs):
        if self.instance is not None:
            vehicle = attrs.get("vehicle")
            if vehicle is not None and vehicle.pk != self.instance.vehicle_id:
                raise serializers.ValidationError({"vehicle": [FIGURES_ARE_FIXED_MESSAGE]})
            return attrs

        vehicle, inputs = attrs["vehicle"], attrs["inputs"]
        # as_serializer_error: the same {"field": ["message"]} shape the live
        # endpoint returns for these rules.
        try:
            ComparisonRequestSerializer().validate({"vehicle": vehicle, "downpayment": inputs["downpayment"]})
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({"inputs": as_serializer_error(exc)})

        scoring = inputs.get("scoring")
        if scoring is not None:
            try:
                SuitabilityScoringRequestSerializer().validate(
                    {**scoring, "vehicle": vehicle, "downpayment": inputs["downpayment"]}
                )
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({"inputs": {"scoring": as_serializer_error(exc)}})
        return attrs


def check_payload_size(payload):
    """QA audit M3's size cap, now applied to the payload the server built."""
    encoded_size = len(json.dumps(payload).encode("utf-8"))
    if encoded_size > MAX_PAYLOAD_BYTES:
        raise serializers.ValidationError(
            {"payload": [f"payload is too large ({encoded_size} bytes; maximum is {MAX_PAYLOAD_BYTES})."]}
        )
