"""Route handlers for the Slack caching proxy.

Provides the ``/api/{method}`` proxy endpoint and ``/health`` check.
All shared state (cache, upstream client, config) is accessed via
``request.app.state``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response

from proxy.constants import CACHEABLE_METHODS, INVALIDATING_METHODS, VERSION
from proxy.invalidation import invalidate_for
from proxy.logging_config import (
    log_cache_hit,
    log_cache_invalidation,
    log_cache_miss,
    log_cache_store,
    log_request,
)

logger = logging.getLogger("slack_proxy")

router = APIRouter()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_context(params: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pull ``channel`` and ``thread_ts`` from request parameters."""
    channel = params.get("channel") or None
    thread_ts = params.get("thread_ts") or params.get("ts") or None
    return channel, thread_ts


def _parse_json_body(raw: bytes) -> dict:
    """Best-effort JSON parse; return empty dict on failure."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


# ------------------------------------------------------------------
# /api/{method} — proxy endpoint
# ------------------------------------------------------------------

@router.api_route("/api/{method:path}", methods=["GET", "POST"])
async def proxy_slack(method: str, request: Request) -> Response:
    """Proxy a Slack API call with caching for GET-based methods."""

    cache = request.app.state.cache
    upstream = request.app.state.upstream
    auth_header = request.headers.get("authorization", "")
    source_ip = request.client.host if request.client else "unknown"

    # ------ GET ------
    if request.method == "GET":
        params = dict(request.query_params)

        if method in CACHEABLE_METHODS:
            # Try cache lookup (with graceful degradation)
            try:
                cached = await asyncio.to_thread(cache.lookup, method, params)
            except Exception:
                logger.exception("cache lookup failed for %s, falling through", method)
                cached = None

            if cached is not None:
                body, status_code, headers = cached
                cache_age = headers.pop("x-cache-age", "0")
                cache_key = cache.make_key(method, params)
                log_cache_hit(method, cache_key)
                log_request(method, source_ip, "HIT")
                return Response(
                    content=body,
                    status_code=status_code,
                    headers={
                        **headers,
                        "X-Proxy-Cache": "HIT",
                        "X-Proxy-Cache-Age": cache_age,
                    },
                    media_type=None,
                )

            # MISS — forward upstream
            cache_key = cache.make_key(method, params)
            log_cache_miss(method, cache_key)

        resp = await upstream.forward_get(method, params, auth_header)

        # Only cache ok:true responses for cacheable methods
        if method in CACHEABLE_METHODS and resp.status_code == 200:
            resp_json = _parse_json_body(resp.body)
            if resp_json.get("ok", False):
                channel, thread_ts = _extract_context(params)
                try:
                    await asyncio.to_thread(
                        cache.store,
                        method=method,
                        params=params,
                        channel=channel,
                        thread_ts=thread_ts,
                        body=resp.body,
                        status_code=resp.status_code,
                        content_type=resp.content_type,
                    )
                    log_cache_store(method, cache.make_key(method, params), 0)
                except Exception:
                    logger.exception("cache store failed for %s, continuing", method)

        cache_status = "MISS" if method in CACHEABLE_METHODS else "PASS"
        log_request(method, source_ip, cache_status)
        return Response(
            content=resp.body,
            status_code=resp.status_code,
            headers={
                "content-type": resp.content_type,
                "X-Proxy-Cache": cache_status,
            },
            media_type=None,
        )

    # ------ POST ------
    body = await request.body()
    content_type = request.headers.get("content-type", "application/json")

    resp = await upstream.forward_post(method, body, auth_header, content_type)

    # Run invalidation for known mutating methods with ok:true responses
    if method in INVALIDATING_METHODS and resp.status_code == 200:
        resp_json = _parse_json_body(resp.body)
        if resp_json.get("ok", False):
            req_json = _parse_json_body(body)
            try:
                count = await asyncio.to_thread(invalidate_for, cache, method, req_json, resp_json)
                if count:
                    log_cache_invalidation(method, count)
            except Exception:
                logger.exception("cache invalidation failed for %s, continuing", method)

    log_request(method, source_ip, "PASS")
    return Response(
        content=resp.body,
        status_code=resp.status_code,
        headers={
            "content-type": resp.content_type,
            "X-Proxy-Cache": "PASS",
        },
        media_type=None,
    )


# ------------------------------------------------------------------
# /health
# ------------------------------------------------------------------

@router.get("/health")
async def health(request: Request) -> dict:
    """Health check returning proxy status."""
    cache = request.app.state.cache
    try:
        db_healthy = await asyncio.to_thread(cache.is_healthy)
        entry_count = await asyncio.to_thread(cache.count)
    except Exception:
        db_healthy = False
        entry_count = 0

    return {
        "ok": db_healthy,
        "version": VERSION,
        "cache_entries": entry_count,
        "db_status": "healthy" if db_healthy else "degraded",
    }
