from rest_framework_simplejwt.views import TokenRefreshView

from django.urls import path

from .views import (
    AdminUserListView,
    ChangePasswordView,
    LoginView,
    LogoutView,
    ProfileView,
    RegisterView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("login/refresh/", TokenRefreshView.as_view(), name="auth-login-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("profile/", ProfileView.as_view(), name="auth-profile"),
    path("change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
    path("users/", AdminUserListView.as_view(), name="auth-admin-user-list"),
]
