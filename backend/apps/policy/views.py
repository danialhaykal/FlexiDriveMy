from django.db import transaction
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.mixins import AuditedModelViewSet
from apps.audit.models import AuditActionCategory
from apps.audit.services import write_audit_log
from apps.users.permissions import IsAdminRole

from .models import (
    ContractPenaltyRule,
    FuelSchedule,
    InterestRate,
    MCDACriteriaWeight,
    MCDACriterion,
    EvRoadTaxGroup,
    OperatingCostRate,
    ResidualAdjustment,
    ResidualBaseline,
    ResidualValueMatrix,
    RoadTaxCcBand,
    SubscriptionPlan,
    SubscriptionPolicy,
)
from .serializers import (
    ContractPenaltyRuleSerializer,
    EvRoadTaxGroupReadSerializer,
    InterestRateSerializer,
    MCDACriteriaWeightSerializer,
    MCDAWeightSetSerializer,
    OperatingCostRateReadSerializer,
    ResidualAdjustmentReadSerializer,
    ResidualBaselineReadSerializer,
    ResidualValueMatrixSerializer,
    RoadTaxCcBandReadSerializer,
    SubscriptionPlanSerializer,
    SubscriptionPolicyReadSerializer,
)


class InterestRateViewSet(AuditedModelViewSet, viewsets.ModelViewSet):
    """F011 - dealer interest rates (CRUD + archive)."""

    resource_type = "policy.InterestRate"
    serializer_class = InterestRateSerializer
    permission_classes = [IsAdminRole]
    queryset = InterestRate.objects.select_related("brand").all()


class ResidualValueMatrixViewSet(AuditedModelViewSet, viewsets.ModelViewSet):
    """F011 - OPTIONAL per-brand GFV residual overrides, keyed by brand +
    tenure + mileage band. With no row, apps.policy.residuals estimates it."""

    resource_type = "policy.ResidualValueMatrix"
    serializer_class = ResidualValueMatrixSerializer
    permission_classes = [IsAdminRole]
    queryset = ResidualValueMatrix.objects.select_related("brand").all()


class SubscriptionPlanViewSet(AuditedModelViewSet, viewsets.ModelViewSet):
    """Batch 6A / F011 - per-vehicle subscription commercial terms (CRUD + archive)."""

    resource_type = "policy.SubscriptionPlan"
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAdminRole]
    queryset = SubscriptionPlan.objects.select_related("vehicle", "vehicle__brand").all()


class OperatingCostsView(APIView):
    """Read-only: the three rate tables apps.policy.operating_costs reads
    (JPJ cc road-tax tables by registration class, JPJ EV kW groups,
    insurance/maintenance percentages and caps), each row with its
    source_note and effective_from, for the Policy Configuration page's
    "Operating Costs" tab. Active rows only, plus the archived diesel cc
    bands (run 1 fix batch 3) listed separately so it is clear they are no
    longer used. Edited in Django admin - no write API."""

    permission_classes = [IsAdminRole]

    def get(self, request):
        return Response(
            {
                "road_tax_cc_bands": RoadTaxCcBandReadSerializer(
                    RoadTaxCcBand.objects.filter(is_active=True).order_by("vehicle_class", "min_cc"), many=True
                ).data,
                "archived_diesel_cc_bands": RoadTaxCcBandReadSerializer(
                    RoadTaxCcBand.objects.filter(is_active=False, fuel_schedule=FuelSchedule.DIESEL).order_by(
                        "min_cc"
                    ),
                    many=True,
                ).data,
                "ev_road_tax_groups": EvRoadTaxGroupReadSerializer(
                    EvRoadTaxGroup.objects.filter(is_active=True).order_by("min_kw"), many=True
                ).data,
                "cost_rates": OperatingCostRateReadSerializer(
                    OperatingCostRate.objects.filter(is_active=True).order_by("powertrain"), many=True
                ).data,
            }
        )


class ResidualEstimatesView(APIView):
    """Read-only: the tables apps.policy.residuals estimates GFV residuals
    from (the baseline grid and the brand/powertrain adjustments), each row
    with its source_note, for the Policy Configuration "Residual Estimates"
    tab. Active rows only. Edited in Django admin - no write API."""

    permission_classes = [IsAdminRole]

    def get(self, request):
        return Response(
            {
                "baselines": ResidualBaselineReadSerializer(
                    ResidualBaseline.objects.filter(is_active=True).order_by("tenure_months", "mileage_band"),
                    many=True,
                ).data,
                "adjustments": ResidualAdjustmentReadSerializer(
                    ResidualAdjustment.objects.filter(is_active=True)
                    .select_related("brand")
                    .order_by("powertrain", "brand__name"),
                    many=True,
                ).data,
            }
        )


class SubscriptionEstimatesView(APIView):
    """Read-only: the SubscriptionPolicy assumptions apps.policy.
    subscription_pricing estimates every Subscription fee from, with their
    source_note, for the Policy Configuration "Subscription Estimates" tab.
    Active rows only. Edited in Django admin - no write API."""

    permission_classes = [IsAdminRole]

    def get(self, request):
        policies = SubscriptionPolicy.objects.filter(is_active=True).order_by("-effective_from", "-pk")
        return Response({"policies": SubscriptionPolicyReadSerializer(policies, many=True).data})


class ContractPenaltyRuleViewSet(AuditedModelViewSet, viewsets.ModelViewSet):
    """Batch 6A / UC011's "contract penalty rules" - see
    apps.policy.models.ContractPenaltyRule's own docstring (CRUD + archive)."""

    resource_type = "policy.ContractPenaltyRule"
    serializer_class = ContractPenaltyRuleSerializer
    permission_classes = [IsAdminRole]
    queryset = ContractPenaltyRule.objects.select_related("brand").all()  # brand is null on the default rule


class MCDAWeightsView(APIView):
    """F011 - MCDA criteria weightings.

    Exposed as a single GET/PUT resource rather than per-row CRUD: the
    three criteria weights must always sum to 1.0 (the project spec), an invariant
    that spans all three rows and can't be maintained by editing one row
    at a time without passing through an invalid intermediate state.
    """

    permission_classes = [IsAdminRole]

    def get(self, request):
        weights = MCDACriteriaWeight.objects.filter(is_active=True).order_by("criterion")
        return Response(MCDACriteriaWeightSerializer(weights, many=True).data)

    def put(self, request):
        serializer = MCDAWeightSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data["weights"]

        before = list(
            MCDACriteriaWeight.objects.filter(is_active=True)
            .order_by("criterion")
            .values("criterion", "default_weight")
        )

        # QA audit H1: the audit write now shares the SAME atomic block as
        # the weight updates - either both commit or neither does.
        # Previously the audit write happened after this block had
        # already closed, so a failure writing it (e.g. a malformed IP)
        # left the weight change committed with no audit row.
        with transaction.atomic():
            updated = []
            for item in payload:
                obj, _ = MCDACriteriaWeight.objects.update_or_create(
                    criterion=item["criterion"],
                    defaults={"default_weight": item["default_weight"], "is_active": True},
                )
                updated.append(obj)

            after = list(
                MCDACriteriaWeight.objects.filter(is_active=True)
                .order_by("criterion")
                .values("criterion", "default_weight")
            )
            write_audit_log(
                actor=request.user,
                request=request,
                action=AuditActionCategory.UPDATE,
                resource_type="policy.MCDACriteriaWeight",
                resource_id="all",
                before={"weights": before},
                after={"weights": after},
            )

        updated.sort(key=lambda obj: obj.criterion)
        return Response(MCDACriteriaWeightSerializer(updated, many=True).data)
