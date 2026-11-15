"""Who is calling? Check the access token from Keycloak on every API request.

The web app signs the user in at Keycloak (OpenID Connect) and sends the access token
with every request:

    Authorization: Bearer <JWT>

We check the token ourselves, without asking Keycloak each time:

- signature: made by Keycloak's key (public keys from the JWKS URL, cached)
- issuer: our Keycloak realm
- audience: this API ("bizpartnercheck-api")
- expiry: not expired (30 s tolerance for clocks that differ a little)

Any problem gives 401 in the uniform error format. If Keycloak's keys cannot be
loaded, we answer 503: the token may be fine, we just cannot check it right now.

Details: docs/authentication.md
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import error_body

DEFAULT_ISSUER = "http://localhost:8080/realms/bizpartnercheck"
DEFAULT_AUDIENCE = "bizpartnercheck-api"
ALGORITHMS = ["RS256"]
LEEWAY_SECONDS = 30


ORG_ADMIN_ROLE = "org-admin"
# Runs the platform for all customers (e.g. data source imports); not a customer role.
PLATFORM_ADMIN_ROLE = "platform-admin"


@dataclass(frozen=True)
class CurrentUser:
    id: str  # Keycloak user ID ("sub"), stable even if the e-mail changes
    email: str | None
    name: str | None
    roles: frozenset[str] = frozenset()  # Keycloak realm roles, e.g. "org-admin"


class TokenError(Exception):
    """The token is missing, broken, expired or not for us."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthUnavailable(Exception):
    """Keycloak's public keys could not be loaded."""


# Finds the public key for a token (looks at the "kid" in the token header).
KeyResolver = Callable[[str], Any]


class TokenVerifier:
    def __init__(self, issuer: str, audience: str, resolve_key: KeyResolver) -> None:
        self.issuer = issuer
        self.audience = audience
        self._resolve_key = resolve_key

    def verify(self, token: str) -> CurrentUser:
        try:
            key = self._resolve_key(token)
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthUnavailable() from exc
        except (jwt.PyJWKClientError, jwt.InvalidTokenError) as exc:
            raise TokenError(
                "invalid_token", "The sign-in token is not valid."
            ) from exc
        except (jwt.PyJWTError, ValueError) as exc:
            # Keycloak answered, but not with a usable key set (empty, HTML, wrong key type).
            raise AuthUnavailable() from exc

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.InvalidKeyError as exc:
            # The key from Keycloak cannot be used for RS256 (wrong key type).
            raise AuthUnavailable() from exc
        except jwt.ExpiredSignatureError as exc:
            raise TokenError(
                "token_expired", "Your session has expired. Please sign in again."
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise TokenError(
                "invalid_token", "The sign-in token is not valid."
            ) from exc

        # Keycloak marks access tokens with typ "Bearer"; ID or refresh tokens are not accepted.
        if claims.get("typ", "Bearer") != "Bearer":
            raise TokenError("invalid_token", "The sign-in token is not valid.")

        realm_access = claims.get("realm_access")
        roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
        if not isinstance(roles, list):
            roles = []  # anything else is not from our Keycloak: no roles
        return CurrentUser(
            id=claims["sub"],
            email=claims.get("email"),
            name=claims.get("name") or claims.get("preferred_username"),
            roles=frozenset(role for role in roles if isinstance(role, str)),
        )


def jwks_key_resolver(jwks_url: str) -> KeyResolver:
    # Keys are cached for 10 minutes; an unknown "kid" (Keycloak rotated its key)
    # makes the client load the key set again.
    client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600, timeout=5)

    def resolve(token: str) -> Any:
        return client.get_signing_key_from_jwt(token).key

    return resolve


@lru_cache
def get_token_verifier() -> TokenVerifier:
    """FastAPI dependency. Settings come from environment variables (see .env.example)."""
    issuer = os.environ.get("OIDC_ISSUER") or DEFAULT_ISSUER
    audience = os.environ.get("OIDC_AUDIENCE") or DEFAULT_AUDIENCE
    # Inside Docker the API may reach Keycloak under another host name than the browser.
    jwks_url = (
        os.environ.get("OIDC_JWKS_URL") or f"{issuer}/protocol/openid-connect/certs"
    )
    return TokenVerifier(issuer, audience, jwks_key_resolver(jwks_url))


def _unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail=error_body(code, message)["detail"],
        headers={"WWW-Authenticate": "Bearer"},
    )


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> CurrentUser:
    """FastAPI dependency: the signed-in user, or 401."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("not_authenticated", "Please sign in.")
    try:
        return verifier.verify(credentials.credentials)
    except TokenError as exc:
        raise _unauthorized(exc.code, exc.message) from exc
    except AuthUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_body(
                "auth_unavailable",
                "Sign-in cannot be checked right now. Please try again in a moment.",
            )["detail"],
        ) from exc


AuthenticatedUser = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(role: str, message: str) -> Callable[[CurrentUser], CurrentUser]:
    """FastAPI dependency factory: the signed-in user must have `role`, otherwise 403."""

    def check(user: AuthenticatedUser) -> CurrentUser:
        if role not in user.roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=error_body("forbidden", message)["detail"],
            )
        return user

    return check


OrgAdmin = Annotated[
    CurrentUser,
    Depends(require_role(ORG_ADMIN_ROLE, "Only organisation admins can do this.")),
]

PlatformAdmin = Annotated[
    CurrentUser,
    Depends(require_role(PLATFORM_ADMIN_ROLE, "Only platform admins can do this.")),
]
