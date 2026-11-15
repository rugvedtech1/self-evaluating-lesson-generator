"""Unit tests for SupabaseAuthClient using a fake HTTP transport (no real Supabase)."""

import json
import uuid

import httpx
import pytest

from app.core.exceptions import AuthRejectedError, AuthServiceUnavailableError
from app.services.supabase_auth import SupabaseAuthClient

AUTH_URL = "https://test-project.supabase.co/auth/v1"
KEY = "sb_publishable_test"
USER_ID = str(uuid.uuid4())
USER = {"id": USER_ID, "email": "learner@example.com"}
SESSION = {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600,
           "token_type": "bearer", "user": USER}


def make_client(handler) -> SupabaseAuthClient:
    return SupabaseAuthClient(AUTH_URL, KEY, transport=httpx.MockTransport(handler))


def test_sign_up_returns_session_and_sends_publishable_key() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(path=request.url.path, apikey=request.headers.get("apikey"),
                    body=json.loads(request.content))
        return httpx.Response(200, json=SESSION)

    result = make_client(handler).sign_up("learner@example.com", "correct-horse")
    assert result.session is not None
    assert result.session.access_token == "acc"
    assert str(result.user.id) == USER_ID
    assert seen == {"path": "/auth/v1/signup", "apikey": KEY,
                    "body": {"email": "learner@example.com", "password": "correct-horse"}}


def test_sign_up_without_session_means_confirmation_required() -> None:
    result = make_client(lambda request: httpx.Response(200, json=USER)).sign_up("a@example.com", "pw-12345678")
    assert result.session is None
    assert str(result.user.id) == USER_ID


def test_login_uses_password_grant() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(path=request.url.path, grant=request.url.params.get("grant_type"))
        return httpx.Response(200, json=SESSION)

    session = make_client(handler).sign_in_with_password("learner@example.com", "pw")
    assert session.refresh_token == "ref"
    assert seen == {"path": "/auth/v1/token", "grant": "password"}


def test_invalid_credentials_raise_rejected_with_message() -> None:
    body = {"code": 400, "error_code": "invalid_credentials", "msg": "Invalid login credentials"}
    client = make_client(lambda request: httpx.Response(400, json=body))
    with pytest.raises(AuthRejectedError, match="Invalid login credentials") as info:
        client.sign_in_with_password("learner@example.com", "wrong")
    assert info.value.status_code == 400


def test_rate_limit_keeps_status_429() -> None:
    client = make_client(lambda request: httpx.Response(429, json={"msg": "email rate limit exceeded"}))
    with pytest.raises(AuthRejectedError) as info:
        client.sign_up("a@example.com", "pw-12345678")
    assert info.value.status_code == 429


def test_server_error_is_service_unavailable() -> None:
    client = make_client(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(AuthServiceUnavailableError):
        client.sign_in_with_password("a@example.com", "pw")


def test_network_error_is_service_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AuthServiceUnavailableError):
        make_client(handler).sign_in_with_password("a@example.com", "pw")


def test_timeout_is_service_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(AuthServiceUnavailableError, match="timed out"):
        make_client(handler).sign_in_with_password("a@example.com", "pw")


def test_refresh_uses_refresh_token_grant() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(grant=request.url.params.get("grant_type"), body=json.loads(request.content))
        return httpx.Response(200, json=SESSION)

    make_client(handler).refresh_session("ref-old")
    assert seen == {"grant": "refresh_token", "body": {"refresh_token": "ref-old"}}


def test_logout_sends_bearer_token_with_local_scope() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(path=request.url.path, auth=request.headers.get("authorization"),
                    scope=request.url.params.get("scope"))
        return httpx.Response(204)

    make_client(handler).sign_out("acc-token")
    assert seen == {"path": "/auth/v1/logout", "auth": "Bearer acc-token", "scope": "local"}


def test_malformed_success_response_is_service_unavailable() -> None:
    client = make_client(lambda request: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(AuthServiceUnavailableError):
        client.sign_in_with_password("a@example.com", "pw")
