# Implementation Tasks: slack-caching-proxy

## Task 1: Create constants module and TOML configuration loader (P)

> Requirements: 6, 9, 11

- [ ] Create `src/proxy/constants.py` with the `CACHEABLE_METHODS` frozenset (9 methods), `INVALIDATING_METHODS` frozenset (4 methods), `DEFAULT_METHOD_TTLS` dictionary, `DEFAULT_TTL = 60`, and a `VERSION` string
- [ ] Create `src/proxy/config.py` with frozen dataclasses (`ServerConfig`, `CacheConfig`, `UpstreamConfig`, `LoggingConfig`, `ProxyConfig`) and a `load_config()` function that reads TOML via `tomllib`, falls back to defaults on missing file with a logged warning, and calls `sys.exit()` on invalid TOML syntax
- [ ] Support config path override via `--config` CLI argument, `SLACK_PROXY_CONFIG` env var, and default `/etc/slack-proxy/config.toml` (in that priority order)
- [ ] Create `deploy/config.toml` reference configuration file matching the design specification values
- [ ] Create `tests/test_config.py` covering: valid config loads correctly, missing file returns defaults, invalid TOML raises SystemExit, partial config merges with defaults, unknown keys are ignored with warning

## Task 2: Create Stoolap cache engine with TTL and targeted invalidation (P)

> Requirements: 2, 3, 5, 9

- [ ] Create `src/proxy/cache.py` with a `CacheEngine` class backed by Stoolap, implementing `lookup()`, `store()`, `invalidate_channel()`, `invalidate_thread()`, `invalidate_reactions()`, `count()`, `is_healthy()`, and the static `make_key()` method
- [ ] Implement schema initialization (`CREATE TABLE IF NOT EXISTS cache_entries` with columns: `cache_key`, `method`, `params_hash`, `channel`, `thread_ts`, `response_body`, `status_code`, `content_type`, `created_at`, `ttl_seconds`) and three indexes (`idx_cache_channel`, `idx_cache_method_channel`, `idx_cache_thread`)
- [ ] Implement TTL resolution that looks up per-method TTL from config and falls back to the default 60s TTL; cache lookup must check `current_time - created_at < ttl_seconds` and return `None` on expiry
- [ ] Only cache responses where the Slack API returns `"ok": true`; never cache error responses
- [ ] Handle corrupted database at startup by catching the error, logging it, deleting the file, and recreating the database
- [ ] Store `channel` and `thread_ts` columns from request params to enable targeted invalidation queries; for `reactions.get` entries, store the `timestamp` param in the `thread_ts` column
- [ ] Create `tests/test_cache.py` using Stoolap in-memory mode (`Database.open(":memory:")`) covering: store and retrieve, TTL expiry returns None, overwrite existing key, invalidate by channel, invalidate by thread, invalidate reactions, count accuracy, `make_key` determinism, `make_key` param order independence

## Task 3: Create upstream HTTP client with error mapping (P)

> Requirements: 1, 13

- [ ] Create `src/proxy/upstream.py` with an `UpstreamClient` class wrapping `httpx.AsyncClient` (single persistent instance with connection pooling), exposing `forward_get()`, `forward_post()`, and `close()` methods, plus an `UpstreamResponse` frozen dataclass
- [ ] Forward the `Authorization` header verbatim without modification or validation; pass all query parameters and request body unchanged
- [ ] Map upstream errors: `httpx.TimeoutException`, `httpx.ConnectError`, and `httpx.HTTPError` produce HTTP 502 with a JSON error body (`{"ok": false, "error": "proxy_upstream_unreachable", "detail": "..."}`); internal exceptions produce HTTP 500 with a generic message that does not expose paths, config, or stack traces
- [ ] Forward Slack 4xx and 5xx responses verbatim with original status code and body
- [ ] Create `tests/test_upstream.py` using `pytest-httpx` covering: successful GET/POST forward, timeout returns 502, DNS failure returns 502, connection refused returns 502, 4xx forwarded as-is, 5xx forwarded as-is

## Task 4: Create cache invalidation rules module (P)

> Requirements: 4

- [ ] Create `src/proxy/invalidation.py` with an `INVALIDATION_MAP` dictionary mapping POST method names to invalidation handler functions, and a dispatcher `invalidate_for()` that executes the correct handler when a POST succeeds
- [ ] Implement `chat.postMessage` handler: invalidate `conversations.history` for the channel; if request body contained `thread_ts`, also invalidate `conversations.replies` for that thread
- [ ] Implement `chat.update` and `chat.delete` handlers: invalidate both `conversations.history` for the channel and `conversations.replies` for the thread identified by `ts` in the response
- [ ] Implement `reactions.add` handler: invalidate `reactions.get` entries for the affected message using `channel` and `timestamp` from the request body
- [ ] Skip invalidation entirely when the POST response has `"ok": false`
- [ ] Create `tests/test_invalidation.py` covering all four method handlers, the skip-on-failure case, and edge cases (missing channel/ts fields)

