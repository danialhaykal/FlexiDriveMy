from django.contrib import admin

from apps.audit.admin_mixins import NoHardDeleteAdminMixin

from .models import SavedScenario


@admin.register(SavedScenario)
class SavedScenarioAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = ["title", "user", "vehicle", "updated_at"]
    list_filter = ["user"]
    search_fields = ["title", "user__email"]
