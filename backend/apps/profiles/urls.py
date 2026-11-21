from django.urls import path

from .views import FinancialProfileView

urlpatterns = [
    path("financial/", FinancialProfileView.as_view(), name="financial-profile"),
]
