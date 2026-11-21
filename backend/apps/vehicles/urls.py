from rest_framework.routers import DefaultRouter

from .views import BrandViewSet, CatalogVehicleViewSet, VehicleModelViewSet, VehicleSpecDraftViewSet

router = DefaultRouter()
router.register("brands", BrandViewSet, basename="brand")
router.register("models", VehicleModelViewSet, basename="vehicle-model")
router.register("catalog", CatalogVehicleViewSet, basename="catalog-vehicle")
router.register("spec-drafts", VehicleSpecDraftViewSet, basename="vehicle-spec-draft")

urlpatterns = router.urls
