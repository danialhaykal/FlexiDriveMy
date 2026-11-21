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

from .inference import FORECAST_SOURCE_ML, FORECAST_SOURCE_UNAVAILABLE, FORECAST_SOURCE_UNSUPPORTED

TENURE_RANGE_MESSAGE = f"Tenure must be between {MIN_TENURE_MONTHS} and {MAX_TENURE_MONTHS} months."


class TCORequestSerializer(serializers.Serializer):
    """UC006 main-flow inputs, mirroring F005's ComparisonRequestSerializer."""

    # select_related("brand"): build_tco_report() always accesses
    # vehicle.brand - avoids an N+1 query per request (see F005's
    # ComparisonRequestSerializer, where this was originally found under load testing).
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


# --- Output --------------------------------------------------------------
# Same reasoning as apps.comparisons.serializers: routing Decimal values
# through DecimalField.to_representation() keeps currency a quoted string
# on the wire instead of falling through to DRF's float() fallback.


class MonthlyForecastEntrySerializer(serializers.Serializer):
    month = serializers.IntegerField()
    predicted_resale_value = serializers.DecimalField(max_digits=12, decimal_places=2)
    hp_outstanding_balance = serializers.DecimalField(max_digits=12, decimal_places=2)


class ResaleValueExplanationSerializer(serializers.Serializer):
    """F012's per-feature breakdown of one resale-value prediction, as the
    buyer reads it: apps.depreciation.explanation.round_explanation has already
    rounded every amount to whole sen so the parts add up exactly to the
    predicted value.

    Run 3 fix batch 5 (F-03): sent as 2-dp strings like every other money field
    in this response (they were JSON floats). Each value converts through its
    own 2-dp text, so the exact sum is unchanged. Saved snapshots written before
    this hold numbers; the screen and the PDF accept both."""

    base_value = serializers.DecimalField(max_digits=14, decimal_places=2)
    contributions = serializers.DictField(child=serializers.DecimalField(max_digits=14, decimal_places=2))
    predicted_value = serializers.DecimalField(max_digits=14, decimal_places=2)


class RiskRadarPathwaySerializer(serializers.Serializer):
    """Batch 6C - the same three UNWEIGHTED per-pathway scores UC007's
    suitability scoring computes (apps.scoring.formulas), reused here for
    UC006's 3-axis risk radar - see apps.depreciation.services.
    _build_risk_radar."""

    upfront_cash_preservation = serializers.DecimalField(max_digits=5, decimal_places=4)
    maintenance_protection = serializers.DecimalField(max_digits=5, decimal_places=4)
    ownership_equity = serializers.DecimalField(max_digits=5, decimal_places=4)


class CumulativeCashFlowEntrySerializer(serializers.Serializer):
    month = serializers.IntegerField()
    cumulative_cash_outflow = serializers.DecimalField(max_digits=14, decimal_places=2)


class EarlySettlementSerializer(serializers.Serializer):
    """Settling the Hire Purchase loan early: the reducing-balance amount to
    settle (no penalty under the Hire-Purchase (Amendment) Act 2026)."""

    method = serializers.ChoiceField(choices=["reducing_balance"])
    after_12_months = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    at_half_term = serializers.DecimalField(max_digits=12, decimal_places=2)
    half_term_month = serializers.IntegerField()
    penalty = serializers.ChoiceField(choices=["none"])


class ContractChecklistSerializer(serializers.Serializer):
    """Batch 6C - sourced from apps.policy.models.ContractPenaltyRule: the
    vehicle's brand rule, else the single default rule (audit batch 4).

    Two early exits (run 1): settling the HP loan early (`early_settlement`,
    reducing balance, no penalty) and returning a subscription car early
    (N months of the subscription fee, `subscription_early_return_fee`, null
    when Subscription isn't available for this request). Every ringgit figure
    is computed at response time, never stored. early_termination_amount (N
    months of the HP instalment) is no longer sent; saved snapshots that have
    it still render. Wear and tear is checklist text only, not a cost."""

    excess_mileage_charge_per_km = serializers.DecimalField(max_digits=6, decimal_places=2)
    early_settlement = EarlySettlementSerializer()
    subscription_early_return_months = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    subscription_early_return_fee = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    # Kept for older clients - the same months, now meaning months of the subscription fee.
    early_termination_months = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    wear_tear_tolerance_description = serializers.CharField()
    # "brand" | "default": which rule applied.
    rule_source = serializers.ChoiceField(choices=["brand", "default"])
    # A brand rule may leave its months empty, inheriting the default's.
    early_termination_months_source = serializers.ChoiceField(choices=["brand", "default"], allow_null=True)


