"""Tests for the /health endpoint."""

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_service_metadata(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["environment"] == "test"
    assert body["service"]
    assert body["version"]
    assert set(body) == {"status", "service", "version", "environment"}


def test_unknown_route_returns_404(client: TestClient) -> None:
    assert client.get("/does-not-exist").status_code == 404


def test_health_is_documented_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/health" in schema["paths"]
