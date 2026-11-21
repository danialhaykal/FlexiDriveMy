from django.urls import path

from .views import ArenaView, ComparisonView, MileageBandsView

urlpatterns = [
    path("", ComparisonView.as_view(), name="comparison"),
    path("mileage-bands/", MileageBandsView.as_view(), name="mileage-bands"),
    path("arena/", ArenaView.as_view(), name="comparison-arena"),
]
