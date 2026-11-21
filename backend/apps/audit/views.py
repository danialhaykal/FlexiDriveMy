from django.conf import settings
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.common.query_params import parse_datetime_param, parse_int_param
from apps.users.permissions import IsAdminRole

from .db import QueryTimeoutError, run_with_statement_timeout
from .models import AuditActionCategory, AuditLog
from .serializers import AuditLogSerializer

TIMEOUT_MESSAGE = "Log query timed out. Please specify a narrower date range filter."


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """F013 - System Log & Audit Trail Management.

    Read-only: audit rows are never created/edited/deleted through this API
    (they're written internally by AuditedModelViewSet). Supports filtering
    by actor (id, or the actor's email), action category, resource type, and a timestamp range, and
    guards its list query with a statement timeout (UC013 alt flow).
    """

    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminRole]
    queryset = AuditLog.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params

        # QA audit M1: every value below is validated/parsed before it
        # ever reaches a queryset filter - a non-numeric actor id or a
        # malformed date used to only fail once the queryset was actually
        # evaluated (inside run_with_statement_timeout below), as an
        # unhandled 500 that QueryTimeoutError's own except clause doesn't
        # catch.
        actor_id = params.get("actor")
        if actor_id:
            queryset = queryset.filter(actor_id=parse_int_param(params, "actor"))

        # The admin UI filters by who did it in the way an admin thinks of
        # them - an email - not a database id. Case-insensitive exact match on
        # the email recorded on the row itself (so it still matches after the
        # account was deleted or renamed). An email nobody used is just an empty
        # result, never an error. Combines (AND) with the id filter above.
        actor_email = (params.get("actor_email") or "").strip()
        if actor_email:
            queryset = queryset.filter(actor_email__iexact=actor_email)

        action = params.get("action")
        if action:
            if action not in AuditActionCategory.values:
                raise ValidationError(
                    {"action": f"Must be one of: {', '.join(AuditActionCategory.values)}."}
                )
            queryset = queryset.filter(action=action)

        # Run 3 fix batch 5 (F-30b): any letter case, and the short form an admin
        # would type - "InterestRate", "interestrate" or "policy.interestrate" all
        # find "policy.InterestRate" rows (the short form is the part after the dot).
        resource_type = (params.get("resource_type") or "").strip()
        if resource_type:
            if "." in resource_type:
                queryset = queryset.filter(resource_type__iexact=resource_type)
            else:
                queryset = queryset.filter(
                    Q(resource_type__iexact=resource_type) | Q(resource_type__iendswith=f".{resource_type}")
                )

        timestamp_from = parse_datetime_param(params, "timestamp_from")
        if timestamp_from:
            queryset = queryset.filter(timestamp__gte=timestamp_from)

        # QA audit L12: end_of_day=True - a date-only timestamp_to must
        # include the WHOLE day, not just its first instant.
        timestamp_to = parse_datetime_param(params, "timestamp_to", end_of_day=True)
        if timestamp_to:
            queryset = queryset.filter(timestamp__lte=timestamp_to)

        if timestamp_from and timestamp_to and timestamp_from > timestamp_to:
            raise ValidationError({"timestamp_from": "timestamp_from must not be after timestamp_to."})

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        timeout_ms = settings.AUDIT_LOG_QUERY_TIMEOUT_MS
        try:
            page = run_with_statement_timeout(lambda: self.paginate_queryset(queryset), timeout_ms)
        except QueryTimeoutError:
            return Response({"detail": TIMEOUT_MESSAGE}, status=status.HTTP_504_GATEWAY_TIMEOUT)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
