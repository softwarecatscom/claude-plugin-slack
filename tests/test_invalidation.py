"""Tests for src/proxy/invalidation.py — cache invalidation rules."""

from __future__ import annotations

from unittest.mock import MagicMock

from proxy.invalidation import INVALIDATION_MAP, invalidate_for


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

import pytest


@pytest.fixture
def cache() -> MagicMock:
    """Return a mock CacheEngine with invalidation methods that return counts."""
    mock = MagicMock()
    mock.invalidate_channel.return_value = 1
    mock.invalidate_thread.return_value = 1
    mock.invalidate_reactions.return_value = 1
    return mock


# ---------------------------------------------------------------------------
# INVALIDATION_MAP sanity
# ---------------------------------------------------------------------------

def test_invalidation_map_contains_expected_methods():
    assert set(INVALIDATION_MAP) == {
        "chat.postMessage",
        "chat.update",
        "chat.delete",
        "reactions.add",
        "reactions.remove",
    }


# ---------------------------------------------------------------------------
# chat.postMessage — channel only
# ---------------------------------------------------------------------------

def test_post_message_invalidates_channel(cache: MagicMock):
    request_body = {"channel": "C123", "text": "hello"}
    response_body = {"ok": True, "channel": "C123", "ts": "111.222"}

    count = invalidate_for(cache, "chat.postMessage", request_body, response_body)

    cache.invalidate_channel.assert_called_once_with("C123")
    cache.invalidate_thread.assert_not_called()
    assert count == 1


# ---------------------------------------------------------------------------
# chat.postMessage — with thread_ts
# ---------------------------------------------------------------------------

def test_post_message_with_thread_ts_invalidates_thread(cache: MagicMock):
    request_body = {"channel": "C123", "text": "reply", "thread_ts": "100.000"}
    response_body = {"ok": True, "channel": "C123", "ts": "111.222"}

    count = invalidate_for(cache, "chat.postMessage", request_body, response_body)

    cache.invalidate_channel.assert_called_once_with("C123")
    cache.invalidate_thread.assert_called_once_with("C123", "100.000")
    assert count == 2


# ---------------------------------------------------------------------------
# chat.update
# ---------------------------------------------------------------------------

def test_chat_update_invalidates_channel_and_thread(cache: MagicMock):
    request_body = {"channel": "C456", "ts": "200.000", "text": "edited"}
    response_body = {"ok": True, "channel": "C456", "ts": "200.000"}

    count = invalidate_for(cache, "chat.update", request_body, response_body)

    cache.invalidate_channel.assert_called_once_with("C456")
    cache.invalidate_thread.assert_called_once_with("C456", "200.000")
    assert count == 2


# ---------------------------------------------------------------------------
# chat.delete
# ---------------------------------------------------------------------------

def test_chat_delete_invalidates_channel_and_thread(cache: MagicMock):
    request_body = {"channel": "C789", "ts": "300.000"}
    response_body = {"ok": True, "channel": "C789", "ts": "300.000"}

    count = invalidate_for(cache, "chat.delete", request_body, response_body)

    cache.invalidate_channel.assert_called_once_with("C789")
    cache.invalidate_thread.assert_called_once_with("C789", "300.000")
    assert count == 2


# ---------------------------------------------------------------------------
# reactions.add
# ---------------------------------------------------------------------------

def test_reactions_add_invalidates_reactions(cache: MagicMock):
    request_body = {"channel": "C111", "timestamp": "400.000", "name": "thumbsup"}
    response_body = {"ok": True}

    count = invalidate_for(cache, "reactions.add", request_body, response_body)

    cache.invalidate_reactions.assert_called_once_with("C111", "400.000")
    cache.invalidate_channel.assert_not_called()
    cache.invalidate_thread.assert_not_called()
    assert count == 1


# ---------------------------------------------------------------------------
# Skip on ok: false
# ---------------------------------------------------------------------------

