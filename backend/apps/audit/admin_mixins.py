"""QA audit H3: Django admin bypassed every rule apps.audit.mixins'
AuditedModelViewSet enforces for the same data via the API - hard
deletes (cascading to dependent rows) with no audit row at all, and
edits that never reached the audit log either. This mirrors that same
mixin's behaviour for ModelAdmin instead of ModelViewSet: archive
(is_active=False) instead of hard delete, and every create/update/
archive wrapped in the same atomic-transaction-plus-audit-log pattern
H1 established for the API.

Usage: `class BrandAdmin(AuditedModelAdmin, admin.ModelAdmin): ...` on a
model with an `is_active` BooleanField. `resource_type` is derived
automatically from the model (`app_label.ModelName`, matching the
strings AuditedModelViewSet's own subclasses already use - e.g.
"vehicles.VehicleModel") so it stays consistent without being
redeclared per admin class.

Brand/VehicleModel admins override archive_one/unarchive_one/
cascade_active_change to cascade to their dependants - see
apps.vehicles.archiving.
"""

from django.contrib import admin, messages
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils.translation import ngettext

from .models import AuditActionCategory
from .services import write_audit_log


class NoHardDeleteAdminMixin:
    """Run 3 fix batch 4 (F-32): records that other records, the audit trail or a
    user's own history point at (training runs, export jobs, profiles, saved
    comparisons, users, revoked tokens) are never hard-deleted from Django admin.
    No delete permission means no delete page (403) and, because Django filters
    actions by permission, no "Delete selected" action either."""

    def has_delete_permission(self, request, obj=None):
        return False


class AuditedModelAdmin(admin.ModelAdmin):
    actions = ["archive_selected", "unarchive_selected"]

    def get_resource_type(self):
        meta = self.model._meta
        return f"{meta.app_label}.{meta.object_name}"

    def has_delete_permission(self, request, obj=None):
        # Hard delete is never offered - archive (is_active=False) is the
        # only way to retire a row, same as the API (prevents orphaned
        # foreign keys on existing saved comparisons, and keeps every
        # removal audited).
        return False

    def save_model(self, request, obj, form, change):
        before = None
        active_changed = change and "is_active" in form.changed_data
        if change:
            before = model_to_dict(self.model.objects.get(pk=obj.pk))
        if active_changed and hasattr(obj, "archived_by_parent"):
            # Archived/reactivated directly by an admin - no later cascade
            # restore of its parent may revive it.
            obj.archived_by_parent = False
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            write_audit_log(
                actor=request.user,
                request=request,
                action=AuditActionCategory.UPDATE if change else AuditActionCategory.CREATE,
                resource_type=self.get_resource_type(),
                resource_id=obj.pk,
                before=before,
                after=model_to_dict(obj),
            )
            if active_changed:
                self.cascade_active_change(request, obj)

    def cascade_active_change(self, request, obj):
        """Hook: is_active was just toggled on the edit form (and saved +
        audited above). No-op unless the model has dependants to cascade to."""

    def archive_one(self, request, instance):
        self._set_active(request, instance, False, AuditActionCategory.ARCHIVE)

    def unarchive_one(self, request, instance):
        self._set_active(request, instance, True, AuditActionCategory.UPDATE)

    def _set_active(self, request, instance, is_active, action):
        before = model_to_dict(instance)
        with transaction.atomic():
            instance.is_active = is_active
            update_fields = ["is_active"]
            if hasattr(instance, "archived_by_parent"):
                instance.archived_by_parent = False
                update_fields.append("archived_by_parent")
            instance.save(update_fields=update_fields)
            write_audit_log(
                actor=request.user,
                request=request,
                action=action,
                resource_type=self.get_resource_type(),
                resource_id=instance.pk,
                before=before,
                after=model_to_dict(instance),
            )

    @admin.action(description="Archive selected (soft delete)")
    def archive_selected(self, request, queryset):
        archived_count = 0
        for instance in queryset:
            if not instance.is_active:
                continue
            self.archive_one(request, instance)
            archived_count += 1

        if archived_count:
            self.message_user(
                request,
                ngettext(
                    "%d record was archived.", "%d records were archived.", archived_count
                )
                % archived_count,
                messages.SUCCESS,
            )
        else:
            self.message_user(request, "The selected records were already archived.", messages.INFO)

    @admin.action(description="Un-archive selected")
    def unarchive_selected(self, request, queryset):
        """QA audit M18: there was previously no way to undo an
        accidental archive anywhere in the app - this is that path for
        Django admin (apps.audit.mixins.AuditedModelViewSet.unarchive is
        the matching API action).
        """
        unarchived_count = 0
        for instance in queryset:
            if instance.is_active:
                continue
            self.unarchive_one(request, instance)
            unarchived_count += 1

        if unarchived_count:
            self.message_user(
                request,
                ngettext(
                    "%d record was un-archived.", "%d records were un-archived.", unarchived_count
                )
                % unarchived_count,
                messages.SUCCESS,
            )
        else:
            self.message_user(request, "The selected records were already active.", messages.INFO)
