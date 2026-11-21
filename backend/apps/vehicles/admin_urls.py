from django.urls import path

from .views import VehicleReadinessView

urlpatterns = [
    path("vehicle-readiness/", VehicleReadinessView.as_view(), name="vehicle-readiness"),
]

