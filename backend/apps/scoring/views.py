from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.profiles.models import ncd_percent_for

from .serializers import (
    DSRSimulatorRequestSerializer,
    DSRSimulatorResultSerializer,
    SuitabilityScoringRequestSerializer,
    SuitabilityScoringResultSerializer,
)
from .services import build_dsr_simulation, build_suitability_scoring


class SuitabilityScoringView(APIView):
    """F007 - UC007 AI Suitability Scoring & Recommendation.

    GET, read-only, same reasoning as F005/F006. Blocks scoring (400) if
    any priority dimension is unanswered (UC007 alt flow) - but never for
    missing F010/F011 config: build_suitability_scoring() scores
    whichever pathways are available and reports the rest in
    `unavailable`, same always-200-once-valid contract as F005's own
    endpoint.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = SuitabilityScoringRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = build_suitability_scoring(
            vehicle=data["vehicle"],
            tenure_months=data["tenure_months"],
            mileage_band=data["mileage_band"],
            downpayment=data["downpayment"],
            priority_ratings={
                "upfront_cash_preservation": data["upfront_cash_preservation"],
                "maintenance_protection": data["maintenance_protection"],
                "ownership_equity": data["ownership_equity"],
            },
            monthly_income=data["monthly_income"],
            max_dsr_percent=data["max_dsr_percent"],
            ncd_percent=ncd_percent_for(request.user),
        )

        return Response(SuitabilityScoringResultSerializer(result).data, status=status.HTTP_200_OK)


class DSRSimulatorView(APIView):
    """Sprint 11 - standalone Affordability / DSR Simulator.

    GET, read-only, same reasoning as F005/F007. A separate tool from
    F007's own recommendation flow: it doesn't rank or recommend, it only
    reports each available pathway's total DSR (including self-declared
    existing debt) and CCRIS-reportability - an unavailable pathway is
    listed in `unavailable` with its reason, never a 400 for the whole
    request.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = DSRSimulatorRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = build_dsr_simulation(
            vehicle=data["vehicle"],
            tenure_months=data["tenure_months"],
            mileage_band=data["mileage_band"],
            downpayment=data["downpayment"],
            monthly_income=data["monthly_income"],
            existing_monthly_commitments=data["existing_monthly_commitments"],
            max_dsr_percent=data["max_dsr_percent"],
            ncd_percent=ncd_percent_for(request.user),
        )

        return Response(DSRSimulatorResultSerializer(result).data, status=status.HTTP_200_OK)
