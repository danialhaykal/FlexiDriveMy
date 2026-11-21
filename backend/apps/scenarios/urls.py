from rest_framework.routers import DefaultRouter

from .views import SavedScenarioViewSet

router = DefaultRouter()
router.register("", SavedScenarioViewSet, basename="saved-scenario")

urlpatterns = router.urls
