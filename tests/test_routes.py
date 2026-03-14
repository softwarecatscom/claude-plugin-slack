# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "fastapi>=0.115",
#     "httpx>=0.28",
#     "pytest>=8",
#     "pytest-asyncio>=0.24",
#     "respx>=0.22",
#     "stoolap-python>=0.2",
# ]
# ///
"""Tests for src/proxy/routes.py — proxy route handlers."""

from __future__ import annotations

import json
import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from proxy.cache import CacheEngine
from proxy.constants import VERSION
from proxy.routes import router
from proxy.upstream import UpstreamClient


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _make_app(cache: CacheEngine, upstream: UpstreamClient) -> FastAPI:
    """Build a FastAPI app wired with the given cache and upstream."""
    app = FastAPI()
    app.include_router(router)
    app.state.cache = cache
    app.state.upstream = upstream
    app.state.config = None
    return app


@pytest.fixture()
def cache() -> CacheEngine:
    """In-memory Stoolap cache engine."""
    return CacheEngine(db_path=":memory:", default_ttl=60)


@pytest.fixture()
def upstream() -> UpstreamClient:
    """Real UpstreamClient (upstream calls mocked via respx)."""
    return UpstreamClient(timeout=5.0, max_connections=5)


@pytest.fixture()
def app(cache: CacheEngine, upstream: UpstreamClient) -> FastAPI:
    return _make_app(cache, upstream)


@pytest.fixture()
async def client(app: FastAPI):
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ------------------------------------------------------------------
# GET: cacheable MISS then HIT
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cacheable_miss_then_hit(client: AsyncClient) -> None:
    """First GET is a MISS (forwarded upstream), second is a HIT."""
    payload = json.dumps({"ok": True, "messages": []})

    with respx.mock:
        respx.get("https://slack.com/api/conversations.history").mock(
            return_value=httpx.Response(
                200,
                content=payload.encode(),
                headers={"content-type": "application/json"},
            )
        )

        # First request — MISS
        r1 = await client.get(
            "/api/conversations.history",
            params={"channel": "C123"},
            headers={"Authorization": "Bearer xoxb-test"},
        )
        assert r1.status_code == 200
        assert r1.headers["x-proxy-cache"] == "MISS"
        assert json.loads(r1.content) == {"ok": True, "messages": []}

    # Second request — HIT (no upstream mock needed)
    r2 = await client.get(
        "/api/conversations.history",
        params={"channel": "C123"},
        headers={"Authorization": "Bearer xoxb-test"},
    )
    assert r2.status_code == 200
    assert r2.headers["x-proxy-cache"] == "HIT"
    assert "x-proxy-cache-age" in r2.headers
    assert int(r2.headers["x-proxy-cache-age"]) >= 0
    assert json.loads(r2.content) == {"ok": True, "messages": []}


# ------------------------------------------------------------------
# GET: non-cacheable pass-through
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_non_cacheable_passthrough(client: AsyncClient) -> None:
    """A method not in CACHEABLE_METHODS is forwarded without caching."""
    payload = json.dumps({"ok": True, "url": "https://files.slack.com/..."})

    with respx.mock:
        respx.get("https://slack.com/api/files.info").mock(
            return_value=httpx.Response(
                200,
                content=payload.encode(),
                headers={"content-type": "application/json"},
            )
        )

        resp = await client.get(
            "/api/files.info",
            params={"file": "F123"},
            headers={"Authorization": "Bearer xoxb-test"},
        )

    assert resp.status_code == 200
    assert resp.headers["x-proxy-cache"] == "PASS"
    assert json.loads(resp.content)["ok"] is True