def test_skip_invalidation_on_ok_false(cache: MagicMock):
    request_body = {"channel": "C123", "text": "hello"}
    response_body = {"ok": False, "error": "channel_not_found"}

    count = invalidate_for(cache, "chat.postMessage", request_body, response_body)

    cache.invalidate_channel.assert_not_called()
    cache.invalidate_thread.assert_not_called()
    cache.invalidate_reactions.assert_not_called()
    assert count == 0


def test_skip_invalidation_when_ok_missing(cache: MagicMock):
    """A response without the ``ok`` field should be treated as failure."""
    request_body = {"channel": "C123", "text": "hello"}
    response_body = {"error": "something"}

    count = invalidate_for(cache, "chat.postMessage", request_body, response_body)

    cache.invalidate_channel.assert_not_called()
    assert count == 0


# ---------------------------------------------------------------------------
# Missing channel field — graceful handling
# ---------------------------------------------------------------------------

def test_missing_channel_in_post_message(cache: MagicMock):
    request_body = {"text": "hello"}
    response_body = {"ok": True, "ts": "111.222"}

    count = invalidate_for(cache, "chat.postMessage", request_body, response_body)

    cache.invalidate_channel.assert_not_called()
    cache.invalidate_thread.assert_not_called()
    assert count == 0


def test_missing_channel_in_chat_update(cache: MagicMock):
    request_body = {"ts": "200.000", "text": "edited"}
    response_body = {"ok": True, "ts": "200.000"}

    count = invalidate_for(cache, "chat.update", request_body, response_body)

    cache.invalidate_channel.assert_not_called()
    cache.invalidate_thread.assert_not_called()
    assert count == 0


def test_missing_channel_in_chat_delete(cache: MagicMock):
    request_body = {"ts": "300.000"}
    response_body = {"ok": True, "ts": "300.000"}

    count = invalidate_for(cache, "chat.delete", request_body, response_body)

    cache.invalidate_channel.assert_not_called()
    assert count == 0


def test_missing_channel_in_reactions_add(cache: MagicMock):
    request_body = {"timestamp": "400.000", "name": "thumbsup"}
    response_body = {"ok": True}

    count = invalidate_for(cache, "reactions.add", request_body, response_body)

    cache.invalidate_reactions.assert_not_called()
    assert count == 0


# ---------------------------------------------------------------------------
# Missing ts / timestamp field — graceful handling
# ---------------------------------------------------------------------------

def test_missing_ts_in_chat_update(cache: MagicMock):
    """chat.update with channel but no ts should still invalidate channel."""
    request_body = {"channel": "C456", "text": "edited"}
    response_body = {"ok": True, "channel": "C456"}

    count = invalidate_for(cache, "chat.update", request_body, response_body)

    cache.invalidate_channel.assert_called_once_with("C456")
    cache.invalidate_thread.assert_not_called()
    assert count == 1


def test_missing_ts_in_chat_delete(cache: MagicMock):
    """chat.delete with channel but no ts should still invalidate channel."""
    request_body = {"channel": "C789"}
    response_body = {"ok": True, "channel": "C789"}

    count = invalidate_for(cache, "chat.delete", request_body, response_body)

    cache.invalidate_channel.assert_called_once_with("C789")
    cache.invalidate_thread.assert_not_called()
    assert count == 1


def test_missing_timestamp_in_reactions_add(cache: MagicMock):
    request_body = {"channel": "C111", "name": "thumbsup"}
    response_body = {"ok": True}

    count = invalidate_for(cache, "reactions.add", request_body, response_body)

    cache.invalidate_reactions.assert_not_called()
    assert count == 0


# ---------------------------------------------------------------------------
# Unknown method — no-op
# ---------------------------------------------------------------------------

def test_unknown_method_returns_zero(cache: MagicMock):
    count = invalidate_for(
        cache, "files.upload", {"channel": "C123"}, {"ok": True}
    )

    cache.invalidate_channel.assert_not_called()
    cache.invalidate_thread.assert_not_called()
    cache.invalidate_reactions.assert_not_called()
    assert count == 0
