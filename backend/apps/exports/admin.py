from django.contrib import admin

from apps.audit.admin_mixins import NoHardDeleteAdminMixin

from .models import PDFExportJob


@admin.register(PDFExportJob)
class PDFExportJobAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = ["id", "user", "status", "created_at"]
    list_filter = ["status"]
    readonly_fields = [f.name for f in PDFExportJob._meta.fields]

    def has_add_permission(self, request):
        return False