# ------------------------------------------------------------------
# POST: forward with invalidation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_forward_with_invalidation(
    client: AsyncClient, cache: CacheEngine
) -> None:
    """POST to an invalidating method clears relevant cache entries."""
    # Pre-populate cache
    cache.store(
        method="conversations.history",
        params={"channel": "C123"},
        channel="C123",
        thread_ts=None,
        body=b'{"ok": true, "messages": []}',
        status_code=200,
        content_type="application/json",
    )
    assert cache.count() == 1

    post_resp_payload = json.dumps(
        {"ok": True, "channel": "C123", "ts": "1234567890.123456"}
    )

    with respx.mock:
        respx.post("https://slack.com/api/chat.postMessage").mock(
            return_value=httpx.Response(
                200,
                content=post_resp_payload.encode(),
                headers={"content-type": "application/json"},
            )
        )

        resp = await client.post(
            "/api/chat.postMessage",
            content=json.dumps({"channel": "C123", "text": "hello"}).encode(),
            headers={
                "Authorization": "Bearer xoxb-test",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    assert resp.headers["x-proxy-cache"] == "PASS"
    # Cache should have been invalidated
    assert cache.count() == 0


# ------------------------------------------------------------------
# POST: failure skips invalidation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_failure_skips_invalidation(
    client: AsyncClient, cache: CacheEngine
) -> None:
    """POST that returns ok:false does not trigger invalidation."""
    cache.store(
        method="conversations.history",
        params={"channel": "C123"},
        channel="C123",
        thread_ts=None,
        body=b'{"ok": true, "messages": []}',
        status_code=200,
        content_type="application/json",
    )
    assert cache.count() == 1

    fail_payload = json.dumps({"ok": False, "error": "channel_not_found"})

    with respx.mock:
        respx.post("https://slack.com/api/chat.postMessage").mock(
            return_value=httpx.Response(
                200,
                content=fail_payload.encode(),
                headers={"content-type": "application/json"},
            )
        )

        resp = await client.post(
            "/api/chat.postMessage",
            content=json.dumps({"channel": "C123", "text": "hello"}).encode(),
            headers={
                "Authorization": "Bearer xoxb-test",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200
    # Cache should NOT have been invalidated
    assert cache.count() == 1


# ------------------------------------------------------------------
# X-Proxy-Cache header correctness
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_header_values(client: AsyncClient) -> None:
    """Verify HIT, MISS, and PASS headers are set correctly."""
    payload = json.dumps({"ok": True, "user": {"id": "U123"}})
    post_payload = json.dumps({"ok": True, "ts": "1.1"})

    with respx.mock:
        respx.get("https://slack.com/api/users.info").mock(
            return_value=httpx.Response(
                200,
                content=payload.encode(),
                headers={"content-type": "application/json"},
            )
        )
        respx.post("https://slack.com/api/chat.update").mock(
            return_value=httpx.Response(
                200,
                content=post_payload.encode(),
                headers={"content-type": "application/json"},
            )
        )

        # GET cacheable — MISS
        r_miss = await client.get(
            "/api/users.info",
            params={"user": "U123"},
            headers={"Authorization": "Bearer xoxb-test"},
        )
        assert r_miss.headers["x-proxy-cache"] == "MISS"

    # GET cacheable — HIT
    r_hit = await client.get(
        "/api/users.info",
        params={"user": "U123"},
        headers={"Authorization": "Bearer xoxb-test"},
    )
    assert r_hit.headers["x-proxy-cache"] == "HIT"

    # POST — PASS
    with respx.mock:
        respx.post("https://slack.com/api/chat.update").mock(
            return_value=httpx.Response(
                200,
                content=post_payload.encode(),
                headers={"content-type": "application/json"},
            )
        )

        r_pass = await client.post(
            "/api/chat.update",
            content=json.dumps({"channel": "C1", "ts": "1.1", "text": "updated"}).encode(),
            headers={
                "Authorization": "Bearer xoxb-test",
                "Content-Type": "application/json",
            },
        )
        assert r_pass.headers["x-proxy-cache"] == "PASS"


# ------------------------------------------------------------------
# Auth header forwarded
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_header_forwarded(client: AsyncClient) -> None:
    """Authorization header is forwarded verbatim to upstream."""
    with respx.mock:
        route = respx.get("https://slack.com/api/auth.test").mock(
            return_value=httpx.Response(
                200,
                content=json.dumps({"ok": True, "user_id": "U1"}).encode(),
                headers={"content-type": "application/json"},
            )
        )

        await client.get(
            "/api/auth.test",
            headers={"Authorization": "Bearer xoxb-my-secret-token"},
        )

        assert route.called
        sent_request = route.calls[0].request
        assert sent_request.headers["authorization"] == "Bearer xoxb-my-secret-token"


# ------------------------------------------------------------------
# Unknown method pass-through
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_method_passthrough(client: AsyncClient) -> None:
    """An unknown Slack method is forwarded without caching."""
    payload = json.dumps({"ok": True, "result": "custom"})

    with respx.mock:
        respx.get("https://slack.com/api/custom.method").mock(
            return_value=httpx.Response(
                200,
                content=payload.encode(),
                headers={"content-type": "application/json"},
            )
        )

        resp = await client.get(
            "/api/custom.method",
            headers={"Authorization": "Bearer xoxb-test"},
        )

    assert resp.status_code == 200
    assert resp.headers["x-proxy-cache"] == "PASS"


# ------------------------------------------------------------------
# Health endpoint
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    """Health endpoint returns expected JSON structure."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["version"] == VERSION
    assert body["cache_entries"] >= 0
    assert body["db_status"] == "healthy"
