from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from rest_framework_simplejwt.token_blacklist.admin import BlacklistedTokenAdmin as SimpleJwtBlacklistedTokenAdmin
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from apps.audit.admin_mixins import NoHardDeleteAdminMixin

from .models import User


@admin.register(User)
class UserAdmin(NoHardDeleteAdminMixin, DjangoUserAdmin):
    # Run 3 fix batch 4 (F-32): a user is deactivated (is_active), never deleted -
    # their saved comparisons, exports and audit rows refer to them.
    ordering = ["-date_joined"]
    list_display = ["email", "first_name", "last_name", "role", "is_staff", "is_active"]
    list_filter = ["role", "is_staff", "is_active"]
    search_fields = ["email", "first_name", "last_name"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone_number")}),
        ("Role", {"fields": ("role",)}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "role"),
            },
        ),
    )
    readonly_fields = ["date_joined"]


# Run 3 fix batch 4 (F-32): deleting a blacklisted token would quietly un-revoke a
# logged-out refresh token. simplejwt's own OutstandingToken admin already refuses
# deletes; its BlacklistedToken admin did not. (rest_framework_simplejwt.token_blacklist
# is installed before apps.users, so its registration exists here to replace.)
class BlacklistedTokenAdmin(NoHardDeleteAdminMixin, SimpleJwtBlacklistedTokenAdmin):
    pass


if admin.site.is_registered(BlacklistedToken):
    admin.site.unregister(BlacklistedToken)
admin.site.register(BlacklistedToken, BlacklistedTokenAdmin)
