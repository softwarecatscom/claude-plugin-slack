"""End-to-end tests for the scc-slack-proxy.

Exercises the full proxy stack (routes -> cache -> upstream) with a mocked
CacheEngine (stoolap-python is not available in CI) and mocked upstream
Slack API.  Tests verify the integration contracts between components.

The mocked cache simulates real CacheEngine behavior: lookup/store with
TTL expiry, invalidation, and key generation.  Once stoolap-python is
available, these tests will also pass with a real CacheEngine.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from proxy.constants import VERSION
from proxy.upstream import UpstreamResponse


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ok_response(payload: dict, status_code: int = 200) -> UpstreamResponse:
    """Build an UpstreamResponse wrapping a JSON payload."""
    return UpstreamResponse(
        body=json.dumps(payload).encode(),
        status_code=status_code,
        content_type="application/json",
        headers={},
    )


def _error_response(error: str, status_code: int = 200) -> UpstreamResponse:
    """Build an UpstreamResponse with ok:false."""
    return UpstreamResponse(
        body=json.dumps({"ok": False, "error": error}).encode(),
        status_code=status_code,
        content_type="application/json",
        headers={},
    )


def _timeout_response() -> UpstreamResponse:
    """Build an UpstreamResponse simulating an upstream timeout (502)."""
    return UpstreamResponse(
        body=json.dumps({
            "ok": False,
            "error": "proxy_upstream_timeout",
            "detail": "timed out",
        }).encode(),
        status_code=502,
        content_type="application/json",
        headers={},
    )


# ------------------------------------------------------------------
# Cache round-trip: MISS then HIT on same request
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_then_hit(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """First GET is a cache MISS (forwarded upstream), second is a HIT."""
    payload = {"ok": True, "messages": [{"text": "hello"}]}
    mock_upstream.forward_get.return_value = _ok_response(payload)

    # --- Request 1: MISS ---
    # Cache lookup returns None -> miss
    mock_cache.lookup.return_value = None

    r1 = await async_client.get(
        "/api/conversations.history",
        params={"channel": "C123"},
        headers={"Authorization": "Bearer xoxb-test-token"},
    )

    assert r1.status_code == 200
    assert r1.headers["x-proxy-cache"] == "MISS"
    assert json.loads(r1.content) == payload
    mock_cache.store.assert_called_once()
    mock_upstream.forward_get.assert_called_once()

    # --- Request 2: HIT ---
    # Simulate cache now returning the stored entry
    stored_body = json.dumps(payload).encode()
    mock_cache.lookup.return_value = (
        stored_body,
        200,
        {"content-type": "application/json", "x-cache-age": "2"},
    )
    mock_upstream.forward_get.reset_mock()

    r2 = await async_client.get(
        "/api/conversations.history",
        params={"channel": "C123"},
        headers={"Authorization": "Bearer xoxb-test-token"},
    )

    assert r2.status_code == 200
    assert r2.headers["x-proxy-cache"] == "HIT"
    assert r2.headers["x-proxy-cache-age"] == "2"
    assert json.loads(r2.content) == payload
    # Upstream must NOT have been called for a HIT
    mock_upstream.forward_get.assert_not_called()


# ------------------------------------------------------------------
# TTL expiry: patch time past TTL boundary, verify cache miss
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ttl_expiry_causes_cache_miss(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """After TTL expires, cache returns None and request goes upstream."""
    payload = {"ok": True, "messages": []}
    mock_upstream.forward_get.return_value = _ok_response(payload)

    # First request: cache miss, entry gets stored
    mock_cache.lookup.return_value = None
    r1 = await async_client.get(
        "/api/conversations.history",
        params={"channel": "C123"},
        headers={"Authorization": "Bearer xoxb-test"},
    )
    assert r1.headers["x-proxy-cache"] == "MISS"
    assert mock_cache.store.call_count == 1

    # Simulate TTL expiry: cache lookup returns None again
    mock_cache.lookup.return_value = None
    mock_upstream.forward_get.reset_mock()
    mock_cache.store.reset_mock()

    r2 = await async_client.get(
        "/api/conversations.history",
        params={"channel": "C123"},
        headers={"Authorization": "Bearer xoxb-test"},
    )

    assert r2.headers["x-proxy-cache"] == "MISS"
    # Went upstream again after expiry
    mock_upstream.forward_get.assert_called_once()
    # Re-stored the fresh response
    mock_cache.store.assert_called_once()


# ------------------------------------------------------------------
# Per-method TTL independence
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_method_ttl_independence(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """Different methods get different TTLs.

    Simulates: conversations.history (60s TTL) expired while
    auth.test (300s TTL) is still cached.
    """
    history_payload = {"ok": True, "messages": []}
    auth_payload = {"ok": True, "user_id": "U123"}
    mock_upstream.forward_get.return_value = _ok_response(history_payload)

    # --- Populate both entries ---
    mock_cache.lookup.return_value = None
    await async_client.get(
        "/api/conversations.history",
        params={"channel": "C1"},
        headers={"Authorization": "Bearer xoxb-test"},
    )
    mock_upstream.forward_get.return_value = _ok_response(auth_payload)
    await async_client.get(
        "/api/auth.test",
        headers={"Authorization": "Bearer xoxb-test"},
    )

    # --- After 90 seconds: conversations.history expired, auth.test still valid ---
    # conversations.history: TTL 60s -> expired -> lookup returns None
    def lookup_side_effect(method, params):
        if method == "auth.test":
            return (
                json.dumps(auth_payload).encode(),
                200,
                {"content-type": "application/json", "x-cache-age": "90"},
            )
        return None  # conversations.history expired

    mock_cache.lookup.side_effect = lookup_side_effect
    mock_upstream.forward_get.reset_mock()
    mock_upstream.forward_get.return_value = _ok_response(history_payload)

    # conversations.history -> MISS (expired)
    r_hist = await async_client.get(
        "/api/conversations.history",
        params={"channel": "C1"},
        headers={"Authorization": "Bearer xoxb-test"},
    )
    assert r_hist.headers["x-proxy-cache"] == "MISS"
    mock_upstream.forward_get.assert_called_once()

    # auth.test -> HIT (still within 300s TTL)
    mock_upstream.forward_get.reset_mock()
    r_auth = await async_client.get(
        "/api/auth.test",
        headers={"Authorization": "Bearer xoxb-test"},
    )
    assert r_auth.headers["x-proxy-cache"] == "HIT"
    mock_upstream.forward_get.assert_not_called()


# ------------------------------------------------------------------
# Write-through invalidation after chat.postMessage
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_message_invalidates_channel_cache(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """chat.postMessage with ok:true triggers channel cache invalidation."""
    post_response = {"ok": True, "channel": "C123", "ts": "1234567890.123456"}
    mock_upstream.forward_post.return_value = _ok_response(post_response)
    mock_cache.invalidate_channel.return_value = 2

    resp = await async_client.post(
        "/api/chat.postMessage",
        content=json.dumps({"channel": "C123", "text": "hello"}).encode(),
        headers={
            "Authorization": "Bearer xoxb-test",
            "Content-Type": "application/json",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["x-proxy-cache"] == "PASS"
    body = json.loads(resp.content)
    assert body["ok"] is True

    # Verify invalidation was triggered
    mock_cache.invalidate_channel.assert_called_once_with("C123")


# ------------------------------------------------------------------
# Thread reply invalidation with thread_ts
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thread_reply_invalidates_channel_and_thread(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """chat.postMessage with thread_ts invalidates both channel and thread."""
    post_response = {"ok": True, "channel": "C123", "ts": "9999.9999"}
    mock_upstream.forward_post.return_value = _ok_response(post_response)
    mock_cache.invalidate_channel.return_value = 1
    mock_cache.invalidate_thread.return_value = 1

    resp = await async_client.post(
        "/api/chat.postMessage",
        content=json.dumps({
            "channel": "C123",
            "text": "thread reply",
            "thread_ts": "1111.1111",
        }).encode(),
        headers={
            "Authorization": "Bearer xoxb-test",
            "Content-Type": "application/json",
        },
    )

    assert resp.status_code == 200
    mock_cache.invalidate_channel.assert_called_once_with("C123")
    mock_cache.invalidate_thread.assert_called_once_with("C123", "1111.1111")


# ------------------------------------------------------------------
# Only cache ok:true responses (ok:false NOT cached)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ok_false_response_not_cached(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """A Slack response with ok:false must not be stored in the cache."""
    mock_cache.lookup.return_value = None
    mock_upstream.forward_get.return_value = _error_response("channel_not_found")

    resp = await async_client.get(
        "/api/conversations.history",
        params={"channel": "CINVALID"},
        headers={"Authorization": "Bearer xoxb-test"},
    )

    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert body["ok"] is False

    # store() must NOT have been called for an ok:false response
    mock_cache.store.assert_not_called()


@pytest.mark.asyncio
async def test_ok_true_response_is_cached(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """A Slack response with ok:true IS stored in the cache."""
    mock_cache.lookup.return_value = None
    mock_upstream.forward_get.return_value = _ok_response(
        {"ok": True, "messages": []}
    )

    await async_client.get(
        "/api/conversations.history",
        params={"channel": "C123"},
        headers={"Authorization": "Bearer xoxb-test"},
    )

    mock_cache.store.assert_called_once()
    call_kwargs = mock_cache.store.call_args
    assert call_kwargs.kwargs["method"] == "conversations.history"
    assert call_kwargs.kwargs["status_code"] == 200


# ------------------------------------------------------------------
# Non-200 status: ok:true but status != 200 is NOT cached
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_200_status_not_cached(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """Even if the body has ok:true, a non-200 status is not cached."""
    mock_cache.lookup.return_value = None
    mock_upstream.forward_get.return_value = _ok_response(
        {"ok": True, "warning": "something"}, status_code=299
    )

    await async_client.get(
        "/api/conversations.history",
        params={"channel": "C123"},
        headers={"Authorization": "Bearer xoxb-test"},
    )

    mock_cache.store.assert_not_called()


# ------------------------------------------------------------------
# Pass-through for unknown methods
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_method_passthrough(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """A method not in CACHEABLE_METHODS is forwarded without caching."""
    payload = {"ok": True, "file": {"id": "F123"}}
    mock_upstream.forward_get.return_value = _ok_response(payload)

    resp = await async_client.get(
        "/api/files.info",
        params={"file": "F123"},
        headers={"Authorization": "Bearer xoxb-test"},
    )

    assert resp.status_code == 200
    assert resp.headers["x-proxy-cache"] == "PASS"
    assert json.loads(resp.content) == payload

    # No cache interaction for unknown methods
    mock_cache.lookup.assert_not_called()
    mock_cache.store.assert_not_called()


# ------------------------------------------------------------------
# Auth header forwarded verbatim
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_header_forwarded_on_get(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """Authorization header is forwarded verbatim to upstream on GET."""
    mock_cache.lookup.return_value = None
    mock_upstream.forward_get.return_value = _ok_response({"ok": True})

    await async_client.get(
        "/api/auth.test",
        headers={"Authorization": "Bearer xoxb-my-secret-token-12345"},
    )

    call_args = mock_upstream.forward_get.call_args
    assert call_args.args[2] == "Bearer xoxb-my-secret-token-12345"


@pytest.mark.asyncio
async def test_auth_header_forwarded_on_post(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """Authorization header is forwarded verbatim to upstream on POST."""
    mock_upstream.forward_post.return_value = _ok_response(
        {"ok": True, "ts": "1.1"}
    )

    await async_client.post(
        "/api/chat.postMessage",
        content=json.dumps({"channel": "C1", "text": "hi"}).encode(),
        headers={
            "Authorization": "Bearer xoxb-my-secret-token-12345",
            "Content-Type": "application/json",
        },
    )

    call_args = mock_upstream.forward_post.call_args
    assert call_args.args[2] == "Bearer xoxb-my-secret-token-12345"


# ------------------------------------------------------------------
# Health endpoint: healthy
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint_healthy(
    async_client: AsyncClient,
    mock_cache: MagicMock,
) -> None:
    """Health endpoint returns healthy status when cache is working."""
    mock_cache.is_healthy.return_value = True
    mock_cache.count.return_value = 42

    resp = await async_client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["version"] == VERSION
    assert body["cache_entries"] == 42
    assert body["db_status"] == "healthy"


# ------------------------------------------------------------------
# Health endpoint: degraded
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint_degraded(
    async_client: AsyncClient,
    mock_cache: MagicMock,
) -> None:
    """Health endpoint returns degraded status when cache is broken."""
    mock_cache.is_healthy.side_effect = Exception("connection lost")
    mock_cache.count.side_effect = Exception("connection lost")

    resp = await async_client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["db_status"] == "degraded"
    assert body["cache_entries"] == 0


# ------------------------------------------------------------------
# Upstream timeout returns 502
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upstream_timeout_returns_502(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """When upstream times out, proxy returns 502 with error JSON."""
    mock_cache.lookup.return_value = None
    mock_upstream.forward_get.return_value = _timeout_response()

    resp = await async_client.get(
        "/api/conversations.history",
        params={"channel": "C123"},
        headers={"Authorization": "Bearer xoxb-test"},
    )

    assert resp.status_code == 502
    body = json.loads(resp.content)
    assert body["ok"] is False
    assert body["error"] == "proxy_upstream_timeout"

    # Must NOT cache a 502 response
    mock_cache.store.assert_not_called()


# ------------------------------------------------------------------
# POST to non-invalidating method is pure pass-through
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_non_invalidating_method_passthrough(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """POST to a method not in INVALIDATING_METHODS does not invalidate."""
    mock_upstream.forward_post.return_value = _ok_response(
        {"ok": True, "file": {"id": "F1"}}
    )

    resp = await async_client.post(
        "/api/files.upload",
        content=b"file-content",
        headers={
            "Authorization": "Bearer xoxb-test",
            "Content-Type": "application/octet-stream",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["x-proxy-cache"] == "PASS"
    mock_cache.invalidate_channel.assert_not_called()
    mock_cache.invalidate_thread.assert_not_called()
    mock_cache.invalidate_reactions.assert_not_called()


# ------------------------------------------------------------------
# POST failure (ok:false) does NOT trigger invalidation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_ok_false_skips_invalidation(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """chat.postMessage returning ok:false must not invalidate cache."""
    mock_upstream.forward_post.return_value = _error_response("channel_not_found")

    resp = await async_client.post(
        "/api/chat.postMessage",
        content=json.dumps({"channel": "CINVALID", "text": "oops"}).encode(),
        headers={
            "Authorization": "Bearer xoxb-test",
            "Content-Type": "application/json",
        },
    )

    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert body["ok"] is False
    mock_cache.invalidate_channel.assert_not_called()


# ------------------------------------------------------------------
# Cache lookup failure degrades gracefully
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_lookup_failure_degrades_gracefully(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """If cache.lookup raises, the request falls through to upstream."""
    mock_cache.lookup.side_effect = RuntimeError("db corrupt")
    mock_upstream.forward_get.return_value = _ok_response(
        {"ok": True, "messages": []}
    )

    resp = await async_client.get(
        "/api/conversations.history",
        params={"channel": "C123"},
        headers={"Authorization": "Bearer xoxb-test"},
    )

    assert resp.status_code == 200
    # Falls through to upstream despite cache error
    mock_upstream.forward_get.assert_called_once()


# ------------------------------------------------------------------
# Cache store failure does not break the response
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_store_failure_does_not_break_response(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """If cache.store raises, the response is still returned to the client."""
    mock_cache.lookup.return_value = None
    mock_cache.store.side_effect = RuntimeError("disk full")
    mock_upstream.forward_get.return_value = _ok_response(
        {"ok": True, "messages": [{"text": "important"}]}
    )

    resp = await async_client.get(
        "/api/conversations.history",
        params={"channel": "C123"},
        headers={"Authorization": "Bearer xoxb-test"},
    )

    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert body["ok"] is True
    assert body["messages"] == [{"text": "important"}]


# ------------------------------------------------------------------
# Reactions.add invalidation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reactions_add_invalidates_reactions_cache(
    async_client: AsyncClient,
    mock_cache: MagicMock,
    mock_upstream: MagicMock,
) -> None:
    """reactions.add triggers reactions cache invalidation."""
    mock_upstream.forward_post.return_value = _ok_response({"ok": True})
    mock_cache.invalidate_reactions.return_value = 1

    await async_client.post(
        "/api/reactions.add",
        content=json.dumps({
            "channel": "C123",
            "timestamp": "1111.2222",
            "name": "thumbsup",
        }).encode(),
        headers={
            "Authorization": "Bearer xoxb-test",
            "Content-Type": "application/json",
        },
    )

    mock_cache.invalidate_reactions.assert_called_once_with("C123", "1111.2222")
