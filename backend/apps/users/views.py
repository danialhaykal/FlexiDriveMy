from datetime import datetime, timezone as dt_timezone

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import User
from .permissions import IsAdminRole
from .serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserProfileSerializer,
)


class RegisterView(generics.CreateAPIView):
    """F001 - Registration. Always creates a role='user' account."""

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    # QA audit M21: 5/min per IP (see DEFAULT_THROTTLE_RATES) - no limit
    # previously existed at all.
    throttle_scope = "auth-register"


class LoginView(TokenObtainPairView):
    """F001 - Login. Returns access/refresh JWTs plus the user's profile."""

    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]
    # QA audit M21: 5/min per IP (see DEFAULT_THROTTLE_RATES) - previously
    # unlimited, so a password could be guessed without any rate limit.
    throttle_scope = "auth-login"


class LogoutView(APIView):
    """F002 - Logout. Blacklists the refresh token so it can't be reused.

    QA audit H6: also blacklists the ACCESS token this very request was
    authenticated with - otherwise it kept working for the rest of its
    own lifetime (up to ACCESS_TOKEN_LIFETIME later), which isn't really
    "logged out". See apps.users.authentication.BlacklistAwareJWTAuthentication
    for the matching enforcement side (checked on every request).
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "refresh token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response(
                {"detail": "Token is invalid or already blacklisted"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        self._blacklist_current_access_token(request)
        return Response(status=status.HTTP_205_RESET_CONTENT)

    @staticmethod
    def _blacklist_current_access_token(request):
        access_token = request.auth
        if access_token is None:
            return
        jti = access_token["jti"]
        outstanding, _ = OutstandingToken.objects.get_or_create(
            jti=jti,
            defaults={
                "user": request.user,
                "token": str(access_token),
                "created_at": datetime.fromtimestamp(access_token["iat"], tz=dt_timezone.utc),
                "expires_at": datetime.fromtimestamp(access_token["exp"], tz=dt_timezone.utc),
            },
        )
        BlacklistedToken.objects.get_or_create(token=outstanding)


class ProfileView(generics.RetrieveUpdateAPIView):
    """F001 - View/edit the authenticated user's own profile."""

    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    """QA audit M20 - change password for an already-authenticated user
    (old password + new password). See ChangePasswordSerializer's own
    docstring for why a full forgot-password-via-email flow is scoped out."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminUserListView(generics.ListAPIView):
    """Admin-only: list all user accounts. Exercises role-based access control."""

    queryset = User.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [IsAdminRole]
