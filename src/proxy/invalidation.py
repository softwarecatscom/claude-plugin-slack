"""Write-through cache invalidation rules for Slack POST methods.

Maps each mutating Slack API method to a handler that invalidates the
relevant cache entries.  The dispatcher ``invalidate_for()`` is called
by the route handler after a successful POST.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CacheEngine protocol — the subset of CacheEngine that invalidation needs.
# ---------------------------------------------------------------------------

class CacheEngineProtocol(Protocol):
    """Structural type for the cache engine dependency."""

    def invalidate_channel(self, channel: str) -> int: ...
    def invalidate_thread(self, channel: str, thread_ts: str) -> int: ...
    def invalidate_reactions(self, channel: str, timestamp: str) -> int: ...


# Type alias for invalidation handler functions.
InvalidationHandler = Callable[
    [CacheEngineProtocol, dict, dict], int
]


# ---------------------------------------------------------------------------
# Per-method invalidation handlers
# ---------------------------------------------------------------------------

def _invalidate_post_message(
    cache: CacheEngineProtocol,
    request_body: dict,
    response_body: dict,
) -> int:
    """Invalidate cache after chat.postMessage.

    Always invalidates conversations.history for the channel.
    If the request included ``thread_ts``, also invalidates
    conversations.replies for that thread.
    """
    channel = response_body.get("channel") or request_body.get("channel")
    if not channel:
        logger.warning("chat.postMessage: missing channel in request/response, skipping invalidation")
        return 0

    count = cache.invalidate_channel(channel)

    thread_ts = request_body.get("thread_ts")
    if thread_ts:
        count += cache.invalidate_thread(channel, thread_ts)

    return count


def _invalidate_chat_update(
    cache: CacheEngineProtocol,
    request_body: dict,
    response_body: dict,
) -> int:
    """Invalidate cache after chat.update.

    Invalidates conversations.history for the channel and
    conversations.replies for the thread identified by ``ts``
    in the response.
    """
    channel = response_body.get("channel") or request_body.get("channel")
    if not channel:
        logger.warning("chat.update: missing channel in request/response, skipping invalidation")
        return 0

    count = cache.invalidate_channel(channel)

    ts = response_body.get("ts") or request_body.get("ts")
    if ts:
        count += cache.invalidate_thread(channel, ts)
    else:
        logger.warning("chat.update: missing ts in request/response, skipping thread invalidation")

    return count


def _invalidate_chat_delete(
    cache: CacheEngineProtocol,
    request_body: dict,
    response_body: dict,
) -> int:
    """Invalidate cache after chat.delete.

    Same logic as chat.update: invalidates conversations.history
    for the channel and conversations.replies for the thread.
    """
    channel = response_body.get("channel") or request_body.get("channel")
    if not channel:
        logger.warning("chat.delete: missing channel in request/response, skipping invalidation")
        return 0

    count = cache.invalidate_channel(channel)

    ts = response_body.get("ts") or request_body.get("ts")
    if ts:
        count += cache.invalidate_thread(channel, ts)
    else:
        logger.warning("chat.delete: missing ts in request/response, skipping thread invalidation")

    return count


def _invalidate_reactions_add(
    cache: CacheEngineProtocol,
    request_body: dict,
    response_body: dict,
) -> int:
    """Invalidate cache after reactions.add.

    Invalidates reactions.get entries for the affected message
    using ``channel`` and ``timestamp`` from the request body.
    """
    channel = request_body.get("channel")
    if not channel:
        logger.warning("reactions.add: missing channel in request body, skipping invalidation")
        return 0

    timestamp = request_body.get("timestamp")
    if not timestamp:
        logger.warning("reactions.add: missing timestamp in request body, skipping invalidation")
        return 0

    return cache.invalidate_reactions(channel, timestamp)


# ---------------------------------------------------------------------------
# Invalidation map and dispatcher
# ---------------------------------------------------------------------------

INVALIDATION_MAP: dict[str, InvalidationHandler] = {
    "chat.postMessage": _invalidate_post_message,
    "chat.update": _invalidate_chat_update,
    "chat.delete": _invalidate_chat_delete,
    "reactions.add": _invalidate_reactions_add,
}


async def invalidate_for(
    cache: CacheEngineProtocol,
    method: str,
    request_body: dict,
    response_body: dict,
) -> int:
    """Dispatch cache invalidation for a successful POST.

    Parameters
    ----------
    cache:
        The cache engine instance with invalidation methods.
    method:
        The Slack API method name (e.g. ``chat.postMessage``).
    request_body:
        The parsed JSON body sent by the caller.
    response_body:
        The parsed JSON body returned by Slack.

    Returns
    -------
    int
        Number of cache entries invalidated, or 0 if skipped.
    """
    # Skip invalidation when the Slack response indicates failure.
    if not response_body.get("ok", False):
        return 0

    handler = INVALIDATION_MAP.get(method)
    if handler is None:
        return 0

    return handler(cache, request_body, response_body)
