from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ContractPenaltyRuleViewSet,
    InterestRateViewSet,
    MCDAWeightsView,
    OperatingCostsView,
    ResidualEstimatesView,
    ResidualValueMatrixViewSet,
    SubscriptionEstimatesView,
    SubscriptionPlanViewSet,
)

router = DefaultRouter()
router.register("interest-rates", InterestRateViewSet, basename="interest-rate")
router.register("residual-value-matrix", ResidualValueMatrixViewSet, basename="residual-value-matrix")
router.register("subscription-plans", SubscriptionPlanViewSet, basename="subscription-plan")
router.register("contract-penalty-rules", ContractPenaltyRuleViewSet, basename="contract-penalty-rule")

urlpatterns = [
    path("mcda-weights/", MCDAWeightsView.as_view(), name="mcda-weights"),
    path("operating-costs/", OperatingCostsView.as_view(), name="operating-costs"),
    path("residual-estimates/", ResidualEstimatesView.as_view(), name="residual-estimates"),
    path("subscription-estimates/", SubscriptionEstimatesView.as_view(), name="subscription-estimates"),
] + router.urls
