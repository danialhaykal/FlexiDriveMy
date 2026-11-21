from django.urls import path

from .views import DSRSimulatorView, SuitabilityScoringView

urlpatterns = [
    path("", SuitabilityScoringView.as_view(), name="suitability-scoring"),
    path("dsr-simulator/", DSRSimulatorView.as_view(), name="dsr-simulator"),
]
