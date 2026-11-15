"""Tests for BackendClient using a fake HTTP transport (no real backend needed)."""

import httpx

from services.api_client import BackendClient

BASE_URL = "http://backend.test"


def make_client(handler) -> BackendClient:
    return BackendClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))


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
