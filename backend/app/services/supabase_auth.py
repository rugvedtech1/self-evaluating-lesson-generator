"""Thin, stateless HTTP client for Supabase Auth.

Supabase Auth stores identities and password hashes; we never do.
The client holds no user session, so it is safe to share across requests.
"""

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.exceptions import AuthRejectedError, AuthServiceUnavailableError


@dataclass(frozen=True)
class AuthUser:
    id: uuid.UUID
    email: str | None


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str
    user: AuthUser


@dataclass(frozen=True)
class SignUpResult:
    user: AuthUser
    session: AuthSession | None  # None when email confirmation is required


def _parse_user(data: dict[str, Any]) -> AuthUser:
    return AuthUser(id=uuid.UUID(str(data["id"])), email=data.get("email"))


def _parse_session(data: dict[str, Any]) -> AuthSession:
    return AuthSession(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_in=int(data.get("expires_in", 3600)),
        token_type=data.get("token_type", "bearer"),
        user=_parse_user(data["user"]),
    )


def _error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return "Authentication request was rejected."
    if isinstance(data, dict):
        for key in ("msg", "message", "error_description", "error"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    return "Authentication request was rejected."


class SupabaseAuthClient:
    def __init__(
        self,
        auth_url: str,
        publishable_key: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,  # injected in tests
    ) -> None:
        self._client = httpx.Client(
            base_url=auth_url,
            headers={"apikey": publishable_key},
            timeout=timeout,
            transport=transport,
        )

    # ------------------------------------------------------------ internals
    def _post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.post(path, json=json, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise AuthServiceUnavailableError("Authentication service timed out.") from exc
        except httpx.RequestError as exc:
            raise AuthServiceUnavailableError("Could not reach the authentication service.") from exc

        if response.status_code >= 500:
            raise AuthServiceUnavailableError(f"Authentication service error (HTTP {response.status_code}).")
        if response.status_code >= 400:
            raise AuthRejectedError(_error_message(response), response.status_code)
        return response

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise AuthServiceUnavailableError("Authentication service returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise AuthServiceUnavailableError("Authentication service returned an unexpected response.")
        return data

    # ------------------------------------------------------------ public API
    def sign_up(self, email: str, password: str) -> SignUpResult:
        data = self._json(self._post("/signup", json={"email": email, "password": password}))
        try:
            if "access_token" in data:
                session = _parse_session(data)
                return SignUpResult(user=session.user, session=session)
            return SignUpResult(user=_parse_user(data), session=None)
        except (KeyError, ValueError, TypeError) as exc:
            raise AuthServiceUnavailableError("Authentication service returned an unexpected response.") from exc

    def sign_in_with_password(self, email: str, password: str) -> AuthSession:
        response = self._post("/token", params={"grant_type": "password"},
                              json={"email": email, "password": password})
        return self._session_from(response)

    def refresh_session(self, refresh_token: str) -> AuthSession:
        response = self._post("/token", params={"grant_type": "refresh_token"},
                              json={"refresh_token": refresh_token})
        return self._session_from(response)

    def sign_out(self, access_token: str) -> None:
        # scope=local: end only this session, not the user's other devices.
        self._post("/logout", params={"scope": "local"},
                   headers={"Authorization": f"Bearer {access_token}"})

    def _session_from(self, response: httpx.Response) -> AuthSession:
        try:
            return _parse_session(self._json(response))
        except (KeyError, ValueError, TypeError) as exc:
            raise AuthServiceUnavailableError("Authentication service returned an unexpected response.") from exc

    def close(self) -> None:
        self._client.close()
