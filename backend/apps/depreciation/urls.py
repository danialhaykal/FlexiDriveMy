from django.urls import path

from .views import TCOView, TotalLossSandboxView

urlpatterns = [
    path("tco/", TCOView.as_view(), name="tco"),
    path("total-loss-sandbox/", TotalLossSandboxView.as_view(), name="total-loss-sandbox"),
]
