"""CacheEngine — Stoolap-backed response cache for scc-slack-proxy.

Stores Slack API responses keyed by method + params hash, with per-method
TTL support and targeted invalidation by channel, thread, or reaction.

Callers are responsible for only caching ok:true responses.  The engine
itself does not inspect the response body.
"""

import hashlib
import json
import time

from stoolap import Database


class CacheEngine:
    """Persistent Slack API response cache backed by Stoolap."""

    def __init__(
        self,
        db_path: str,
        default_ttl: int = 30,
        method_ttls: dict[str, int] | None = None,
    ) -> None:
        self._db = Database.open(db_path)
        self._default_ttl = default_ttl
        self._method_ttls: dict[str, int] = method_ttls or {}
        self._create_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_schema(self) -> None:
        self._db.exec(
            """CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key    TEXT PRIMARY KEY,
                method       TEXT,
                params_hash  TEXT,
                channel      TEXT,
                thread_ts    TEXT,
                response_body TEXT,
                status_code  INTEGER,
                content_type TEXT,
                created_at   REAL,
                ttl_seconds  INTEGER
            )"""
        )
        self._db.exec(
            "CREATE INDEX IF NOT EXISTS idx_cache_channel ON cache_entries (channel)"
        )
        self._db.exec(
            "CREATE INDEX IF NOT EXISTS idx_cache_method_channel ON cache_entries (method, channel)"
        )
        self._db.exec(
            "CREATE INDEX IF NOT EXISTS idx_cache_thread ON cache_entries (channel, thread_ts)"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def make_key(method: str, params: dict) -> str:
        """Return a deterministic sha256 hex digest for *method* + sorted *params*."""
        sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        raw = f"{method}?{sorted_params}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _ttl_for(self, method: str) -> int:
        return self._method_ttls.get(method, self._default_ttl)

    def lookup(self, method: str, params: dict) -> tuple[bytes, int, dict] | None:
        """Return ``(body, status_code, headers)`` or ``None`` on miss / expiry."""
        key = self.make_key(method, params)
        row = self._db.query_one(
            "SELECT response_body, status_code, content_type, created_at, ttl_seconds "
            "FROM cache_entries WHERE cache_key = $1",
            [key],
        )
        if row is None:
            return None

        age = time.time() - row["created_at"]
        if age >= row["ttl_seconds"]:
            # Expired — clean up lazily
            self._db.execute(
                "DELETE FROM cache_entries WHERE cache_key = $1", [key]
            )
            return None

        headers = {
            "content-type": row["content_type"],
            "x-cache-age": str(int(age)),
        }
        body = row["response_body"]
        if isinstance(body, str):
            body = body.encode()
        return (body, row["status_code"], headers)

    def store(
        self,
        method: str,
        params: dict,
        channel: str | None,
        thread_ts: str | None,
        body: bytes,
        status_code: int,
        content_type: str,
    ) -> None:
        """Insert or replace a cache entry.

        The caller should only call this for responses with ``ok: true``.
        """
        key = self.make_key(method, params)
        params_hash = hashlib.sha256(
            json.dumps(params, sort_keys=True).encode()
        ).hexdigest()
        ttl = self._ttl_for(method)

        # Upsert: delete then insert (portable across engines)
        self._db.execute(
            "DELETE FROM cache_entries WHERE cache_key = $1", [key]
        )
        self._db.execute(
            "INSERT INTO cache_entries "
            "(cache_key, method, params_hash, channel, thread_ts, "
            " response_body, status_code, content_type, created_at, ttl_seconds) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            [
                key,
                method,
                params_hash,
                channel or "",
                thread_ts or "",
                body,
                status_code,
                content_type,
                time.time(),
                ttl,
            ],
        )

    def invalidate_channel(self, channel: str) -> None:
        """Delete every cache entry that belongs to *channel*."""
        self._db.execute(
            "DELETE FROM cache_entries WHERE channel = $1", [channel]
        )

    def invalidate_thread(self, channel: str, thread_ts: str) -> None:
        """Delete cache entries for a specific thread in *channel*."""
        self._db.execute(
            "DELETE FROM cache_entries WHERE channel = $1 AND thread_ts = $2",
            [channel, thread_ts],
        )

    def invalidate_reactions(self, channel: str, timestamp: str) -> None:
        """Delete ``reactions.get`` entries for a message identified by *channel* + *timestamp*."""
        self._db.execute(
            "DELETE FROM cache_entries WHERE method = $1 AND channel = $2 AND thread_ts = $3",
            ["reactions.get", channel, timestamp],
        )

    def count(self) -> int:
        """Return the number of entries currently in the cache (including expired)."""
        row = self._db.query_one("SELECT COUNT(*) AS cnt FROM cache_entries")
        if row is None:
            return 0
        return int(row["cnt"])

    def is_healthy(self) -> bool:
        """Return ``True`` if the database is accessible."""
        try:
            self._db.query_one("SELECT 1 AS ok")
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
