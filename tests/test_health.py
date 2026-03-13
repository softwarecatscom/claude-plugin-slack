# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "fastapi>=0.115",
#     "httpx>=0.28",
#     "pytest>=8",
#     "pytest-asyncio>=0.24",
#     "stoolap-python>=0.2",
# ]
# ///
"""Tests for the /health endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from proxy.cache import CacheEngine
from proxy.constants import VERSION
from proxy.routes import router


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_app(cache) -> FastAPI:
    """Build a FastAPI app wired to the given cache."""
    app = FastAPI()
    app.include_router(router)
    app.state.cache = cache
    app.state.upstream = None
    app.state.config = None
    return app


# ------------------------------------------------------------------
# Healthy state
# ------------------------------------------------------------------


@pytest.fixture()
def cache() -> CacheEngine:
    return CacheEngine(db_path=":memory:", default_ttl=60)


@pytest.fixture()
async def healthy_client(cache: CacheEngine):
    app = _make_app(cache)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    cache.close()


@pytest.mark.asyncio
async def test_healthy_returns_200_with_structure(healthy_client: AsyncClient) -> None:
    """Healthy cache returns 200 with version, count, and db_status."""
    resp = await healthy_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["version"] == VERSION
    assert body["cache_entries"] == 0
    assert body["db_status"] == "healthy"


@pytest.mark.asyncio
async def test_healthy_includes_version(healthy_client: AsyncClient) -> None:
    """Version field matches constants.VERSION."""
    resp = await healthy_client.get("/health")
    assert resp.json()["version"] == VERSION


@pytest.mark.asyncio
async def test_healthy_with_entries(
    cache: CacheEngine, healthy_client: AsyncClient
) -> None:
    """Cache entry count is reflected in health response."""
    cache.store(
        method="auth.test",
        params={},
        channel=None,
        thread_ts=None,
        body=b'{"ok": true}',
        status_code=200,
        content_type="application/json",
    )
    resp = await healthy_client.get("/health")
    assert resp.json()["cache_entries"] == 1


# ------------------------------------------------------------------
# Degraded state
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_degraded_cache_returns_degraded_status() -> None:
    """When cache.is_healthy() returns False, db_status is degraded."""
    mock_cache = MagicMock()
    mock_cache.is_healthy.return_value = False
    mock_cache.count.side_effect = Exception("db gone")

    app = _make_app(mock_cache)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/health")

    body = resp.json()
    assert resp.status_code == 200
    assert body["ok"] is False
    assert body["db_status"] == "degraded"
    assert body["cache_entries"] == 0


@pytest.mark.asyncio
async def test_degraded_cache_exception_in_is_healthy() -> None:
    """When is_healthy() itself raises, status is degraded."""
    mock_cache = MagicMock()
    mock_cache.is_healthy.side_effect = Exception("connection lost")
    mock_cache.count.side_effect = Exception("connection lost")

    app = _make_app(mock_cache)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/health")

    body = resp.json()
    assert body["ok"] is False
    assert body["db_status"] == "degraded"
    assert body["version"] == VERSION