class RiskAlertSerializer(serializers.Serializer):
    code = serializers.CharField()
    severity = serializers.ChoiceField(choices=["warning", "info"])
    message = serializers.CharField()


def _money(**kwargs):
    return serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True, **kwargs)


class OperatingCostPolicySerializer(serializers.Serializer):
    # FX-3: the yearly maintenance cap of the rate row the engine used
    # (null = no cap), so the running-costs sentence can name it.
    maintenance_cap_annual = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)


class PathwayTcoEntrySerializer(serializers.Serializer):
    """Run 1 fix batch 4: one pathway's TCO (see build_pathway_tco). Every
    money field is null when the pathway isn't available for this request."""

    available = serializers.BooleanField()
    unavailable_reason = serializers.CharField(allow_null=True)
    horizon_months = serializers.IntegerField()
    upfront_cash = _money()
    payments_total = _money()
    balloon_paid = _money()
    running_costs_total = _money()
    resale_credit = _money()
    settlement_debit = _money()
    deposit_refund = _money()
    gross = _money()
    net = _money()
    amount_back = _money()  # gross - net: "what you get back"
    net_per_month = _money()


class GfvPathwayTcoEntrySerializer(PathwayTcoEntrySerializer):
    # max(0, balloon - predicted resale at month t): what the buy-back
    # guarantee is worth on this forecast. Null when GFV is unavailable.
    gfv_guarantee_value = _money()


class PathwayTcoSerializer(serializers.Serializer):
    hire_purchase = PathwayTcoEntrySerializer()
    gfv_retain = GfvPathwayTcoEntrySerializer()
    gfv_return = GfvPathwayTcoEntrySerializer()
    subscription = PathwayTcoEntrySerializer()


class TCOResultSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField()
    tenure_months = serializers.IntegerField()
    mileage_band = serializers.CharField()
    downpayment = serializers.DecimalField(max_digits=12, decimal_places=2)
    hp_monthly = serializers.DecimalField(max_digits=12, decimal_places=2)
    model_degraded = serializers.BooleanField()
    degraded_reason = serializers.CharField(allow_null=True)
    # Run 2 fix batch 3 (A14, X1): where the resale curve comes from -
    # "ml_model", "estimated_curve_unsupported" (a car the model can't cover:
    # electric, no engine size, body type not mapped) or "model_unavailable"
    # (nothing usable is serving). model_degraded stays true for both estimated
    # curves. Optional: a snapshot saved before it existed has none.
    forecast_source = serializers.ChoiceField(
        choices=[FORECAST_SOURCE_ML, FORECAST_SOURCE_UNSUPPORTED, FORECAST_SOURCE_UNAVAILABLE], required=False
    )
    monthly_forecast = MonthlyForecastEntrySerializer(many=True)
    tco_gross = serializers.DecimalField(max_digits=14, decimal_places=2)
    tco_net = serializers.DecimalField(max_digits=14, decimal_places=2)
    # Run 1 fix batch 4: TCO for every pathway (tco_gross / tco_net above stay
    # the Hire Purchase figures). Optional so an older snapshot still validates.
    pathway_tco = PathwayTcoSerializer(required=False)
    road_tax_annual = serializers.DecimalField(max_digits=12, decimal_places=2)
    insurance_annual = serializers.DecimalField(max_digits=12, decimal_places=2)
    maintenance_annual = serializers.DecimalField(max_digits=12, decimal_places=2)
    # Run 1 fix batch 3: the No-Claim Discount behind insurance_annual, from
    # the user's own profile ("0.00" = before NCD). Optional for old snapshots.
    ncd_percent = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    # How each of the three figures above was derived ({"road_tax": ...,
    # "insurance": ..., "maintenance": ...}) - display text from
    # apps.policy.operating_costs, shown muted under each cost.
    operating_cost_basis = serializers.DictField(child=serializers.CharField())
    # FX-3: optional so an older snapshot without it still validates.
    operating_cost_policy = OperatingCostPolicySerializer(required=False)
    negative_equity_crossover_month = serializers.IntegerField(allow_null=True)
    negative_equity_shortfall_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    # Null whenever model_degraded is true or the explanation itself
    # failed (see build_tco_report / explain_resale_prediction) - same
    # graceful-degradation pattern as degraded_reason.
    resale_value_explanation = ResaleValueExplanationSerializer(allow_null=True)
    # Batch 6C / UC006 steps 7-9 additions below - see
    # apps.depreciation.services.build_tco_report's own docstring.
    risk_radar = serializers.DictField(child=RiskRadarPathwaySerializer())
    radar_unavailable = serializers.DictField(child=serializers.CharField())
    cumulative_cash_flow = CumulativeCashFlowEntrySerializer(many=True)
    contract_checklist = ContractChecklistSerializer(allow_null=True)
    risk_alerts = RiskAlertSerializer(many=True)
    # Run 2 fix batch 2 (E3, C6, E5): server-built sentences saying what the
    # GFV residual and the predicted market value are (resale_views_note) and
    # what the predicted curve is (resale_forecast_note) - see
    # apps.depreciation.resale_notes. Null when they don't apply; absent from a
    # snapshot saved before they existed, so both are optional.
    resale_views_note = serializers.CharField(allow_null=True, required=False)
    resale_forecast_note = serializers.CharField(allow_null=True, required=False)
    # Run 3 fix batch 6: "The forecast is capped at the mileage the model has seen." -
    # only when the cap changed the machine-learning curve; null otherwise, absent
    # from older snapshots.
    forecast_cap_note = serializers.CharField(allow_null=True, required=False)