## Task 5: Create structured logging configuration (P)

> Requirements: 12

- [ ] Create `src/proxy/logging_config.py` that configures Python's `logging` module at startup using the level and format from `LoggingConfig`, writing to stdout/stderr for journald capture
- [ ] Define log events for: request received (INFO with method, source IP, cache status), cache HIT/MISS/STORE (DEBUG), cache invalidation (INFO with trigger method and entries removed), upstream errors (WARNING/ERROR with method and elapsed time), config loaded (INFO with host, port, db_path, TTL count), startup/shutdown (INFO)

## Task 6: Wire modules into FastAPI application with lifespan management

> Requirements: 1, 2, 4, 5, 11, 13, 14

- [ ] Refactor `src/proxy/service.py` to use the modular structure: import and initialize `ProxyConfig`, `CacheEngine`, `UpstreamClient`, and logging via the FastAPI lifespan context manager; open Stoolap database at startup, close on shutdown; add `stoolap-python>=0.2` to the PEP 723 dependencies
- [ ] Create `src/proxy/routes.py` with the `/api/{method:path}` route handler and `/health` endpoint; GET flow checks cache then forwards upstream; POST flow forwards then triggers invalidation; all responses include `X-Proxy-Cache` header (HIT/MISS/PASS)
- [ ] Implement pass-through degradation: when Stoolap is unreachable, set `_db_degraded` flag, bypass all cache operations, and forward directly to Slack; health endpoint returns 503 when degraded
- [ ] Handle unknown/unsupported methods by forwarding to Slack as pass-through without caching
- [ ] Support `--config` CLI argument and `SLACK_PROXY_CONFIG` env var for config path override
- [ ] Create `tests/test_routes.py` using `httpx.AsyncClient` with `ASGITransport` and in-memory Stoolap covering: GET cacheable HIT/MISS, GET non-cacheable pass-through, POST forward with invalidation, POST failure skips invalidation, X-Proxy-Cache header correctness, auth header forwarded, unknown method pass-through
- [ ] Create `tests/test_health.py` covering: healthy returns 200 with version/count/db_status, degraded returns 503

## Task 7: Add agent-side proxy support and fallback logic to all 7 scripts

> Requirements: 7, 8

- [ ] Update all 6 bash scripts (`slack-poll`, `slack-send`, `slack-react`, `slack-identity`, `slack-channels`, `slack-resolve`) to resolve `SLACK_API_BASE="${SLACK_PROXY_URL:-https://slack.com}"` at the top and replace all hardcoded `https://slack.com` references with `${SLACK_API_BASE}`
- [ ] Update `slack-heartbeat.py` to resolve `SLACK_BASE = os.environ.get("SLACK_PROXY_URL") or "https://slack.com"` and use it in the `slack_api()` helper
- [ ] Add the `slack_api_call()` fallback wrapper function to bash scripts: on curl exit codes 7/28/6 or HTTP 5xx, retry against `https://slack.com/api/{method}` directly
- [ ] Implement fallback alert throttling: on first fallback, check `~/.claude/slack-proxy-fallback-alerted` for timestamp; emit one-line stderr warning and write epoch to state file if no alert within last 10 minutes

## Task 8: Create systemd unit and deployment artifacts

> Requirements: 10

- [ ] Create `deploy/slack-proxy.service` systemd unit file with `ExecStart` using `uv run`, `Restart=on-failure`, `RestartSec=5`, `WantedBy=multi-user.target`, `After=network-online.target`, and hardening directives (`NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths=/var/lib/slack-proxy`, `ReadOnlyPaths=/etc/slack-proxy`)
- [ ] Verify the unit references the correct paths: application at `/opt/scc-slack/src/proxy/service.py`, config at `/etc/slack-proxy/config.toml`, working directory at `/opt/scc-slack`

## Task 9: Create end-to-end test suite and verify 80%+ coverage

> Requirements: 1, 2, 3, 4, 5, 9, 13, 14

- [ ] Create `tests/conftest.py` with shared pytest fixtures: in-memory Stoolap database, test `ProxyConfig`, `pytest-httpx` mock setup, and a FastAPI test client via `httpx.AsyncClient` with `ASGITransport`
- [ ] Create `tests/test_e2e.py` covering: cache round-trip (MISS then HIT), TTL expiry (patch `time.time` past TTL boundary), per-method TTL independence, write-through invalidation after `chat.postMessage`, thread reply invalidation with `thread_ts`, only cache `ok:true` responses, pass-through for unknown methods, auth header forwarded verbatim, DB degradation triggers pass-through mode, health endpoint healthy vs degraded, upstream timeout returns 502
- [ ] Configure `pytest-cov` with `--cov=src/proxy --cov-fail-under=80` and verify 80%+ line coverage across all source modules
- [ ]* Add coverage for concurrent identical GET requests verifying only one upstream call is made (multiple-agents scenario)
