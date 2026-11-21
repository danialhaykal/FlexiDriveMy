"""Cascade archive/restore for brands and vehicles - the ONE place this
logic lives. Every entry point calls it: the API's destroy()/unarchive()
for Brand and VehicleModel, Django admin's archive/un-archive actions, and
admin's save_model when is_active is toggled on the edit form.

  archive a brand    -> also its active vehicles, interest rate, residual
                        value rows, contract penalty rule, and every active
                        subscription plan of its vehicles
  archive a vehicle  -> also its active subscription plan(s)
  restore either     -> only the rows archived BECAUSE of it come back

Nothing is ever hard-deleted. A cascaded row gets is_active=False AND
archived_by_parent=True; a restore only revives archived_by_parent=True
rows, so anything archived on its own beforehand stays archived. Every
row changed gets its own audit row (same actor/request) inside the
caller's single transaction, with the cascade named in the `after`
snapshot ({"cascade": "Brand #10 archived"}) - AuditLog has no dedicated
field for it and its schema is append-only.

Uniqueness guard: if restoring a row would give its key a second ACTIVE
row (one interest rate / penalty rule per brand, one residual value row
per brand+tenure+band, one plan per vehicle) - because the admin created a
replacement in the meantime - it's left archived, its flag cleared (the
admin's replacement superseded it, so no later restore may revive it),
and it's reported as skipped. VehicleModel's own uniqueness constraint is
unconditional, so a vehicle restore can never clash.
"""

from dataclasses import dataclass, field

from django.db import transaction

from apps.audit.models import AuditActionCategory
from apps.audit.services import write_audit_log
from apps.policy.models import ContractPenaltyRule, InterestRate, ResidualValueMatrix, SubscriptionPlan
from apps.policy.serializers import (
    ContractPenaltyRuleSerializer,
    InterestRateSerializer,
    ResidualValueMatrixSerializer,
    SubscriptionPlanSerializer,
)

from .models import Brand, VehicleModel
from .serializers import BrandSerializer, VehicleModelSerializer

# model -> (impact/result group name, audit resource_type, serializer used
# for audit snapshots - the same shapes the API's own audit rows use)
_REGISTRY = {
    Brand: ("brands", "vehicles.Brand", BrandSerializer),
    VehicleModel: ("vehicles", "vehicles.VehicleModel", VehicleModelSerializer),
    InterestRate: ("interest_rates", "policy.InterestRate", InterestRateSerializer),
    ResidualValueMatrix: ("residual_value_rows", "policy.ResidualValueMatrix", ResidualValueMatrixSerializer),
    ContractPenaltyRule: ("penalty_rules", "policy.ContractPenaltyRule", ContractPenaltyRuleSerializer),
    SubscriptionPlan: ("subscription_plans", "policy.SubscriptionPlan", SubscriptionPlanSerializer),
}
BRAND_GROUPS = ["vehicles", "interest_rates", "residual_value_rows", "penalty_rules", "subscription_plans"]
VEHICLE_GROUPS = ["subscription_plans"]

# The "one ACTIVE row per ..." key of each guarded model.
_UNIQUE_KEY = {
    InterestRate: ("brand_id",),
    ContractPenaltyRule: ("brand_id",),
    ResidualValueMatrix: ("brand_id", "tenure_months", "mileage_band"),
    SubscriptionPlan: ("vehicle_id",),
}


@dataclass
class CascadePlan:
    """Rows a cascade would change (or did change), plus the rows a restore
    skipped. Doubles as the read-only archive-impact preview."""

    action: str  # "archive" | "restore"
    groups: list
    rows: list = field(default_factory=list)
    skipped: list = field(default_factory=list)  # [(row, reason)]

    def as_dict(self):
        counts = {group: 0 for group in self.groups}
        for row in self.rows:
            counts[_REGISTRY[type(row)][0]] += 1
        return {
            "action": self.action,
            "counts": counts,
            "skipped": [
                {
                    "resource_type": _REGISTRY[type(row)][1],
                    "id": row.pk,
                    "label": str(row),
                    "reason": reason,
                }
                for row, reason in self.skipped
            ],
        }


# --------------------------------------------------------------- planning


def plan_brand_archive(brand):
    rows = list(VehicleModel.objects.filter(brand=brand, is_active=True).select_related("brand"))
    for model in (InterestRate, ResidualValueMatrix, ContractPenaltyRule):
        rows += list(model.objects.filter(brand=brand, is_active=True).select_related("brand"))
    rows += list(
        SubscriptionPlan.objects.filter(vehicle__brand=brand, is_active=True).select_related("vehicle__brand")
    )
    return CascadePlan("archive", BRAND_GROUPS, rows)


def plan_vehicle_archive(vehicle):
    rows = list(SubscriptionPlan.objects.filter(vehicle=vehicle, is_active=True).select_related("vehicle__brand"))
    return CascadePlan("archive", VEHICLE_GROUPS, rows)


def plan_brand_restore(brand):
    plan = CascadePlan("restore", BRAND_GROUPS)
    vehicles = list(VehicleModel.objects.filter(brand=brand, is_active=False, archived_by_parent=True))
    plan.rows += vehicles
    # A plan only comes back with an ACTIVE vehicle - one whose vehicle stays
    # archived (archived on its own) waits for that vehicle's own restore.
    active_vehicle_ids = set(
        VehicleModel.objects.filter(brand=brand, is_active=True).values_list("pk", flat=True)
    ) | {v.pk for v in vehicles}
    for model in (InterestRate, ResidualValueMatrix, ContractPenaltyRule):
        _plan_guarded_restore(plan, model.objects.filter(brand=brand).select_related("brand"))
    _plan_guarded_restore(
        plan,
        SubscriptionPlan.objects.filter(vehicle__brand=brand, vehicle_id__in=active_vehicle_ids).select_related(
            "vehicle__brand"
        ),
    )
    return plan


