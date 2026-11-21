from datetime import timedelta

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.users.models import User, UserRole

pytestmark = pytest.mark.django_db


# --- Registration (F001) ----------------------------------------------------


def test_register_creates_user_with_default_role(api_client):
    url = reverse("auth-register")
    payload = {
        "email": "newrider@example.com",
        "password": "AnotherStrongPass1!",
        "password2": "AnotherStrongPass1!",
        "first_name": "New",
        "last_name": "Rider",
        "role": UserRole.ADMIN,  # must be ignored: self-registration can't grant admin
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    user = User.objects.get(email="newrider@example.com")
    assert user.role == UserRole.USER
    assert user.check_password("AnotherStrongPass1!")


def test_register_duplicate_email_rejected(api_client, regular_user):
    url = reverse("auth-register")
    payload = {
        "email": regular_user.email,
        "password": "AnotherStrongPass1!",
        "password2": "AnotherStrongPass1!",
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- H7: emails are case-insensitive end to end -----------------------------


def test_register_lowercases_the_stored_email(api_client):
    url = reverse("auth-register")
    payload = {
        "email": "Mixed.Case@Example.com",
        "password": "AnotherStrongPass1!",
        "password2": "AnotherStrongPass1!",
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    user = User.objects.get(email="mixed.case@example.com")
    assert user.email == "mixed.case@example.com"


def test_registering_a_different_case_of_an_existing_email_is_rejected_as_duplicate_not_a_second_account(
    api_client,
):
    url = reverse("auth-register")
    api_client.post(
        url,
        {
            "email": "QA.Tester@Example.com",
            "password": "AnotherStrongPass1!",
            "password2": "AnotherStrongPass1!",
        },
        format="json",
    )

    response = api_client.post(
        url,
        {
            "email": "qa.tester@example.com",
            "password": "AnotherStrongPass1!",
            "password2": "AnotherStrongPass1!",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert User.objects.filter(email__iexact="qa.tester@example.com").count() == 1


def test_login_with_a_different_case_than_registered_resolves_to_the_same_account(api_client, user_password):
    register_url = reverse("auth-register")
    api_client.post(
        register_url,
        {"email": "QA.Tester@Example.com", "password": user_password, "password2": user_password},
        format="json",
    )

    login_url = reverse("auth-login")
    response = api_client.post(
        login_url, {"email": "qa.tester@example.com", "password": user_password}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["user"]["email"] == "qa.tester@example.com"


def test_register_weak_password_rejected(api_client):
    url = reverse("auth-register")
    payload = {"email": "weak@example.com", "password": "123", "password2": "123"}

    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- M20: confirm-password on registration -----------------------------------


def test_register_mismatched_passwords_rejected_with_a_specific_message(api_client):
    url = reverse("auth-register")
    payload = {
        "email": "newrider@example.com",
        "password": "AnotherStrongPass1!",
        "password2": "ADifferentPass1!",
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["password2"][0] == "Passwords do not match."
    assert not User.objects.filter(email="newrider@example.com").exists()


def test_register_missing_password2_rejected(api_client):
    url = reverse("auth-register")
    payload = {"email": "newrider@example.com", "password": "AnotherStrongPass1!"}

    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "password2" in response.data


# --- M20: change password for an already-authenticated user -----------------


def test_change_password_succeeds_with_correct_old_password(api_client, regular_user, user_password):
    api_client.force_authenticate(user=regular_user)
    url = reverse("auth-change-password")

    response = api_client.post(
        url,
        {"old_password": user_password, "new_password": "ABrandNewStrongPass1!"},
        format="json",
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    regular_user.refresh_from_db()
    assert regular_user.check_password("ABrandNewStrongPass1!")
    assert not regular_user.check_password(user_password)


def test_change_password_rejects_an_incorrect_old_password(api_client, regular_user, user_password):
    api_client.force_authenticate(user=regular_user)
    url = reverse("auth-change-password")

    response = api_client.post(
        url,
        {"old_password": "totally-wrong", "new_password": "ABrandNewStrongPass1!"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["old_password"][0] == "Current password is incorrect."
    regular_user.refresh_from_db()
    assert regular_user.check_password(user_password)  # unchanged


def test_change_password_rejects_a_weak_new_password(api_client, regular_user, user_password):
    api_client.force_authenticate(user=regular_user)
    url = reverse("auth-change-password")

    response = api_client.post(
        url, {"old_password": user_password, "new_password": "123"}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    regular_user.refresh_from_db()
    assert regular_user.check_password(user_password)  # unchanged


def test_change_password_requires_authentication(api_client):
    url = reverse("auth-change-password")

    response = api_client.post(
        url, {"old_password": "whatever", "new_password": "ABrandNewStrongPass1!"}, format="json"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Login (F001) ------------------------------------------------------------


def test_login_success_returns_tokens_and_profile(api_client, regular_user, user_password):
    url = reverse("auth-login")

    response = api_client.post(
        url, {"email": regular_user.email, "password": user_password}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["user"]["email"] == regular_user.email
    assert response.data["user"]["role"] == UserRole.USER


def test_login_invalid_credentials_rejected(api_client, regular_user):
    url = reverse("auth-login")

    response = api_client.post(
        url, {"email": regular_user.email, "password": "wrong-password"}, format="json"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "access" not in response.data


def test_login_unknown_email_rejected(api_client):
    url = reverse("auth-login")

    response = api_client.post(
        url, {"email": "nobody@example.com", "password": "whatever"}, format="json"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_login_inactive_user_rejected(api_client, create_user, user_password):
    user = create_user(email="inactive@example.com", is_active=False)
    url = reverse("auth-login")

    response = api_client.post(
        url, {"email": user.email, "password": user_password}, format="json"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Token expiry --------------------------------------------------------


def test_expired_access_token_rejected(api_client, regular_user):
    token = AccessToken.for_user(regular_user)
    token.set_exp(lifetime=timedelta(seconds=-1))  # already expired

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = api_client.get(reverse("auth-profile"))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_valid_access_token_accepted(api_client, regular_user):
    token = AccessToken.for_user(regular_user)

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = api_client.get(reverse("auth-profile"))

    assert response.status_code == status.HTTP_200_OK


# --- Profile view/edit (F001) ----------------------------------------------


def test_profile_requires_authentication(api_client):
    response = api_client.get(reverse("auth-profile"))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_profile_returns_own_data(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    response = api_client.get(reverse("auth-profile"))

    assert response.status_code == status.HTTP_200_OK
    assert response.data["email"] == regular_user.email


def test_profile_update_persists_editable_fields(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    response = api_client.patch(
        reverse("auth-profile"),
        {"first_name": "Updated", "phone_number": "+60123456789"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    regular_user.refresh_from_db()
    assert regular_user.first_name == "Updated"
    assert regular_user.phone_number == "+60123456789"


def test_profile_update_cannot_change_role(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    response = api_client.patch(
        reverse("auth-profile"), {"role": UserRole.ADMIN}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    regular_user.refresh_from_db()
    assert regular_user.role == UserRole.USER  # role is read-only, silently ignored


# --- Role-based access control ----------------------------------------------


def test_admin_only_endpoint_forbidden_for_regular_user(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    response = api_client.get(reverse("auth-admin-user-list"))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_only_endpoint_allowed_for_admin(api_client, admin_user, regular_user):
    api_client.force_authenticate(user=admin_user)

    response = api_client.get(reverse("auth-admin-user-list"))

    assert response.status_code == status.HTTP_200_OK
    emails = {row["email"] for row in response.data["results"]}
    assert {admin_user.email, regular_user.email}.issubset(emails)


def test_admin_only_endpoint_rejects_unauthenticated(api_client):
    response = api_client.get(reverse("auth-admin-user-list"))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- Logout (F002) -----------------------------------------------------------


def test_logout_blacklists_refresh_token(api_client, regular_user):
    refresh = RefreshToken.for_user(regular_user)
    api_client.force_authenticate(user=regular_user)

    response = api_client.post(
        reverse("auth-logout"), {"refresh": str(refresh)}, format="json"
    )
    assert response.status_code == status.HTTP_205_RESET_CONTENT

    # The blacklisted refresh token must no longer mint new access tokens.
    api_client.credentials()  # drop auth header, refresh endpoint is AllowAny
    refresh_response = api_client.post(
        reverse("auth-login-refresh"), {"refresh": str(refresh)}, format="json"
    )
    assert refresh_response.status_code == status.HTTP_401_UNAUTHORIZED


def test_logout_requires_authentication(api_client, regular_user):
    refresh = RefreshToken.for_user(regular_user)

    response = api_client.post(
        reverse("auth-logout"), {"refresh": str(refresh)}, format="json"
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_logout_without_refresh_token_is_bad_request(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    response = api_client.post(reverse("auth-logout"), {}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_logout_also_blacklists_the_access_token_used_for_that_request(api_client, regular_user):
    """QA audit H6: the access token that authenticated the logout
    request itself must stop working immediately - not just the refresh
    token. Uses real tokens throughout (not force_authenticate, which
    bypasses JWTAuthentication/request.auth entirely) so this exercises
    the actual enforcement path.
    """
    refresh = RefreshToken.for_user(regular_user)
    access = refresh.access_token
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    response = api_client.post(reverse("auth-logout"), {"refresh": str(refresh)}, format="json")
    assert response.status_code == status.HTTP_205_RESET_CONTENT

    # Same pre-logout access token, reused on a protected endpoint -
    # previously stayed valid until its own natural expiry.
    reuse_response = api_client.get(reverse("auth-profile"))
    assert reuse_response.status_code == status.HTTP_401_UNAUTHORIZED


def test_a_different_users_access_token_is_unaffected_by_this_logout(api_client, regular_user, admin_user):
    other_refresh = RefreshToken.for_user(admin_user)
    other_access = other_refresh.access_token

    own_refresh = RefreshToken.for_user(regular_user)
    own_access = own_refresh.access_token
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {own_access}")
    logout_response = api_client.post(
        reverse("auth-logout"), {"refresh": str(own_refresh)}, format="json"
    )
    assert logout_response.status_code == status.HTTP_205_RESET_CONTENT

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {other_access}")
    response = api_client.get(reverse("auth-profile"))
    assert response.status_code == status.HTTP_200_OK


# --- M21: rate limiting on login/registration --------------------------


def test_repeated_login_attempts_are_throttled(api_client, regular_user, user_password):
    url = reverse("auth-login")
    payload = {"email": regular_user.email, "password": "wrong-password"}

    for _ in range(5):
        response = api_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    throttled_response = api_client.post(url, payload, format="json")
    assert throttled_response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    # Even the CORRECT password is throttled once the limit is hit - this
    # is specifically about request volume, not about repeated failures.
    correct_payload = {"email": regular_user.email, "password": user_password}
    still_throttled = api_client.post(url, correct_payload, format="json")
    assert still_throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS


def test_repeated_registration_attempts_are_throttled(api_client):
    url = reverse("auth-register")

    for i in range(5):
        response = api_client.post(
            url,
            {
                "email": f"throttle{i}@example.com",
                "password": "AnotherStrongPass1!",
                "password2": "AnotherStrongPass1!",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

    throttled_response = api_client.post(
        url,
        {
            "email": "throttle-overflow@example.com",
            "password": "AnotherStrongPass1!",
            "password2": "AnotherStrongPass1!",
        },
        format="json",
    )
    assert throttled_response.status_code == status.HTTP_429_TOO_MANY_REQUESTS


def test_login_and_registration_throttles_are_independent_scopes(api_client, regular_user, user_password):
    login_url = reverse("auth-login")
    register_url = reverse("auth-register")

    for _ in range(5):
        api_client.post(login_url, {"email": regular_user.email, "password": "wrong"}, format="json")

    # Login's own limit is exhausted, but registration has its own
    # separate scope/counter and is unaffected.
    response = api_client.post(
        register_url,
        {
            "email": "still-works@example.com",
            "password": "AnotherStrongPass1!",
            "password2": "AnotherStrongPass1!",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
