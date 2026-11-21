from django.db import transaction
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.response import Response

from .models import AuditActionCategory
from .services import write_audit_log

EDIT_CONFLICT_MESSAGE = "This record was changed by someone else. Reload to see the latest version."


class EditConflict(APIException):
    """Run 1 fix batch 5 (G7): the row changed since the admin loaded it."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = EDIT_CONFLICT_MESSAGE
    default_code = "edit_conflict"


class AuditedModelViewSet:
    """Mixin for a ModelViewSet over a soft-deletable, admin-managed resource.

    - excludes archived (is_active=False) rows from list/retrieve unless
      ?include_archived=true is passed
    - DELETE never removes a row: it flips is_active to False (archive)
    - every create/update/archive writes an append-only AuditLog row

    Subclasses must set `resource_type` (e.g. "vehicles.VehicleModel") and
    have a model with an `is_active` BooleanField.

    QA audit H1: the record change and its audit-log write are wrapped in
    one atomic transaction below - either both commit or neither does.
    Previously the audit row was written after the record had already
    been saved, outside any transaction, so a failure writing the audit
    row (e.g. a malformed IP reaching the database as a bad `inet`
    literal) left a committed change with no audit trail at all.
    """

    resource_type = None

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("include_archived") == "true":
            return queryset
        return queryset.filter(is_active=True)

    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            write_audit_log(
                actor=self.request.user,
                request=self.request,
                action=AuditActionCategory.CREATE,
                resource_type=self.resource_type,
                resource_id=instance.pk,
                before=None,
                after=self.get_serializer(instance).data,
            )

    def _loaded_updated_at(self):
        """The `updated_at` the client loaded the row with, if it sent one
        (run 1 fix batch 5, G7). None when absent - older callers keep the
        old last-write-wins behaviour."""
        raw = self.request.data.get("updated_at") if hasattr(self.request.data, "get") else None
        if raw in (None, ""):
            return None
        parsed = parse_datetime(str(raw))
        if parsed is None:
            raise ValidationError({"updated_at": "Not a valid date and time."})
        return parsed

    def perform_update(self, serializer):
        loaded_updated_at = self._loaded_updated_at()
        before = self.get_serializer(serializer.instance).data
        with transaction.atomic():
            if loaded_updated_at is not None:
                # Locked, so two admins saving at once can't both pass the check.
                # Run 3 fix batch 4 (F-01): lock this table's row only. The
                # model's default ordering can name a NULLABLE relation
                # (ContractPenaltyRule orders by brand__name; the default rule
                # has no brand), which adds a LEFT OUTER JOIN that PostgreSQL
                # refuses to lock ("FOR UPDATE cannot be applied to the
                # nullable side of an outer join"). order_by() drops that
                # ordering, and of=("self",) keeps the lock on this row alone.
                current = (
                    type(serializer.instance).objects.select_for_update(of=("self",))
                    .filter(pk=serializer.instance.pk).order_by()
                    .values_list("updated_at", flat=True).first()
                )
                if current != loaded_updated_at:
                    raise EditConflict()
            instance = serializer.save()
            write_audit_log(
                actor=self.request.user,
                request=self.request,
                action=AuditActionCategory.UPDATE,
                resource_type=self.resource_type,
                resource_id=instance.pk,
                before=before,
                after=self.get_serializer(instance).data,
            )

    def destroy(self, request, *args, **kwargs):
        # QA audit L12: looked up WITHOUT the active-only filter
        # get_queryset() applies by default (same bypass unarchive() already
        # uses) - otherwise an already-archived row is invisible to the
        # normal get_object() lookup and a second DELETE 404s before the
        # idempotency check below ever runs, rather than cleanly no-op-ing.
        instance = super().get_queryset().filter(pk=kwargs["pk"]).first()
        if instance is None:
            raise NotFound()
        # QA audit L12: archiving an already-archived row is a no-op, not
        # a second real change - without this check, DELETE-ing the same
        # row twice wrote a SECOND identical ARCHIVE audit row (a
        # misleading "this was archived again" entry for something that
        # never actually un-archived in between) and bumped updated_at
        # for no real change.
        if not instance.is_active:
            return Response(status=status.HTTP_204_NO_CONTENT)
        self.perform_archive(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_archive(self, instance):
        """Archive ONE row on its own. Brand/VehicleModel override this to
        cascade (apps.vehicles.archiving)."""
        self._set_active(instance, False, AuditActionCategory.ARCHIVE)

    def perform_unarchive(self, instance):
        """Reactivate ONE row on its own; returns extra response data (the
        Brand/VehicleModel overrides return their cascade summary)."""
        self._set_active(instance, True, AuditActionCategory.UPDATE)
        return {}

    def _set_active(self, instance, is_active, action):
        before = self.get_serializer(instance).data
        with transaction.atomic():
            instance.is_active = is_active
            # QA audit L12: updated_at must reflect this change -
            # previously excluded from update_fields, so TimeStampedModel's
            # auto_now field never actually persisted a new value here.
            update_fields = ["is_active", "updated_at"]
            if hasattr(instance, "archived_by_parent"):
                # Handled directly by an admin, so no later cascade restore
                # of its parent may revive it (apps.vehicles.archiving).
                instance.archived_by_parent = False
                update_fields.append("archived_by_parent")
            instance.save(update_fields=update_fields)
            write_audit_log(
                actor=self.request.user,
                request=self.request,
                action=action,
                resource_type=self.resource_type,
                resource_id=instance.pk,
                before=before,
                after=self.get_serializer(instance).data,
            )

    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        """QA audit M18: there was previously no way to undo an
        accidental archive. get_queryset()'s own default excludes
        archived rows (the thing being un-archived is invisible to the
        normal get_object() lookup) - super().get_queryset() here
        bypasses that one override to find it, same reasoning as
        ?include_archived=true for list/retrieve.
        """
        instance = super().get_queryset().filter(pk=pk).first()
        if instance is None:
            raise NotFound()
        # QA audit L12: same idempotency/updated_at discipline as destroy()
        # above, applied consistently to its inverse.
        if instance.is_active:
            return Response(self.get_serializer(instance).data)
        extra = self.perform_unarchive(instance)
        return Response({**self.get_serializer(instance).data, **extra})
