"""QA audit H6: simplejwt's access tokens are stateless by design, so its
own JWTAuthentication never consults the blacklist for them -
OutstandingToken/BlacklistedToken rows are normally only ever created
for REFRESH tokens (via RefreshToken.blacklist(), called on logout and
during rotation). That meant a pre-logout access token kept working for
the rest of its own lifetime even after logout - "logged out" wasn't
actually true until that token separately expired on its own (up to
ACCESS_TOKEN_LIFETIME later).

LogoutView now also blacklists the access token used for the very
request that triggered it (see apps.users.views.LogoutView), reusing
the SAME BlacklistedToken/OutstandingToken tables simplejwt already
ships with rather than inventing a parallel mechanism. This
authentication class is what actually enforces that: every authenticated
request now also checks whether its own access token's jti has been
blacklisted, the same way refresh-token rotation already does
internally (Token.check_blacklist(), which this mirrors for access
tokens specifically since simplejwt's own method is refresh-token-only).
"""

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken


class BlacklistAwareJWTAuthentication(JWTAuthentication):
    def get_validated_token(self, raw_token):
        validated_token = super().get_validated_token(raw_token)
        jti = validated_token.get("jti")
        if jti and BlacklistedToken.objects.filter(token__jti=jti).exists():
            raise InvalidToken("Token is blacklisted")
        return validated_token
