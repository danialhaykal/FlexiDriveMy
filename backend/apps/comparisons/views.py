from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.policy.mileage import mileage_band_options
from apps.profiles.models import ncd_percent_for

from .arena import build_arena, compute_arena_winners
from .serializers import (
    ArenaRequestSerializer,
    ArenaResultSerializer,
    ComparisonRequestSerializer,
    ComparisonResultSerializer,
)
from .services import build_comparison


class ComparisonView(APIView):
    """F005 - UC005 Multi-Pathway Comparison Engine.

    GET, not POST: this is a read-only calculation with no side effects
    (nothing is created or persisted) given a vehicle/tenure/mileage-
    band/downpayment. All arithmetic happens here in Python - the response
    is displayed as-is by the frontend, never recomputed client-side
    (the project spec's architecture rule).

    Always 200 once the request itself is valid (valid vehicle, valid
    tenure/mileage/downpayment) - build_comparison() never raises; a
    missing/inactive config for one pathway shows up as that pathway
    being null with its reason in `unavailable`, never a blanket failure
    for pathways that had everything they needed.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = ComparisonRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = build_comparison(
            vehicle=data["vehicle"],
            tenure_months=data["tenure_months"],
            mileage_band=data["mileage_band"],
            downpayment=data["downpayment"],
            # From the user's own profile, never the request.
            ncd_percent=ncd_percent_for(request.user),
        )

        return Response(ComparisonResultSerializer(result).data, status=status.HTTP_200_OK)


class MileageBandsView(APIView):
    """The one list of mileage bands (value, label showing the band's ceiling in
    km a year, included km) the Financial Profile and the compare screens
    share - see apps.policy.mileage. Read-only, any signed-in user."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(mileage_band_options())


class ArenaView(APIView):
    """F005+F006 - Sprint 10's multi-vehicle "Arena" comparison: 2-3
    vehicles side by side, same shared tenure/mileage/downpayment. GET,
    read-only, same reasoning as ComparisonView - runs the existing,
    already-tested build_comparison()/build_tco_report() once per
    selected vehicle via apps.comparisons.arena.build_arena.

    A config problem for ONE vehicle never fails the whole request (200
    with that vehicle's own "ok": False entry) - only request-shape
    problems (vehicle count, duplicate IDs, tenure/downpayment format)
    are a 400, via ArenaRequestSerializer.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = ArenaRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        results = build_arena(
            vehicles=data["vehicles"],
            tenure_months=data["tenure_months"],
            mileage_band=data["mileage_band"],
            downpayment=data["downpayment"],
            ncd_percent=ncd_percent_for(request.user),
        )
        winners = compute_arena_winners(results)

        return Response(
            ArenaResultSerializer({"results": results, "winners": winners}).data,
            status=status.HTTP_200_OK,
        )
