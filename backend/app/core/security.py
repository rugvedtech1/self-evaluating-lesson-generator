"""Verification of Supabase access tokens (JWTs) using Supabase's public signing keys."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from app.core.exceptions import AuthServiceUnavailableError, TokenValidationError

# Asymmetric algorithms only. Never 'none' or HS256 here: this blocks
# algorithm-confusion attacks (forging an HS256 token using the public key).
ALLOWED_ALGORITHMS = ["ES256", "RS256"]

# Given a raw token, return the public key that should have signed it.
KeyResolver = Callable[[str], Any]


@dataclass(frozen=True)
class AuthenticatedUser:
    id: uuid.UUID
    email: str | None
    session_id: str | None = None


class TokenVerifier:
    """Validates signature, expiry, issuer, audience and role of an access token."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        key_resolver: KeyResolver,
        leeway_seconds: int = 10,  # tolerate small clock differences between servers
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._key_resolver = key_resolver
        self._leeway = leeway_seconds

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            key = self._key_resolver(token)
        except PyJWKClientConnectionError as exc:  # JWKS endpoint down: technical failure
            raise AuthServiceUnavailableError("Could not fetch token signing keys.") from exc
        except (PyJWKClientError, jwt.InvalidTokenError) as exc:  # unknown key id / garbage token
            raise TokenValidationError("Token is not signed by a trusted key.") from exc

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenValidationError("Token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenValidationError("Invalid token.") from exc

        if claims.get("role") != "authenticated":
            raise TokenValidationError("Token is not for an authenticated user.")
        try:
            user_id = uuid.UUID(str(claims["sub"]))
        except ValueError as exc:
            raise TokenValidationError("Token subject is not a valid user id.") from exc

        return AuthenticatedUser(id=user_id, email=claims.get("email"), session_id=claims.get("session_id"))
