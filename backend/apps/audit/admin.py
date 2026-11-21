from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only in the Django admin: no add/change/delete, matching the
    append-only guarantee enforced at the database level."""

    list_display = ["timestamp", "actor_email", "action", "resource_type", "resource_id", "ip_address"]
    list_filter = ["action", "resource_type"]
    search_fields = ["actor_email", "resource_type", "resource_id"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
