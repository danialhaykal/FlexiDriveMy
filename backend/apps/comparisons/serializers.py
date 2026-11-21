from decimal import Decimal

from rest_framework import serializers

from apps.common.constants import (
    MAX_TENURE_MONTHS,
    MIN_TENURE_MONTHS,
    POSITIVE_AMOUNT_ERROR_MESSAGES,
    minimum_downpayment_for,
    minimum_downpayment_message,
)
from apps.policy.models import MileageBand
from apps.vehicles.models import VehicleModel

TENURE_RANGE_MESSAGE = f"Tenure must be between {MIN_TENURE_MONTHS} and {MAX_TENURE_MONTHS} months."


class ComparisonRequestSerializer(serializers.Serializer):
    """UC005 main-flow inputs: a target vehicle, tenure, annual mileage
    cap, and the user's chosen downpayment."""

    # select_related("brand"): build_comparison() always accesses
    # vehicle.brand - without this, that's a second (N+1) query per
    # request, found under load testing (see loadtest/README.md).
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

    def validate(self, attrs):
        vehicle = attrs["vehicle"]
        downpayment = attrs["downpayment"]
        if downpayment >= vehicle.msrp:
            raise serializers.ValidationError(
                {"downpayment": "Downpayment must be less than the vehicle's price."}
            )
        if downpayment < minimum_downpayment_for(vehicle.msrp):
            raise serializers.ValidationError({"downpayment": minimum_downpayment_message(vehicle.msrp)})
        return attrs


# --- Output ------------------------------------------------------------
#
# build_comparison() returns plain dicts of Decimal for calculation purity
# and easy testing, but a raw Decimal handed straight to Response() falls
# through DRF's JSONRenderer to a float() fallback - exactly the float-
# precision loss the project spec's architecture rule forbids for money. Routing
# the result through DecimalField.to_representation() (via these
# serializers) is what keeps every currency value a string on the wire.


class PathwaySerializer(serializers.Serializer):
    monthly_instalment = serializers.DecimalField(max_digits=12, decimal_places=2)
    upfront_cash = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_contract_outlay = serializers.DecimalField(max_digits=12, decimal_places=2)


class HirePurchasePathwaySerializer(PathwaySerializer):
    # The dealer's FLAT rate (what the instalment is built from), kept as is.
    interest_rate_percent = serializers.DecimalField(max_digits=6, decimal_places=4)
    # The same instalments as an effective (reducing-balance) rate, derived
    # by apps.comparisons.formulas.effective_annual_rate. Null if no
    # positive rate exists; additive, so older snapshots simply lack it.
    effective_rate_percent = serializers.DecimalField(max_digits=8, decimal_places=4, allow_null=True, required=False)


class GFVLeasingPathwaySerializer(PathwaySerializer):
    balloon_payment = serializers.DecimalField(max_digits=12, decimal_places=2)
    residual_value_ratio = serializers.DecimalField(max_digits=6, decimal_places=4)
    # Where that ratio came from ("Admin override for ..." or "Estimate: ...",
    # apps.policy.residuals). Optional so saved snapshots without it still
    # validate.
    residual_basis = serializers.CharField(required=False)
    effective_rate_percent = serializers.DecimalField(max_digits=8, decimal_places=4, allow_null=True, required=False)
    # Run 1 fix batch 4: the end-of-term choice and why the total equals Hire
    # Purchase's. Optional so older snapshots still validate.
    end_of_term_note = serializers.CharField(required=False)
    same_total_note = serializers.CharField(required=False)
    # Run 2 fix batch 2: what the residual is (a conservative guaranteed
    # buy-back, not a market prediction). Optional like the two above. Run 2 fix
    # batch 3: null when the car's resale curve is not a machine-learning forecast
    # (there is no "expected market value on the TCO tab" to compare it with).
    resale_note = serializers.CharField(required=False, allow_null=True)


class SubscriptionPathwaySerializer(PathwaySerializer):
    # QA audit H8: monthly_instalment (inherited above) is now the real,
    # gross fee the subscriber is billed - this is the separate economic
    # comparison figure (the project spec's NetCost formula), informational only,
    # never used for DSR or as a headline instalment.
    # Audit batch 2: null when the vehicle can't be costed by the
    # operating-cost engine (incomplete specs / no rate row) - the reason is
    # beside it; the pathway and its fee are unaffected.
    net_cost_after_bundled_benefits = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    net_cost_unavailable_reason = serializers.CharField(allow_null=True, required=False)
    # Audit batch 5: where the fee came from, the refundable deposit (it IS
    # upfront_cash, but is returned at term end so it is NOT in
    # total_contract_outlay) and what the mileage tier includes. All optional
    # so a saved scenario's frozen older snapshot still validates.
    refundable_deposit = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    fee_source = serializers.ChoiceField(choices=["quote", "estimate"], required=False)
    fee_basis = serializers.CharField(required=False)
    included_km_per_year = serializers.IntegerField(required=False)
    mileage_note = serializers.CharField(required=False)


class ComparisonResultSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField()
    tenure_months = serializers.IntegerField()
    mileage_band = serializers.CharField()
    downpayment = serializers.DecimalField(max_digits=12, decimal_places=2)
    # Run 1 fix batch 3: the No-Claim Discount (from the user's own profile)
    # behind the subscription's net-cost offset; "0.00" = before NCD.
    # Optional so a saved snapshot without it still validates.
    ncd_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    # Null when that pathway's required config is missing/inactive - see
    # build_comparison(). `unavailable` carries the specific reason for
    # whichever of these keys are null (never both null and silent).
    hire_purchase = HirePurchasePathwaySerializer(allow_null=True)
    gfv_leasing = GFVLeasingPathwaySerializer(allow_null=True)
    subscription = SubscriptionPathwaySerializer(allow_null=True)
    unavailable = serializers.DictField(child=serializers.CharField())
    # FX-3: the most a buyer can put down and still take GFV at this term
    # (price less the balloon; the figure the "exceeds" reason quotes).
    # Optional so a saved snapshot without it still validates.
    gfv_max_downpayment = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True, required=False, read_only=True
    )


# --- Arena (Sprint 10: 2-3 vehicles side by side) ---------------------------

MIN_ARENA_VEHICLES = 2
MAX_ARENA_VEHICLES = 3
ARENA_VEHICLE_COUNT_MESSAGE = (
    f"Select between {MIN_ARENA_VEHICLES} and {MAX_ARENA_VEHICLES} vehicles to compare."
)
ARENA_DUPLICATE_VEHICLE_MESSAGE = "Each vehicle can only be selected once."


class ArenaRequestSerializer(serializers.Serializer):
    """UC005 main-flow inputs, extended to 2-3 vehicles at once and one
    shared downpayment (not a per-vehicle amount - matches how a buyer
    with a fixed cash amount actually shops). Deliberately does NOT
    reject the whole request just because this shared downpayment
    happens to exceed one (cheaper) vehicle's own MSRP - that's a
    per-vehicle concern handled as a per-vehicle "ok": False entry by
    apps.comparisons.arena.build_arena, not a request-shape problem."""

    vehicles = serializers.PrimaryKeyRelatedField(
        queryset=VehicleModel.objects.select_related("brand").visible(),
        many=True,
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

    def validate_vehicles(self, vehicles):
        if not (MIN_ARENA_VEHICLES <= len(vehicles) <= MAX_ARENA_VEHICLES):
            raise serializers.ValidationError(ARENA_VEHICLE_COUNT_MESSAGE)
        vehicle_ids = [vehicle.id for vehicle in vehicles]
        if len(set(vehicle_ids)) != len(vehicle_ids):
            raise serializers.ValidationError(ARENA_DUPLICATE_VEHICLE_MESSAGE)
        return vehicles


class ArenaEntrySerializer(serializers.Serializer):
    """One vehicle's slot in the arena - either a full comparison (reusing
    ComparisonResultSerializer directly, not redefining its fields) plus
    a compact TCO summary, or an "ok": False error entry. comparison/
    tco_net/model_degraded are all null together on an error entry.

    A vehicle can also be "ok": True with a real `comparison` but a null
    `tco_net`: build_tco_report() has its own independent config
    dependencies (interest rate, operating cost band) and can fail even
    when build_comparison() fully succeeds - that shouldn't throw away a
    comparison that was already computed, so `tco_unavailable_reason`
    carries why in that case, same "keep what succeeded" principle as
    comparison's own per-pathway `unavailable` map.
    """

    vehicle_id = serializers.IntegerField()
    ok = serializers.BooleanField()
    error = serializers.CharField(allow_null=True)
    comparison = ComparisonResultSerializer(allow_null=True)
    tco_net = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    model_degraded = serializers.BooleanField(allow_null=True)
    # Run 2 fix batch 3: why the car's resale curve is an estimate, when it is
    # ("estimated_curve_unsupported" or "model_unavailable"); "ml_model" when it
    # is the machine-learning forecast; null with the TCO figures on an error entry.
    forecast_source = serializers.CharField(allow_null=True, required=False, default=None)
    tco_unavailable_reason = serializers.CharField(allow_null=True, required=False, default=None)
    # Run 3 fix batch 4 (F-21): the Status row's wording, shown as-is: "Available"
    # when at least one pathway is offered, "Not available at this downpayment"
    # when none is because the shared downpayment is below this car's minimum,
    # else "Not available". Null on an error entry (`error` says why).
    status_label = serializers.CharField(allow_null=True, required=False, default=None)


class ArenaWinnerSerializer(serializers.Serializer):
    # QA audit L10: tied_with lists EVERY vehicle_id at the winning
    # minimum (winner_id included) - a tie no longer silently picks one
    # vehicle with no indication the others matched it exactly.
    winner_id = serializers.IntegerField()
    tied_with = serializers.ListField(child=serializers.IntegerField())


class ArenaWinnersSerializer(serializers.Serializer):
    cheapest_hp = ArenaWinnerSerializer(allow_null=True)
    cheapest_gfv = ArenaWinnerSerializer(allow_null=True)
    cheapest_subscription = ArenaWinnerSerializer(allow_null=True)
    lowest_tco = ArenaWinnerSerializer(allow_null=True)


class ArenaResultSerializer(serializers.Serializer):
    results = ArenaEntrySerializer(many=True)
    winners = ArenaWinnersSerializer()
