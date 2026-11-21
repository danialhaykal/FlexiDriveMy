from django.contrib import admin

from apps.audit.admin_mixins import AuditedModelAdmin

from .admin_forms import PlainConstraintMessagesForm, shortest_longer_than_longest_error
from .effective_dates import EffectiveFromNotFutureForm
from .models import (
    ContractPenaltyRule,
    EvRoadTaxGroup,
    InterestRate,
    MCDACriteriaWeight,
    OperatingCostBand,
    OperatingCostRate,
    ResidualAdjustment,
    ResidualBaseline,
    ResidualValueMatrix,
    RoadTaxCcBand,
    SubscriptionPlan,
    SubscriptionPolicy,
)


# Run 3 fix batch 5 (F-14): every policy form words a refused database constraint plainly
# (apps/policy/admin_forms.py); the tables with effective_from get it through EffectiveFromNotFutureForm.


class SubscriptionPolicyAdminForm(EffectiveFromNotFutureForm):
    def clean(self):
        cleaned = super().clean()
        error = shortest_longer_than_longest_error(cleaned)
        if error is not None:
            raise error
        return cleaned


@admin.register(InterestRate)
class InterestRateAdmin(AuditedModelAdmin, admin.ModelAdmin):
    form = PlainConstraintMessagesForm
    list_display = ["brand", "rate_percent", "is_active"]
    list_filter = ["brand", "is_active"]


@admin.register(ResidualValueMatrix)
class ResidualValueMatrixAdmin(AuditedModelAdmin, admin.ModelAdmin):
    form = PlainConstraintMessagesForm
    list_display = ["brand", "tenure_months", "mileage_band", "residual_value_ratio", "is_active"]
    list_filter = ["brand", "mileage_band", "is_active"]


@admin.register(ResidualBaseline)
class ResidualBaselineAdmin(AuditedModelAdmin, admin.ModelAdmin):
    """Share of price retained by tenure x mileage band (planning estimate)."""

    form = EffectiveFromNotFutureForm  # Run 3 fix batch 4 (F-12): no future-dated rows
    list_display = ["tenure_months", "mileage_band", "ratio", "effective_from", "is_active"]
    list_filter = ["mileage_band", "is_active"]


@admin.register(ResidualAdjustment)
class ResidualAdjustmentAdmin(AuditedModelAdmin, admin.ModelAdmin):
    """Brand OR powertrain shift to the baseline, in ratio points (0.06 = +6 points)."""

    form = EffectiveFromNotFutureForm
    list_display = ["brand", "powertrain", "delta_points", "effective_from", "is_active"]
    list_filter = ["is_active"]


@admin.register(ContractPenaltyRule)
class ContractPenaltyRuleAdmin(AuditedModelAdmin, admin.ModelAdmin):
    """Contract terms per brand (no brand = the default rule). The form runs the
    model's validators, so a ringgit fee amount typed into the wear-and-tear
    text is refused here exactly as it is by the API."""

    form = PlainConstraintMessagesForm
    list_display = ["brand", "excess_mileage_charge_per_km", "early_termination_months", "is_active"]
    list_filter = ["is_active"]
    exclude = ["early_termination_fee"]  # deprecated, not read


@admin.register(MCDACriteriaWeight)
class MCDACriteriaWeightAdmin(AuditedModelAdmin, admin.ModelAdmin):
    list_display = ["criterion", "default_weight", "is_active"]


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(AuditedModelAdmin, admin.ModelAdmin):
    # The three annual cost columns are deprecated (derived by
    # apps.policy.operating_costs) - not listed, not asked for.
    form = PlainConstraintMessagesForm
    list_display = ["vehicle", "fee_monthly", "is_active"]
    list_filter = ["is_active"]
    exclude = ["insurance_annual", "road_tax_annual", "maintenance_annual"]


@admin.register(SubscriptionPolicy)
class SubscriptionPolicyAdmin(AuditedModelAdmin, admin.ModelAdmin):
    """The planning assumptions every Subscription fee is estimated from
    (tenure range, funding rate, margin, deposit, very-high-band km allowance)."""

    form = SubscriptionPolicyAdminForm
    list_display = [
        "min_tenure_months", "max_tenure_months", "funding_rate_percent", "margin_percent",
        "deposit_months", "low_km_cap", "standard_km_cap", "high_km_cap", "very_high_km_cap", "effective_from",
        "is_active",
    ]
    list_filter = ["is_active"]


@admin.register(OperatingCostBand)
class OperatingCostBandAdmin(AuditedModelAdmin, admin.ModelAdmin):
    """DEPRECATED - kept so the old rows stay visible for the audit trail;
    nothing reads them. Run 1 fix batch 5 (D4): read-only - no add, edit,
    archive or delete (the model's verbose name carries the "deprecated - not
    used" title)."""

    list_display = [
        "min_engine_capacity_kw",
        "max_engine_capacity_kw",
        "road_tax_annual",
        "insurance_annual",
        "maintenance_annual",
        "is_active",
    ]
    list_filter = ["is_active"]
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RoadTaxCcBand)
class RoadTaxCcBandAdmin(AuditedModelAdmin, admin.ModelAdmin):
    """JPJ private-car road tax by engine cc (every powertrain except BEV, petrol and diesel alike), one table per
    registration class (saloon / non-saloon). fuel_schedule is no longer read: the old diesel rows are archived."""

    form = EffectiveFromNotFutureForm
    list_display = [
        "vehicle_class", "min_cc", "max_cc", "base_amount", "threshold_cc", "per_cc_rate", "effective_from",
        "is_active", "fuel_schedule",
    ]
    list_filter = ["vehicle_class", "is_active", "fuel_schedule"]


@admin.register(EvRoadTaxGroup)
class EvRoadTaxGroupAdmin(AuditedModelAdmin, admin.ModelAdmin):
    """JPJ battery-electric road tax by motor kW (effective 1 Jan 2026)."""

    form = EffectiveFromNotFutureForm
    list_display = [
        "label", "min_kw", "max_kw", "base_amount", "base_until_kw", "increment_per_10kw", "effective_from", "is_active",
    ]
    list_filter = ["is_active"]


@admin.register(OperatingCostRate)
class OperatingCostRateAdmin(AuditedModelAdmin, admin.ModelAdmin):
    """Insurance and maintenance percentage estimates, one per powertrain."""

    form = EffectiveFromNotFutureForm
    list_display = [
        "powertrain", "insurance_rate_percent", "maintenance_rate_percent", "maintenance_floor_annual",
        "maintenance_cap_annual", "effective_from", "is_active",
    ]
    list_filter = ["is_active"]
