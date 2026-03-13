# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "fastapi>=0.115",
#     "uvicorn[standard]>=0.34",
#     "httpx>=0.28",
#     "stoolap-python>=0.2",
#     "tomli>=2.0",
# ]
# ///
"""scc-slack-proxy: Caching proxy for the Slack Web API.

Transparent proxy that sits between agents and slack.com.  GET requests
for cacheable methods are served from a Stoolap-backed cache; POST
requests pass through and trigger targeted cache invalidation.

Usage:
    uv run src/proxy/service.py [--config path] [--host 0.0.0.0] [--port 8321]
"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from proxy.cache import CacheEngine
from proxy.config import load_config
from proxy.constants import VERSION
from proxy.logging_config import (
    log_config_loaded,
    log_shutdown,
    log_startup,
    setup_logging,
)
from proxy.routes import router
from proxy.upstream import UpstreamClient

# Module-level reference so argparse results are visible to the lifespan.
_cli_args: argparse.Namespace | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle for the proxy."""
    config = load_config(getattr(_cli_args, "config", None))

    setup_logging(
        level=config.logging.level,
        redact_tokens=config.logging.redact_tokens,
    )

    cache = CacheEngine(
        db_path=config.cache.db_path,
        default_ttl=config.cache.default_ttl,
        method_ttls=config.cache.method_ttls,
    )
    upstream = UpstreamClient()

    app.state.cache = cache
    app.state.upstream = upstream
    app.state.config = config

    log_config_loaded(
        host=config.server.host,
        port=config.server.port,
        db_path=config.cache.db_path,
        ttl_count=len(config.cache.method_ttls),
    )
    log_startup()

    yield

    await upstream.close()
    cache.close()
    log_shutdown()


app = FastAPI(
    title="scc-slack-proxy",
    version=VERSION,
    lifespan=lifespan,
)
app.include_router(router)


def main() -> None:
    """CLI entry point."""
    global _cli_args

    parser = argparse.ArgumentParser(description="scc-slack-proxy")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.toml (default: auto-detect)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Bind address (overrides config file)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port (overrides config file)",
    )
    _cli_args = parser.parse_args()

    # Load config early just to resolve host/port defaults for uvicorn.
    config = load_config(_cli_args.config)
    host = _cli_args.host or config.server.host
    port = _cli_args.port or config.server.port

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
