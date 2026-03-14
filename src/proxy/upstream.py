# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "httpx>=0.28",
# ]
# ///
"""Upstream HTTP client for forwarding requests to the Slack Web API.

Wraps httpx.AsyncClient with connection pooling, timeout handling,
and structured error mapping. Slack 4xx/5xx responses are forwarded
as-is; transport-level failures produce 502/500 JSON error bodies
in Slack-compatible ``{"ok": false, ...}`` format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

SLACK_BASE_URL = "https://slack.com/api/"


@dataclass(frozen=True)
class UpstreamResponse:
    """Immutable container for an upstream HTTP response."""

    body: bytes
    status_code: int
    content_type: str
    headers: dict[str, str]


def _error_json(error: str, detail: str) -> bytes:
    return json.dumps({"ok": False, "error": error, "detail": detail}).encode()


def _internal_error_json() -> bytes:
    return json.dumps(
        {"ok": False, "error": "proxy_internal_error", "detail": "internal server error"}
    ).encode()


class UpstreamClient:
    """Async HTTP client that forwards requests to the Slack Web API.

    Uses connection pooling via ``httpx.AsyncClient`` for efficient
    reuse of TCP connections across requests.

    Parameters
    ----------
    timeout:
        Request timeout in seconds (default 30).
    max_connections:
        Maximum number of concurrent connections in the pool (default 20).
    """

    def __init__(self, timeout: float = 30.0, max_connections: int = 20) -> None:
        self._client = httpx.AsyncClient(
            base_url=SLACK_BASE_URL,
            limits=httpx.Limits(max_connections=max_connections),
            timeout=httpx.Timeout(timeout),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def forward_get(
        self, method: str, params: dict[str, str], auth_header: str
    ) -> UpstreamResponse:
        """Forward a GET request to ``SLACK_BASE_URL/{method}``."""
        try:
            resp = await self._client.get(
                method,
                params=params,
                headers={"Authorization": auth_header},
            )
            return self._wrap(resp)
        except httpx.TimeoutException as exc:
            return self._transport_error("proxy_upstream_timeout", exc)
        except httpx.ConnectError as exc:
            return self._transport_error("proxy_upstream_unreachable", exc)
        except httpx.HTTPError as exc:
            return self._transport_error("proxy_upstream_error", exc)
        except Exception:
            return UpstreamResponse(
                body=_internal_error_json(),
                status_code=500,
                content_type="application/json",
                headers={},
            )

    async def forward_post(
        self,
        method: str,
        body: bytes,
        auth_header: str,
        content_type: str,
    ) -> UpstreamResponse:
        """Forward a POST request to ``SLACK_BASE_URL/{method}``."""
        try:
            resp = await self._client.post(
                method,
                content=body,
                headers={
                    "Authorization": auth_header,
                    "Content-Type": content_type,
                },
            )
            return self._wrap(resp)
        except httpx.TimeoutException as exc:
            return self._transport_error("proxy_upstream_timeout", exc)
        except httpx.ConnectError as exc:
            return self._transport_error("proxy_upstream_unreachable", exc)
        except httpx.HTTPError as exc:
            return self._transport_error("proxy_upstream_error", exc)
        except Exception:
            return UpstreamResponse(
                body=_internal_error_json(),
                status_code=500,
                content_type="application/json",
                headers={},
            )

    async def close(self) -> None:
        """Shut down the underlying connection pool."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap(resp: httpx.Response) -> UpstreamResponse:
        """Convert an httpx response into an ``UpstreamResponse``."""
        return UpstreamResponse(
            body=resp.content,
            status_code=resp.status_code,
            content_type=resp.headers.get("content-type", "application/json"),
            headers=dict(resp.headers),
        )

    @staticmethod
    def _transport_error(error_code: str, exc: Exception) -> UpstreamResponse:
        return UpstreamResponse(
            body=_error_json(error_code, str(exc)),
            status_code=502,
            content_type="application/json",
            headers={},
        )
