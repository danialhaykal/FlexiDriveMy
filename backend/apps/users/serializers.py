from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User, UserRole
from .validators import validate_phone_number

# Run 3 fix batch 5 (F-04): one sentence for a duplicate email, whatever its letter case.
DUPLICATE_EMAIL_MESSAGE = "An account with this email already exists."


class UserProfileSerializer(serializers.ModelSerializer):
    """Used for viewing and editing the authenticated user's own profile."""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "role",
            "date_joined",
        ]
        read_only_fields = ["id", "email", "role", "date_joined"]
        # Run 3 fix batch 5 (F-05): the same phone rule as registration.
        extra_kwargs = {"phone_number": {"validators": [validate_phone_number], "max_length": None}}


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    # QA audit M20: UC001 asks for a confirm-password field - write-only,
    # never persisted (popped in create() below), checked against
    # `password` in validate() with a specific, non-generic message.
    password2 = serializers.CharField(write_only=True, label="Confirm password")

    class Meta:
        model = User
        fields = ["id", "email", "password", "password2", "first_name", "last_name", "phone_number"]
        read_only_fields = ["id"]
        extra_kwargs = {
            # Run 3 fix batch 5 (F-04): no auto UniqueValidator - it matched only the exact
            # case and had its own sentence; validate_email below is the one check (any case).
            "email": {"validators": []},
            "phone_number": {"validators": [validate_phone_number], "max_length": None},
        }

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({"password2": "Passwords do not match."})
        return attrs

    def validate_email(self, value):
        # QA audit H7: ModelSerializer's auto-generated UniqueValidator
        # only catches an EXACT-case match (it queries on the field's own
        # unique=True) - registering "qa.tester@example.com" when
        # "QA.Tester@Example.com" already exists would sail past that
        # check and only then collide with the DB's case-insensitive
        # UniqueConstraint (migration 0002), as a raw IntegrityError the
        # view doesn't catch (an unhandled 500). Catching it here first
        # means it's always a clean 400 - the DB constraint is a backstop
        # that should never actually be hit in the normal request path.
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(DUPLICATE_EMAIL_MESSAGE)
        return value

    def create(self, validated_data):
        # Role is never accepted from client input on self-registration;
        # every self-registered account is a regular user. password2 is
        # confirmation-only - it was never a real field on User, and
        # create_user would reject an unexpected kwarg if it weren't
        # popped here.
        validated_data.pop("password2")
        validated_data["role"] = UserRole.USER
        return User.objects.create_user(**validated_data)


class ChangePasswordSerializer(serializers.Serializer):
    """QA audit M20: a reasonably-scoped "change password" action for an
    ALREADY-authenticated user (old password + new password) - a full
    forgot-password-via-email flow (reset request, emailed token,
    unauthenticated reset form) is a separate, materially larger feature
    (needs an email provider, a token model/expiry, a new unauthenticated
    endpoint) and is flagged as its own follow-up rather than folded into
    this batch, the same way H11 flagged the ML Model Management admin
    page as a named follow-up rather than building it inline.
    """

    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds role/profile claims to the JWT and to the login response body."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["email"] = user.email
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserProfileSerializer(self.user).data
        return data
