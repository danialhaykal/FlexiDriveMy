from django.contrib import admin

from apps.audit.admin_mixins import NoHardDeleteAdminMixin

from .models import FinancialProfile


@admin.register(FinancialProfile)
class FinancialProfileAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = [
        "user",
        "monthly_budget",
        "preferred_tenure_months",
        "annual_mileage_band",
        "ownership_preference",
        "shariah_compliant_required",
    ]
    list_filter = ["annual_mileage_band", "ownership_preference", "shariah_compliant_required"]
    search_fields = ["user__email"]
