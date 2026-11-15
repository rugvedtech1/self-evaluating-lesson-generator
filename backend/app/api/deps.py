"""Shared FastAPI dependencies: database session, auth client, current user."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AuthServiceUnavailableError, TokenValidationError
from app.core.security import AuthenticatedUser, TokenVerifier
from app.db.session import get_db
from app.services.supabase_auth import SupabaseAuthClient

_bearer_scheme = HTTPBearer(auto_error=False, description="Supabase access token")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


def _service_unavailable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


# ------------------------------------------------------------------ token verifier
@lru_cache
def _build_token_verifier(issuer: str, audience: str) -> TokenVerifier:
    # One JWKS client per process; public keys are cached and refetched on unknown key ids.
    jwks_client = PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_jwk_set=True, lifespan=600, timeout=5)
    return TokenVerifier(
        issuer=issuer,
        audience=audience,
        key_resolver=lambda token: jwks_client.get_signing_key_from_jwt(token).key,
    )


def get_token_verifier() -> TokenVerifier:
    settings = get_settings()
    if not settings.supabase_auth_url:
        raise _service_unavailable("Authentication is not configured.")
    return _build_token_verifier(settings.supabase_auth_url, settings.jwt_audience)


# ------------------------------------------------------------------ auth client
@lru_cache
def _build_auth_client(auth_url: str, publishable_key: str, timeout: float) -> SupabaseAuthClient:
    return SupabaseAuthClient(auth_url, publishable_key, timeout=timeout)


def get_auth_client() -> SupabaseAuthClient:
    settings = get_settings()
    if not settings.supabase_auth_url or settings.supabase_publishable_key is None:
        raise _service_unavailable("Authentication is not configured.")
    return _build_auth_client(
        settings.supabase_auth_url,
        settings.supabase_publishable_key.get_secret_value(),
        settings.auth_request_timeout_seconds,
    )


# ------------------------------------------------------------------ current user
def get_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _unauthorized("Missing bearer token.")
    return credentials.credentials


def get_current_user(
    token: Annotated[str, Depends(get_bearer_token)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> AuthenticatedUser:
    """The ONLY way routes learn who the caller is: from a verified token."""
    try:
        return verifier.verify(token)
    except TokenValidationError as exc:
        raise _unauthorized(str(exc)) from exc
    except AuthServiceUnavailableError as exc:
        raise _service_unavailable(str(exc)) from exc


# Convenient type aliases for route signatures
DbSession = Annotated[Session, Depends(get_db)]
AuthClient = Annotated[SupabaseAuthClient, Depends(get_auth_client)]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
BearerToken = Annotated[str, Depends(get_bearer_token)]
