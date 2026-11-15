"""Tests for the frontend API client using a fake HTTP transport (no real backend)."""

import json

import httpx
import pytest

from services.api_client import ApiError, BackendClient, ChatApi, SessionExpiredError, Tokens

BASE_URL = "http://backend.test"


def make_client(handler) -> BackendClient:
    return BackendClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))


class TokenStore:
    def __init__(self, tokens: Tokens | None) -> None:
        self.tokens = tokens

    def get(self) -> Tokens | None:
        return self.tokens

    def save(self, tokens: Tokens) -> None:
        self.tokens = tokens


# ------------------------------------------------------------------ health
def test_health_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok", "service": "api"})

    status = make_client(handler).check_health()
    assert status.ok is True
    assert status.payload["status"] == "ok"


def test_health_server_error() -> None:
    status = make_client(lambda request: httpx.Response(500)).check_health()
    assert status.ok is False
    assert "500" in status.detail


def test_health_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    status = make_client(handler).check_health()
    assert status.ok is False
    assert "connect" in status.detail.lower()


def test_health_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    status = make_client(handler).check_health()
    assert status.ok is False
    assert "time" in status.detail.lower()


def test_health_invalid_json() -> None:
    status = make_client(lambda request: httpx.Response(200, text="not json")).check_health()
    assert status.ok is False
    assert "json" in status.detail.lower()


# ------------------------------------------------------------------ auth
def test_login_returns_session_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/login"
        assert json.loads(request.content) == {"email": "a@example.com", "password": "pw"}
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "r",
                                         "user": {"email": "a@example.com"}})

    assert make_client(handler).login("a@example.com", "pw")["access_token"] == "a"


def test_login_error_shows_backend_detail() -> None:
    client = make_client(lambda request: httpx.Response(401, json={"detail": "Invalid login credentials"}))
    with pytest.raises(ApiError, match="Invalid login credentials") as info:
        client.login("a@example.com", "wrong")
    assert info.value.status_code == 401


def test_validation_error_message_is_readable() -> None:
    body = {"detail": [{"loc": ["body", "password"], "type": "value_error",
                        "msg": "Value error, Password must be between 8 and 72 characters."}]}
    client = make_client(lambda request: httpx.Response(422, json=body))
    with pytest.raises(ApiError) as info:
        client.signup("a@example.com", "short")
    assert info.value.message == "Password must be between 8 and 72 characters."


def test_unreachable_backend_raises_friendly_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ApiError, match="Could not reach"):
        make_client(handler).login("a@example.com", "pw")


def test_logout_ignores_backend_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    make_client(handler).logout("a")  # must not raise


# ------------------------------------------------------------------ authenticated calls
def test_expired_access_token_is_refreshed_and_request_retried() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization")
        seen.append((request.url.path, auth))
        if request.url.path == "/auth/refresh":
            return httpx.Response(200, json={"access_token": "new-a", "refresh_token": "new-r"})
        if auth == "Bearer old-a":
            return httpx.Response(401, json={"detail": "Token has expired."})
        return httpx.Response(200, json=[{"id": "c1"}])

    store = TokenStore(Tokens("old-a", "old-r"))
    api = ChatApi(make_client(handler), store.get, store.save)
    assert api.list_chats() == [{"id": "c1"}]
    assert store.tokens == Tokens("new-a", "new-r")
    assert seen == [("/chats", "Bearer old-a"), ("/auth/refresh", None), ("/chats", "Bearer new-a")]


def test_rejected_refresh_means_session_expired() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/refresh":
            return httpx.Response(401, json={"detail": "Invalid Refresh Token"})
        return httpx.Response(401, json={"detail": "Token has expired."})

    store = TokenStore(Tokens("old-a", "old-r"))
    with pytest.raises(SessionExpiredError):
        ChatApi(make_client(handler), store.get, store.save).list_chats()


def test_network_failure_during_refresh_does_not_log_user_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/refresh":
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(401, json={"detail": "Token has expired."})

    store = TokenStore(Tokens("old-a", "old-r"))
    with pytest.raises(ApiError) as info:
        ChatApi(make_client(handler), store.get, store.save).list_chats()
    assert not isinstance(info.value, SessionExpiredError)


def test_missing_tokens_means_session_expired() -> None:
    api = ChatApi(make_client(lambda request: httpx.Response(200, json=[])), lambda: None, lambda t: None)
    with pytest.raises(SessionExpiredError):
        api.list_chats()


def test_send_message_posts_content_with_bearer_token() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(method=request.method, path=request.url.path,
                    auth=request.headers.get("authorization"), body=json.loads(request.content))
        return httpx.Response(201, json={"ok": True})

    ChatApi(make_client(handler), lambda: Tokens("a", "r"), lambda t: None).send_message("chat-1", "Hello")
    assert seen == {"method": "POST", "path": "/chats/chat-1/messages",
                    "auth": "Bearer a", "body": {"content": "Hello"}}


def test_start_lesson_posts_to_lesson_runs() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(method=request.method, path=request.url.path)
        return httpx.Response(202, json={"id": "run-1", "status": "running"})

    result = ChatApi(make_client(handler), lambda: Tokens("a", "r"), lambda t: None).start_lesson("chat-1")
    assert result["status"] == "running"
    assert seen == {"method": "POST", "path": "/chats/chat-1/lesson-runs"}
