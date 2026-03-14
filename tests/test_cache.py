"""Tests for CacheEngine backed by Stoolap in-memory mode."""

import time

import pytest

from src.proxy.cache import CacheEngine


@pytest.fixture()
def engine():
    """Create a fresh in-memory CacheEngine for each test."""
    e = CacheEngine(db_path=":memory:", default_ttl=30)
    yield e
    e.close()


# ------------------------------------------------------------------
# make_key
# ------------------------------------------------------------------


class TestMakeKey:
    def test_deterministic(self):
        k1 = CacheEngine.make_key("conversations.history", {"channel": "C1", "limit": "10"})
        k2 = CacheEngine.make_key("conversations.history", {"channel": "C1", "limit": "10"})
        assert k1 == k2

    def test_param_order_independence(self):
        k1 = CacheEngine.make_key("conversations.history", {"channel": "C1", "limit": "10"})
        k2 = CacheEngine.make_key("conversations.history", {"limit": "10", "channel": "C1"})
        assert k1 == k2

    def test_different_methods_differ(self):
        k1 = CacheEngine.make_key("conversations.history", {"channel": "C1"})
        k2 = CacheEngine.make_key("conversations.replies", {"channel": "C1"})
        assert k1 != k2

    def test_different_params_differ(self):
        k1 = CacheEngine.make_key("conversations.history", {"channel": "C1"})
        k2 = CacheEngine.make_key("conversations.history", {"channel": "C2"})
        assert k1 != k2


# ------------------------------------------------------------------
# Store and retrieve
# ------------------------------------------------------------------


class TestStoreAndRetrieve:
    def test_store_and_lookup_hit(self, engine: CacheEngine):
        body = b'{"ok": true, "messages": []}'
        engine.store(
            method="conversations.history",
            params={"channel": "C1"},
            channel="C1",
            thread_ts=None,
            body=body,
            status_code=200,
            content_type="application/json",
        )
        result = engine.lookup("conversations.history", {"channel": "C1"})
        assert result is not None
        r_body, r_status, r_headers = result
        assert r_body == body
        assert r_status == 200
        assert r_headers["content-type"] == "application/json"

    def test_lookup_miss(self, engine: CacheEngine):
        result = engine.lookup("conversations.history", {"channel": "C999"})
        assert result is None

    def test_overwrite_existing_key(self, engine: CacheEngine):
        params = {"channel": "C1"}
        engine.store(
            method="conversations.history",
            params=params,
            channel="C1",
            thread_ts=None,
            body=b'{"ok": true, "v": 1}',
            status_code=200,
            content_type="application/json",
        )
        engine.store(
            method="conversations.history",
            params=params,
            channel="C1",
            thread_ts=None,
            body=b'{"ok": true, "v": 2}',
            status_code=200,
            content_type="application/json",
        )
        result = engine.lookup("conversations.history", params)
        assert result is not None
        assert result[0] == b'{"ok": true, "v": 2}'
        assert engine.count() == 1


# ------------------------------------------------------------------
# TTL expiry
# ------------------------------------------------------------------


class TestTTLExpiry:
    def test_expired_entry_returns_none(self, engine: CacheEngine):
        body = b'{"ok": true}'
        engine.store(
            method="conversations.history",
            params={"channel": "C1"},
            channel="C1",
            thread_ts=None,
            body=body,
            status_code=200,
            content_type="application/json",
        )
        # Manually backdate the created_at so the entry is expired
        engine._db.execute(
            "UPDATE cache_entries SET created_at = $1 WHERE channel = $2",
            [time.time() - 60, "C1"],
        )
        result = engine.lookup("conversations.history", {"channel": "C1"})
        assert result is None

    def test_custom_method_ttl(self):
        e = CacheEngine(
            db_path=":memory:", default_ttl=30, method_ttls={"auth.test": 300}
        )
        try:
            e.store(
                method="auth.test",
                params={},
                channel=None,
                thread_ts=None,
                body=b'{"ok": true}',
                status_code=200,
                content_type="application/json",
            )
            # Backdate by 60 seconds — still within 300s TTL
            e._db.execute(
                "UPDATE cache_entries SET created_at = $1 WHERE method = $2",
                [time.time() - 60, "auth.test"],
            )
            result = e.lookup("auth.test", {})
            assert result is not None
        finally:
            e.close()


# ------------------------------------------------------------------
# Invalidation
# ------------------------------------------------------------------


class TestInvalidation:
    def _populate(self, engine: CacheEngine):
        """Insert several entries across two channels and threads."""
        entries = [
            ("conversations.history", {"channel": "C1"}, "C1", None),
            ("conversations.replies", {"channel": "C1", "ts": "1.1"}, "C1", "1.1"),
            ("conversations.replies", {"channel": "C1", "ts": "2.2"}, "C1", "2.2"),
            ("reactions.get", {"channel": "C1", "timestamp": "1.1"}, "C1", "1.1"),
            ("conversations.history", {"channel": "C2"}, "C2", None),
        ]
        for method, params, ch, ts in entries:
            engine.store(
                method=method,
                params=params,
                channel=ch,
                thread_ts=ts,
                body=b'{"ok": true}',
                status_code=200,
                content_type="application/json",
            )

    def test_invalidate_channel(self, engine: CacheEngine):
        self._populate(engine)
        assert engine.count() == 5
        engine.invalidate_channel("C1")
        assert engine.count() == 1  # only C2 entry remains

    def test_invalidate_thread(self, engine: CacheEngine):
        self._populate(engine)
        engine.invalidate_thread("C1", "1.1")
        # Should remove conversations.replies ts=1.1 and reactions.get ts=1.1
        assert engine.count() == 3

    def test_invalidate_reactions(self, engine: CacheEngine):
        self._populate(engine)
        engine.invalidate_reactions("C1", "1.1")
        # Should remove only the reactions.get entry for C1/1.1
        assert engine.count() == 4


# ------------------------------------------------------------------
# Count and health
# ------------------------------------------------------------------


class TestCountAndHealth:
    def test_count_empty(self, engine: CacheEngine):
        assert engine.count() == 0

    def test_count_accuracy(self, engine: CacheEngine):
        for i in range(5):
            engine.store(
                method="conversations.history",
                params={"channel": f"C{i}"},
                channel=f"C{i}",
                thread_ts=None,
                body=b'{"ok": true}',
                status_code=200,
                content_type="application/json",
            )
        assert engine.count() == 5

    def test_is_healthy(self, engine: CacheEngine):
        assert engine.is_healthy() is True

    def test_is_healthy_after_close(self):
        e = CacheEngine(db_path=":memory:", default_ttl=30)
        e.close()
        assert e.is_healthy() is False
