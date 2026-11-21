from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FinancialProfile
from .serializers import FinancialProfileSerializer


class FinancialProfileView(APIView):
    """F003 - UC003 Financial & Lifestyle Profiling Input.

    A singleton-per-user resource: GET returns the current baseline (404 if
    none saved yet), PUT upserts it ("Save & Apply Baseline" is idempotent -
    it doesn't matter whether this is the user's first save or an edit).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            profile = FinancialProfile.objects.get(user=request.user)
        except FinancialProfile.DoesNotExist:
            return Response(
                {"detail": "No financial profile has been saved yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(FinancialProfileSerializer(profile).data)

    def put(self, request):
        instance = FinancialProfile.objects.filter(user=request.user).first()
        serializer = FinancialProfileSerializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