# --- Sprint 12: Total-Loss Exposure Sandbox ---------------------------------


def loss_month_range_message(tenure_months):
    return f"Choose a month from 1 to {tenure_months}."


class TotalLossSandboxRequestSerializer(serializers.Serializer):
    """Mirrors TCORequestSerializer's inputs exactly, plus loss_month and
    excess_amount - the two self-declared "what if" inputs this sandbox
    adds."""

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
    # Run 1 fix batch 5 (X3): month 0 (before the first instalment) is refused
    # in validate() below with the tenure in the message.
    loss_month = serializers.IntegerField()
    # Optional: omitting it means "no policy excess declared", never a
    # validation error - defaults to 0 rather than requiring every caller
    # to pass it explicitly (same pattern as Sprint 11's
    # existing_monthly_commitments).
    excess_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, default=Decimal("0")
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
        # Run 2 fix batch 3: month 0 and a month past the tenure get the same sentence.
        if not 1 <= attrs["loss_month"] <= attrs["tenure_months"]:
            raise serializers.ValidationError(
                {"loss_month": loss_month_range_message(attrs["tenure_months"])}
            )
        return attrs


class TotalLossSandboxPathwaySerializer(serializers.Serializer):
    # QA audit L8: null for Subscription - a subscriber has no ownership
    # stake, so there's no insurance claim on the vehicle that's theirs
    # to receive (consistent with its already-null outstanding_balance/
    # net_position below, not the same computed figure HP/GFV get).
    insurance_payout = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    # Null for Subscription, which has no ownership stake - genuinely not
    # applicable, not computed as zero (see build_total_loss_sandbox).
    outstanding_balance = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    net_position = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    has_ownership_exposure = serializers.BooleanField()


class TotalLossSandboxResultSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField()
    tenure_months = serializers.IntegerField()
    mileage_band = serializers.CharField()
    downpayment = serializers.DecimalField(max_digits=12, decimal_places=2)
    loss_month = serializers.IntegerField()
    excess_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    model_degraded = serializers.BooleanField()
    degraded_reason = serializers.CharField(allow_null=True)
    # QA audit L8: true when loss_month > 60 - the resale value used is
    # reused from month 60 (predict_resale_curve's own horizon), not a
    # genuine prediction for the actual loss month. See
    # build_total_loss_sandbox's own docstring for why.
    resale_value_is_plateaued = serializers.BooleanField()
    # Null as a whole pathway when its own config (interest rate /
    # residual ratio) is missing - see `unavailable` for why. Subscription
    # is never null itself (it has no such dependency), only its own
    # outstanding_balance/net_position fields are.
    hire_purchase = TotalLossSandboxPathwaySerializer(allow_null=True)
    gfv_leasing = TotalLossSandboxPathwaySerializer(allow_null=True)
    subscription = TotalLossSandboxPathwaySerializer(allow_null=True)
    # HP/GFV only - missing interest rate or residual ratio (Subscription
    # has no such dependency, so it's never listed here).
    unavailable = serializers.DictField(child=serializers.CharField())