def plan_vehicle_restore(vehicle):
    plan = CascadePlan("restore", VEHICLE_GROUPS)
    _plan_guarded_restore(plan, SubscriptionPlan.objects.filter(vehicle=vehicle).select_related("vehicle__brand"))
    return plan


def _plan_guarded_restore(plan, queryset):
    claimed = set()
    for row in queryset.filter(is_active=False, archived_by_parent=True).order_by("-updated_at", "-pk"):
        model = type(row)
        key_fields = _UNIQUE_KEY[model]
        key = tuple(getattr(row, name) for name in key_fields)
        clash = model.objects.filter(is_active=True, **dict(zip(key_fields, key))).first()
        if clash is not None:
            plan.skipped.append((row, f"{clash} (#{clash.pk}) is already active"))
        elif key in claimed:
            plan.skipped.append((row, "another archived row with the same key is being restored"))
        else:
            claimed.add(key)
            plan.rows.append(row)


# --------------------------------------------------------------- applying


def _snapshot(row):
    return dict(_REGISTRY[type(row)][2](row).data)


def _set_state(row, *, active, by_parent, action, actor, request, cascade=None):
    before = _snapshot(row)
    row.is_active = active
    update_fields = ["is_active", "updated_at"]
    if hasattr(row, "archived_by_parent"):
        row.archived_by_parent = by_parent
        update_fields.append("archived_by_parent")
    row.save(update_fields=update_fields)
    after = _snapshot(row)
    if cascade:
        after["cascade"] = cascade
    write_audit_log(
        actor=actor,
        request=request,
        action=action,
        resource_type=_REGISTRY[type(row)][1],
        resource_id=row.pk,
        before=before,
        after=after,
    )


def _apply(plan, *, parent_label, actor, request):
    verb = "archived" if plan.action == "archive" else "reactivated"
    note = f"{parent_label} {verb}"
    for row in plan.rows:
        if plan.action == "archive":
            _set_state(row, active=False, by_parent=True, action=AuditActionCategory.ARCHIVE,
                       actor=actor, request=request, cascade=note)
        else:
            _set_state(row, active=True, by_parent=False, action=AuditActionCategory.UPDATE,
                       actor=actor, request=request, cascade=note)
    for row, reason in plan.skipped:
        # Stays archived; only the flag is cleared (see module docstring).
        _set_state(row, active=False, by_parent=False, action=AuditActionCategory.UPDATE,
                   actor=actor, request=request, cascade=f"{note} - not restored: {reason}")
    return plan


def _brand_label(brand):
    return f"Brand #{brand.pk}"


def _vehicle_label(vehicle):
    return f"Vehicle #{vehicle.pk}"


# --- children only (the parent row was already saved by the caller, e.g.
# Django admin's edit form, which writes the parent's own audit row)


def archive_brand_children(brand, *, actor, request):
    return _apply(plan_brand_archive(brand), parent_label=_brand_label(brand), actor=actor, request=request)


def restore_brand_children(brand, *, actor, request):
    return _apply(plan_brand_restore(brand), parent_label=_brand_label(brand), actor=actor, request=request)


def archive_vehicle_children(vehicle, *, actor, request):
    return _apply(plan_vehicle_archive(vehicle), parent_label=_vehicle_label(vehicle), actor=actor, request=request)


def restore_vehicle_children(vehicle, *, actor, request):
    return _apply(plan_vehicle_restore(vehicle), parent_label=_vehicle_label(vehicle), actor=actor, request=request)


# --- parent + children, in one transaction. A no-op (empty plan) when the
# parent is already in the requested state, same idempotency as the API's
# existing destroy()/unarchive().


def archive_brand(brand, *, actor, request):
    with transaction.atomic():
        if not brand.is_active:
            return CascadePlan("archive", BRAND_GROUPS)
        _set_state(brand, active=False, by_parent=False, action=AuditActionCategory.ARCHIVE,
                   actor=actor, request=request)
        return archive_brand_children(brand, actor=actor, request=request)


def restore_brand(brand, *, actor, request):
    with transaction.atomic():
        if brand.is_active:
            return CascadePlan("restore", BRAND_GROUPS)
        _set_state(brand, active=True, by_parent=False, action=AuditActionCategory.UPDATE,
                   actor=actor, request=request)
        return restore_brand_children(brand, actor=actor, request=request)


def archive_vehicle(vehicle, *, actor, request):
    """Archiving a vehicle on its own also clears its archived_by_parent, so
    a later brand restore never revives what the admin handled directly."""
    with transaction.atomic():
        if not vehicle.is_active:
            return CascadePlan("archive", VEHICLE_GROUPS)
        _set_state(vehicle, active=False, by_parent=False, action=AuditActionCategory.ARCHIVE,
                   actor=actor, request=request)
        return archive_vehicle_children(vehicle, actor=actor, request=request)


def restore_vehicle(vehicle, *, actor, request):
    with transaction.atomic():
        if vehicle.is_active:
            return CascadePlan("restore", VEHICLE_GROUPS)
        _set_state(vehicle, active=True, by_parent=False, action=AuditActionCategory.UPDATE,
                   actor=actor, request=request)
        return restore_vehicle_children(vehicle, actor=actor, request=request)


def impact(obj):
    """Read-only preview of what archiving (if active) or reactivating (if
    archived) `obj` would change - nothing is written."""
    if isinstance(obj, Brand):
        plan = plan_brand_archive(obj) if obj.is_active else plan_brand_restore(obj)
    else:
        plan = plan_vehicle_archive(obj) if obj.is_active else plan_vehicle_restore(obj)
    return plan.as_dict()
