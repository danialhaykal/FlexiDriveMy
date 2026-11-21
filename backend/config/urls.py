from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.users.urls")),
    path("api/vehicles/", include("apps.vehicles.urls")),
    path("api/admin/", include("apps.vehicles.admin_urls")),
    path("api/policy/", include("apps.policy.urls")),
    path("api/audit/", include("apps.audit.urls")),
    path("api/profile/", include("apps.profiles.urls")),
    path("api/comparisons/", include("apps.comparisons.urls")),
    path("api/ml/", include("apps.ml.urls")),
    path("api/depreciation/", include("apps.depreciation.urls")),
    path("api/scoring/", include("apps.scoring.urls")),
    path("api/exports/", include("apps.exports.urls")),
    path("api/scenarios/", include("apps.scenarios.urls")),
]
