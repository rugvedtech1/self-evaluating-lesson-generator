"""HTTP client used by the Streamlit UI to talk to the FastAPI backend."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    detail: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class SessionExpiredError(ApiError):
    """Tokens can no longer be refreshed: the user must log in again."""


def _detail(response: httpx.Response) -> str:
    """Turn a backend error response into a sentence a user can read."""
    try:
        data = response.json()
    except ValueError:
        return f"Request failed (HTTP {response.status_code})."
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):  # FastAPI 422
        message = str(detail[0].get("msg", "")).removeprefix("Value error, ")
        return message or "Invalid input."
    return f"Request failed (HTTP {response.status_code})."


def parse_response(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        raise ApiError(_detail(response), response.status_code)
    return response.json() if response.content else None


class BackendClient:
    """Thin wrapper around httpx. Every backend call from the UI goes through here."""

    def __init__(self, base_url: str, timeout: float = 60.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def request(self, method: str, path: str, *, json: Any = None,
                access_token: str | None = None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else None
        try:
            return self._client.request(method, path, json=json, headers=headers)
        except httpx.TimeoutException as exc:
            raise ApiError("The server took too long to respond. Please try again.") from exc
        except httpx.RequestError as exc:
            raise ApiError("Could not reach the server. Is the backend running?") from exc

    # ------------------------------------------------------------ public endpoints
    def check_health(self) -> HealthStatus:
        try:
            response = self._client.get("/health")
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException:
            return HealthStatus(ok=False, detail="Backend did not respond in time.")
        except httpx.HTTPStatusError as exc:
            return HealthStatus(ok=False, detail=f"Backend returned HTTP {exc.response.status_code}.")
        except httpx.RequestError:
            return HealthStatus(ok=False, detail="Could not connect to the backend.")
        except ValueError:
            return HealthStatus(ok=False, detail="Backend returned an invalid (non-JSON) response.")
        return HealthStatus(ok=True, detail="Backend is reachable.", payload=data)

    def login(self, email: str, password: str) -> dict[str, Any]:
        return parse_response(self.request("POST", "/auth/login", json={"email": email, "password": password}))

    def signup(self, email: str, password: str) -> dict[str, Any]:
        return parse_response(self.request("POST", "/auth/signup", json={"email": email, "password": password}))

    def refresh(self, refresh_token: str) -> Tokens:
        data = parse_response(self.request("POST", "/auth/refresh", json={"refresh_token": refresh_token}))
        return Tokens(access_token=data["access_token"], refresh_token=data["refresh_token"])

    def logout(self, access_token: str) -> None:
        try:
            self.request("POST", "/auth/logout", access_token=access_token)
        except ApiError:
            pass  # ending the local session is what matters

    def close(self) -> None:
        self._client.close()


class ChatApi:
    """Authenticated calls. Refreshes an expired access token once, then retries."""

    def __init__(self, client: BackendClient, get_tokens: Callable[[], Tokens | None],
                 save_tokens: Callable[[Tokens], None]) -> None:
        self._client = client
        self._get_tokens = get_tokens
        self._save_tokens = save_tokens

    def _call(self, method: str, path: str, json: Any = None) -> Any:
        tokens = self._get_tokens()
        if tokens is None:
            raise SessionExpiredError("Please log in.")
        response = self._client.request(method, path, json=json, access_token=tokens.access_token)
        if response.status_code == 401:
            try:
                tokens = self._client.refresh(tokens.refresh_token)
            except ApiError as exc:
                if exc.status_code in (400, 401, 403):
                    raise SessionExpiredError("Your session has expired. Please log in again.") from exc
                raise  # e.g. network problem: don't log the user out for that
            self._save_tokens(tokens)
            response = self._client.request(method, path, json=json, access_token=tokens.access_token)
            if response.status_code == 401:
                raise SessionExpiredError("Your session has expired. Please log in again.")
        return parse_response(response)

    def list_chats(self) -> list[dict[str, Any]]:
        return self._call("GET", "/chats")

    def create_chat(self) -> dict[str, Any]:
        return self._call("POST", "/chats", json={})

    def get_chat(self, chat_id: str) -> dict[str, Any]:
        return self._call("GET", f"/chats/{chat_id}")

    def send_message(self, chat_id: str, content: str) -> dict[str, Any]:
        return self._call("POST", f"/chats/{chat_id}/messages", json={"content": content})

    def confirm_profile(self, chat_id: str) -> dict[str, Any]:
        return self._call("POST", f"/chats/{chat_id}/profile/confirm")

    def start_lesson(self, chat_id: str) -> dict[str, Any]:
        return self._call("POST", f"/chats/{chat_id}/lesson-runs")

    def list_prompts(self, component: str = "generator") -> list[dict[str, Any]]:
        return self._call("GET", f"/system/prompts/{component}")

    def list_failure_patterns(self) -> list[dict[str, Any]]:
        return self._call("GET", "/system/failure-patterns")

    def start_evolution(self) -> dict[str, Any]:
        return self._call("POST", "/system/evolve")

    def rollback_prompt(self, component: str = "generator", to_version: int | None = None) -> dict[str, Any]:
        return self._call("POST", f"/system/prompts/{component}/rollback", json={"to_version": to_version})

    def delete_chat(self, chat_id: str) -> None:
        self._call("DELETE", f"/chats/{chat_id}")

    def logout(self) -> None:
        tokens = self._get_tokens()
        if tokens is not None:
            self._client.logout(tokens.access_token)
