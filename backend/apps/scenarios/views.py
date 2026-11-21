from django.db import IntegrityError, transaction
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response

from .models import SavedScenario
from .serializers import DUPLICATE_TITLE_MESSAGE, SavedScenarioSerializer, check_payload_size
from .snapshot import build_scenario_snapshot


class SavedScenarioViewSet(viewsets.ModelViewSet):
    """F009 - UC009 Calculation History Save & Retrieval.

    get_queryset() scopes every action (list/retrieve/update/destroy) to
    the requesting user - UC009 Rule 1 ("users can only view, modify, or
    delete saved scenario records linked directly to their authenticated
    account"). Another user's scenario id simply isn't found (404), not a
    403 - it doesn't confirm the id exists for someone else.
    """

    serializer_class = SavedScenarioSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # select_related: the serializer's vehicle_label always accesses
        # vehicle.brand.name - avoids an N+1 query per row on list/retrieve.
        return SavedScenario.objects.filter(user=self.request.user).select_related("vehicle", "vehicle__brand")

    def _find_duplicate(self, title, exclude_pk=None):
        # QA audit M3: case-insensitive, matching UC009's own alt-flow
        # wording ("A scenario with this label already exists") - a
        # title differing only by case is still the same label to a user.
        queryset = SavedScenario.objects.filter(user=self.request.user, title__iexact=title)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        return queryset.exists()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        title = serializer.validated_data["title"]
        vehicle = serializer.validated_data["vehicle"]
        overwrite = str(request.data.get("overwrite", "")).lower() in ("true", "1")

        existing = SavedScenario.objects.filter(user=request.user, title__iexact=title).first()

        if existing and not overwrite:
            # UC009 alt flow 2.1-2.3: reject, let the client either pick a
            # new title (2.4a, just resubmit) or resubmit with overwrite=true (2.4b).
            return Response({"detail": DUPLICATE_TITLE_MESSAGE}, status=status.HTTP_409_CONFLICT)

        # Run 1 fix batch 2 (G6): the figures are calculated here from the
        # validated inputs, never taken from the client.
        payload = build_scenario_snapshot(
            user=request.user, vehicle=vehicle, inputs=serializer.validated_data["inputs"]
        )
        check_payload_size(payload)

        if existing and overwrite:
            # UC009 alt flow 2.4b: replace the payload, bump updated_at
            # (TimeStampedModel's auto_now handles the timestamp).
            existing.title = title
            existing.vehicle = vehicle
            existing.payload = payload
            existing.save()
            return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)

        try:
            # QA audit M3: a race between two concurrent creates with the
            # same title (e.g. a double-click Save) could both pass the
            # `existing` check above before either commits - the real
            # guard is the DB's own UniqueConstraint, caught here as a
            # clean 409 rather than an unhandled 500. transaction.atomic()
            # makes this a savepoint, so catching the error doesn't poison
            # the rest of the request's (or, in tests, the enclosing
            # test's) transaction.
            with transaction.atomic():
                scenario = SavedScenario.objects.create(
                    user=request.user, title=title, vehicle=vehicle, payload=payload
                )
        except IntegrityError:
            return Response({"detail": DUPLICATE_TITLE_MESSAGE}, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(scenario).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """QA audit M3: renaming a scenario to an already-used title gave
        a 500 - the duplicate-title check above only ever ran on create().
        Covers both PUT and PATCH (UpdateModelMixin.partial_update() just
        calls this with partial=True).

        Run 1 fix batch 2: an update is a rename only. `payload` is
        read-only and `inputs` is refused by the serializer, so the stored
        figures are never touched here.
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        new_title = serializer.validated_data.get("title", instance.title)
        if self._find_duplicate(new_title, exclude_pk=instance.pk):
            return Response({"detail": DUPLICATE_TITLE_MESSAGE}, status=status.HTTP_409_CONFLICT)

        try:
            with transaction.atomic():
                self.perform_update(serializer)
        except IntegrityError:
            return Response({"detail": DUPLICATE_TITLE_MESSAGE}, status=status.HTTP_409_CONFLICT)
        return Response(serializer.data)
