from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.comparisons.services import ComparisonConfigError
from apps.profiles.models import declared_mileage_band_for, ncd_percent_for

from .serializers import (
    TCORequestSerializer,
    TCOResultSerializer,
    TotalLossSandboxRequestSerializer,
    TotalLossSandboxResultSerializer,
)
from .services import OperatingCostConfigError, build_total_loss_sandbox, build_tco_report


class TCOView(APIView):
    """F006 - UC006 Predictive Depreciation, TCO Visualization & Contract
    Risk Alerts.

    GET, read-only, same reasoning as F005's ComparisonView. Missing
    interest-rate or operating-cost config is a clear 4xx (never a 500);
    an ML inference failure/timeout is NOT an error here - it degrades to
    a straight-line fallback and the response completes normally with
    model_degraded=true (UC006's exception flow never blocks the
    comparison).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = TCORequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Batch 6C / UC006 step 9's declared-mileage-mismatch alert: None
        # when the user has no saved UC003 baseline at all (most users,
        # most of the time) - build_tco_report treats None as "nothing to
        # compare against", never raising/blocking on it.
        try:
            result = build_tco_report(
                vehicle=data["vehicle"],
                tenure_months=data["tenure_months"],
                mileage_band=data["mileage_band"],
                downpayment=data["downpayment"],
                declared_mileage_band=declared_mileage_band_for(request.user),
                # From the user's own profile, never the request.
                ncd_percent=ncd_percent_for(request.user),
            )
        except (ComparisonConfigError, OperatingCostConfigError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(TCOResultSerializer(result).data, status=status.HTTP_200_OK)


class TotalLossSandboxView(APIView):
    """Sprint 12 - illustrative Total-Loss Exposure Sandbox.

    GET, read-only, same reasoning as TCOView. Always 200 once the
    request itself is valid - build_total_loss_sandbox() never raises; a
    missing interest rate/residual ratio shows up as that pathway (HP
    and/or GFV) being null with its reason in `unavailable`, same
    graceful-degradation contract as ComparisonView.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = TotalLossSandboxRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = build_total_loss_sandbox(
            vehicle=data["vehicle"],
            tenure_months=data["tenure_months"],
            mileage_band=data["mileage_band"],
            downpayment=data["downpayment"],
            loss_month=data["loss_month"],
            excess_amount=data["excess_amount"],
        )

        return Response(TotalLossSandboxResultSerializer(result).data, status=status.HTTP_200_OK)
