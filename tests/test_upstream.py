# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "httpx>=0.28",
#     "pytest>=8",
#     "pytest-asyncio>=0.24",
#     "pytest-httpx>=0.35",
# ]
# ///
"""Tests for src/proxy/upstream.py — UpstreamClient."""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from src.proxy.upstream import UpstreamClient, UpstreamResponse

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest_asyncio.fixture
async def client() -> UpstreamClient:
    uc = UpstreamClient(timeout=5.0, max_connections=5)
    yield uc
    await uc.close()


# ------------------------------------------------------------------
# Successful forwarding
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_get_success(client: UpstreamClient, httpx_mock) -> None:
    """GET forwarded to Slack returns the upstream body and status."""
    payload = json.dumps({"ok": True, "channels": []}).encode()
    httpx_mock.add_response(
        url=httpx.URL("https://slack.com/api/conversations.list?limit=10"),
        content=payload,
        status_code=200,
        headers={"content-type": "application/json; charset=utf-8"},
    )

    resp = await client.forward_get(
        "conversations.list", {"limit": "10"}, "Bearer xoxb-test"
    )

    assert isinstance(resp, UpstreamResponse)
    assert resp.status_code == 200
    assert resp.body == payload
    assert "application/json" in resp.content_type

    # Verify auth header was forwarded
    request = httpx_mock.get_request()
    assert request.headers["authorization"] == "Bearer xoxb-test"


@pytest.mark.asyncio
async def test_forward_post_success(client: UpstreamClient, httpx_mock) -> None:
    """POST forwarded to Slack returns the upstream body and status."""
    req_body = json.dumps({"channel": "C123", "text": "hello"}).encode()
    resp_payload = json.dumps({"ok": True, "ts": "1234567890.123456"}).encode()
    httpx_mock.add_response(
        url="https://slack.com/api/chat.postMessage",
        content=resp_payload,
        status_code=200,
        headers={"content-type": "application/json; charset=utf-8"},
    )

    resp = await client.forward_post(
        "chat.postMessage", req_body, "Bearer xoxb-test", "application/json"
    )

    assert resp.status_code == 200
    assert resp.body == resp_payload

    request = httpx_mock.get_request()
    assert request.headers["authorization"] == "Bearer xoxb-test"
    assert request.headers["content-type"] == "application/json"
    assert request.content == req_body


# ------------------------------------------------------------------
# Transport errors → 502
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_returns_502(client: UpstreamClient, httpx_mock) -> None:
    """Upstream timeout produces 502 with proxy_upstream_timeout."""
    httpx_mock.add_exception(
        httpx.ReadTimeout("timed out"),
        url="https://slack.com/api/auth.test",
    )

    resp = await client.forward_get("auth.test", {}, "Bearer xoxb-test")

    assert resp.status_code == 502
    body = json.loads(resp.body)
    assert body["ok"] is False
    assert body["error"] == "proxy_upstream_timeout"
    assert "timed out" in body["detail"]


@pytest.mark.asyncio
async def test_connect_error_returns_502(client: UpstreamClient, httpx_mock) -> None:
    """DNS failure / connection refused produces 502 with proxy_upstream_unreachable."""
    httpx_mock.add_exception(
        httpx.ConnectError("Name or service not known"),
        url="https://slack.com/api/auth.test",
    )

    resp = await client.forward_get("auth.test", {}, "Bearer xoxb-test")

    assert resp.status_code == 502
    body = json.loads(resp.body)
    assert body["ok"] is False
    assert body["error"] == "proxy_upstream_unreachable"


@pytest.mark.asyncio
async def test_connection_refused_returns_502(
    client: UpstreamClient, httpx_mock
) -> None:
    """Connection refused (a ConnectError variant) produces 502."""
    httpx_mock.add_exception(
        httpx.ConnectError("[Errno 111] Connection refused"),
        url="https://slack.com/api/conversations.list",
    )

    resp = await client.forward_get(
        "conversations.list", {}, "Bearer xoxb-test"
    )

    assert resp.status_code == 502
    body = json.loads(resp.body)
    assert body["ok"] is False
    assert body["error"] == "proxy_upstream_unreachable"
    assert "Connection refused" in body["detail"]


# ------------------------------------------------------------------
# Slack 4xx / 5xx forwarded as-is
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_4xx_forwarded_as_is(client: UpstreamClient, httpx_mock) -> None:
    """Slack 429 (rate limit) is forwarded with original status and body."""
    payload = json.dumps({"ok": False, "error": "ratelimited"}).encode()
    httpx_mock.add_response(
        url="https://slack.com/api/conversations.history",
        content=payload,
        status_code=429,
        headers={
            "content-type": "application/json",
            "retry-after": "30",
        },
    )

    resp = await client.forward_get(
        "conversations.history", {}, "Bearer xoxb-test"
    )

    assert resp.status_code == 429
    assert resp.body == payload
    body = json.loads(resp.body)
    assert body["ok"] is False
    assert body["error"] == "ratelimited"


@pytest.mark.asyncio
async def test_5xx_forwarded_as_is(client: UpstreamClient, httpx_mock) -> None:
    """Slack 500 is forwarded with original status and body."""
    payload = b"internal server error"
    httpx_mock.add_response(
        url="https://slack.com/api/chat.postMessage",
        content=payload,
        status_code=500,
        headers={"content-type": "text/plain"},
    )

    resp = await client.forward_post(
        "chat.postMessage",
        b'{"channel":"C1","text":"hi"}',
        "Bearer xoxb-test",
        "application/json",
    )

    assert resp.status_code == 500
    assert resp.body == payload


# ------------------------------------------------------------------
# Internal exception → 500
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unexpected_exception_returns_500(
    client: UpstreamClient, monkeypatch
) -> None:
    """An unexpected non-httpx exception produces 500 with no internal details."""

    async def _explode(*args, **kwargs):
        raise RuntimeError("something broke internally")

    monkeypatch.setattr(client._client, "get", _explode)

    resp = await client.forward_get("auth.test", {}, "Bearer xoxb-test")

    assert resp.status_code == 500
    body = json.loads(resp.body)
    assert body["ok"] is False
    assert body["error"] == "proxy_internal_error"
    # Must NOT leak the internal "something broke internally" message
    assert "something broke" not in body["detail"]
    assert body["detail"] == "internal server error"


# ------------------------------------------------------------------
# UpstreamResponse is frozen
# ------------------------------------------------------------------


def test_upstream_response_is_frozen() -> None:
    """UpstreamResponse instances are immutable."""
    resp = UpstreamResponse(
        body=b"test",
        status_code=200,
        content_type="text/plain",
        headers={},
    )
    with pytest.raises(AttributeError):
        resp.status_code = 500  # type: ignore[misc]
