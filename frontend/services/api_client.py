"""HTTP client used by the Streamlit UI to talk to the FastAPI backend."""

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    detail: str
    payload: dict[str, Any] = field(default_factory=dict)


class BackendClient:
    """Thin wrapper around httpx. Every backend call from the UI goes through here."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,  # injected in tests
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def check_health(self) -> HealthStatus:
        """Call GET /health and convert any failure into a readable status."""
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

    def close(self) -> None:
        self._client.close()
