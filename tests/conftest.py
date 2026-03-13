"""Shared pytest fixtures for scc-slack-proxy tests.

Provides reusable fixtures for the proxy's core components with mocked
dependencies.  The CacheEngine is always mocked (stoolap-python is not
available in CI); upstream is mocked via MagicMock with async support.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from proxy.config import CacheConfig, LoggingConfig, ProxyConfig, ServerConfig
from proxy.routes import router


# ------------------------------------------------------------------
# Config fixture
# ------------------------------------------------------------------


@pytest.fixture()
def mock_config() -> ProxyConfig:
    """Return a ProxyConfig with test-friendly defaults."""
    return ProxyConfig(
        server=ServerConfig(host="127.0.0.1", port=8321),
        cache=CacheConfig(
            db_path=":memory:",
            default_ttl=60,
            method_ttls={
                "conversations.history": 60,
                "conversations.replies": 60,
                "pins.list": 300,
                "auth.test": 300,
                "users.info": 300,
                "users.list": 300,
                "conversations.list": 300,
                "conversations.info": 300,
                "reactions.get": 60,
            },
        ),
        logging=LoggingConfig(level="debug", redact_tokens=False),
    )


# ------------------------------------------------------------------
# Cache fixture (fully mocked — stoolap not available)
# ------------------------------------------------------------------


@pytest.fixture()
def mock_cache() -> MagicMock:
    """Return a MagicMock of CacheEngine with all public methods.

    Default behaviors:
    - lookup() returns None (cache miss)
    - make_key() returns a deterministic string
    - store() is a no-op
    - invalidate_*() return 0
    - count() returns 0
    - is_healthy() returns True
    - close() is a no-op
    """
    cache = MagicMock()

    # Lookup: default MISS
    cache.lookup.return_value = None

    # Key generation: deterministic stub
    cache.make_key.side_effect = lambda method, params: (
        f"{method}:{'&'.join(f'{k}={v}' for k, v in sorted(params.items()))}"
    )

    # Store: no-op (record calls for assertions)
    cache.store.return_value = None

    # Invalidation: return 0 by default
    cache.invalidate_channel.return_value = 0
    cache.invalidate_thread.return_value = 0
    cache.invalidate_reactions.return_value = 0

    # Health / count
    cache.count.return_value = 0
    cache.is_healthy.return_value = True

    # Teardown
    cache.close.return_value = None

    return cache


# ------------------------------------------------------------------
# Upstream fixture (fully mocked)
# ------------------------------------------------------------------


@pytest.fixture()
def mock_upstream() -> MagicMock:
    """Return a MagicMock of UpstreamClient with async methods.

    forward_get and forward_post are AsyncMock instances so they can
    be awaited.  close() is also async.
    """
    upstream = MagicMock()
    upstream.forward_get = AsyncMock()
    upstream.forward_post = AsyncMock()
    upstream.close = AsyncMock()
    return upstream


# ------------------------------------------------------------------
# FastAPI app wired with mocked dependencies
# ------------------------------------------------------------------


@pytest.fixture()
def test_app(mock_cache: MagicMock, mock_upstream: MagicMock, mock_config: ProxyConfig) -> FastAPI:
    """Create a FastAPI test app with mocked dependencies on app.state."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.cache = mock_cache
        app.state.upstream = mock_upstream
        app.state.config = mock_config
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    return app


# ------------------------------------------------------------------
# Async HTTP client bound to the test app
# ------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_client(test_app: FastAPI) -> AsyncClient:
    """Return an httpx.AsyncClient wired to the test FastAPI app via ASGITransport."""
    transport = ASGITransport(app=test_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
