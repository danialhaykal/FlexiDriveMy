from django.urls import path

from .views import (
    MLDatasetUploadView,
    MLTrainingRunDeployView,
    MLTrainingRunDetailView,
    MLTrainingRunListView,
    ProductionModelView,
)

urlpatterns = [
    path("production-model/", ProductionModelView.as_view(), name="ml-production-model"),
    path("datasets/", MLDatasetUploadView.as_view(), name="ml-dataset-upload"),
    path("training-runs/", MLTrainingRunListView.as_view(), name="ml-training-run-list"),
    path("training-runs/<int:pk>/", MLTrainingRunDetailView.as_view(), name="ml-training-run-detail"),
    path(
        "training-runs/<int:pk>/deploy/",
        MLTrainingRunDeployView.as_view(),
        name="ml-training-run-deploy",
    ),
]
