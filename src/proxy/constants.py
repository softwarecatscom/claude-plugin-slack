"""Shared constants for the Slack caching proxy."""

VERSION = "0.1.0"

DEFAULT_TTL = 60

# Slack API methods whose responses are safe to cache.
CACHEABLE_METHODS: frozenset[str] = frozenset({
    "conversations.history",
    "conversations.replies",
    "pins.list",
    "conversations.list",
    "conversations.info",
    "users.info",
    "users.list",
    "auth.test",
    "reactions.get",
})

# Slack API methods that mutate state and should invalidate cache entries.
INVALIDATING_METHODS: frozenset[str] = frozenset({
    "chat.postMessage",
    "chat.update",
    "chat.delete",
    "reactions.add",
})

# Per-method TTL overrides (seconds).  Methods not listed here use DEFAULT_TTL.
DEFAULT_METHOD_TTLS: dict[str, int] = {
    "conversations.history": 60,
    "conversations.replies": 60,
    "pins.list": 300,
    "auth.test": 300,
    "users.info": 300,
    "users.list": 300,
    "conversations.list": 300,
    "conversations.info": 300,
    "reactions.get": 60,
}
