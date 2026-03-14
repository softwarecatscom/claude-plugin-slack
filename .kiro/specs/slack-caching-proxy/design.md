# Technical Design: slack-caching-proxy

## 1. Architecture Overview

### 1.1 System Context

The slack-caching-proxy is a transparent HTTP reverse proxy that interposes between Claude Code agent scripts and the Slack Web API. Agents replace the base URL `https://slack.com` with the proxy URL (e.g., `http://localhost:8321`). The proxy forwards requests upstream, caches cacheable GET responses in a Stoolap on-disk database, and invalidates cache entries on POST write operations. Agents retain a fallback path to `https://slack.com` when the proxy is unreachable.

```
 +------------------+     +------------------+     +------------------+
 | Agent 1          |     | Agent 2          |     | Agent N          |
 | (slack-poll,     |     | (slack-poll,     |     | (slack-poll,     |
 |  slack-send,     |     |  slack-send,     |     |  slack-send,     |
 |  slack-react...) |     |  slack-react...) |     |  slack-react...) |
 +--------+---------+     +--------+---------+     +--------+---------+
          |                         |                         |
          | SLACK_PROXY_URL         | SLACK_PROXY_URL         | SLACK_PROXY_URL
          | (fallback: slack.com)   | (fallback: slack.com)   | (fallback: slack.com)
          |                         |                         |
          +------------+------------+------------+------------+
                       |
                       v
          +---------------------------+
          |   slack-caching-proxy     |
          |   (FastAPI + uvicorn)     |
          |   http://0.0.0.0:8321    |
          |                           |
          |  +---------------------+  |
          |  | Route Handler       |  |
          |  | /api/{method}       |  |
          |  +---------------------+  |
          |  | Cache Engine        |  |
          |  | (TTL, invalidation) |  |
          |  +---------------------+  |
          |  | Stoolap Storage     |  |
          |  | (on-disk DB)        |  |
          |  +---------------------+  |
          |  | httpx AsyncClient   |  |
          |  | (upstream Slack)    |  |
          |  +---------------------+  |
          +-------------+-------------+
                        |
                        v
              +-------------------+
              |  Slack Web API    |
              |  slack.com/api/*  |
              +-------------------+
```

### 1.2 Request Flow

```
Agent Request
    |
    v
[FastAPI /api/{method}] -----> [/health] --> return status JSON
    |
    +-- Is method cacheable?
    |       |
    |       +-- YES: cache_key = sha256(method + sorted_params)
    |       |       |
    |       |       +-- Cache HIT (TTL valid)? --> return cached response
    |       |       |                              X-Proxy-Cache: HIT
    |       |       +-- Cache MISS
    |       |               |
    |       |               v
    |       |           Forward GET to slack.com
    |       |               |
    |       |               v
    |       |           Response ok:true? --> store in Stoolap --> return
    |       |           Response ok:false? --> return (do NOT cache)
    |       |                                  X-Proxy-Cache: MISS
    |       |
    |       +-- NO (POST or unknown)
    |               |
    |               v
    |           Forward to slack.com
    |               |
    |               v
    |           Response ok:true AND method in INVALIDATING_METHODS?
    |               |
    |               +-- YES: invalidate related cache entries
    |               +-- NO: skip invalidation
    |               |
    |               v
    |           Return response, X-Proxy-Cache: PASS
    |
    v
  Agent receives response
```

### 1.3 Requirements Traceability

| Component | Requirements Covered |
|-----------|---------------------|
| Route Handler | 1.1, 1.2, 1.3, 1.4, 1.5 |
| Cache Engine | 2.1, 2.2, 2.3, 2.4, 2.5, 9.1, 9.2, 9.3, 9.4 |
| TTL Manager | 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7 |
| Invalidation Logic | 4.1, 4.2, 4.3, 4.4, 4.5, 4.6 |
| Stoolap Storage | 5.1, 5.2, 5.3, 5.4, 5.5 |
| Config Loader | 6.1, 6.2, 6.3, 6.4, 6.5, 6.6 |
| Agent-Side Fallback | 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 8.4, 8.5 |
| systemd Unit | 10.1, 10.2, 10.3, 10.4, 10.5 |
| PEP 723 Metadata | 11.1, 11.2, 11.3 |
| Logging | 12.1, 12.2, 12.3, 12.4, 12.5 |
| Error Handling | 13.1, 13.2, 13.3, 13.4 |
| Health Endpoint | 14.1, 14.2, 14.3 |

---

## 2. Module Structure

### 2.1 File Layout

```
src/proxy/
  service.py          # Main entry point. PEP 723 metadata block.
                      # FastAPI app, lifespan, uvicorn bootstrap.
  config.py           # TOML configuration loading, defaults, dataclasses.
  cache.py            # Stoolap cache engine: store, lookup, invalidate, schema init.
  routes.py           # /api/{method} route handler and /health endpoint.
  upstream.py         # httpx AsyncClient lifecycle and Slack API forwarding.
  invalidation.py     # Write-through invalidation rules mapping POST methods
                      # to affected cache entries.
  constants.py        # CACHEABLE_METHODS, INVALIDATING_METHODS, default TTLs,
                      # version string.
  logging_config.py   # Structured logging setup.

tests/
  conftest.py         # Shared fixtures: mock Stoolap DB, test config, httpx mock.
  test_config.py      # TOML parsing, defaults, validation.
  test_cache.py       # Cache store/lookup/invalidate/TTL expiry.
  test_routes.py      # Route handler with mocked upstream and cache.
  test_upstream.py    # httpx forwarding, error handling, timeout.
  test_invalidation.py # Invalidation rule mapping correctness.
  test_health.py      # Health endpoint responses.
  test_e2e.py         # End-to-end tests: full proxy stack with mocked Slack.

deploy/
  config.toml         # Reference configuration file.
  slack-proxy.service  # systemd unit file.
```

### 2.2 Dependency Graph

```
service.py
  +-> config.py
  +-> cache.py          --> config.py
  +-> routes.py         --> cache.py, upstream.py, invalidation.py, constants.py
  +-> upstream.py       --> config.py
  +-> invalidation.py   --> cache.py, constants.py
  +-> constants.py
  +-> logging_config.py --> config.py
```

No circular dependencies. `constants.py` and `config.py` are leaf modules.

---

## 3. Data Model

### 3.1 Stoolap Cache Table Schema

```sql
CREATE TABLE IF NOT EXISTS cache_entries (
    cache_key    TEXT PRIMARY KEY,
    method       TEXT NOT NULL,
    params_hash  TEXT NOT NULL,
    channel      TEXT,
    thread_ts    TEXT,
    response_body TEXT NOT NULL,
    status_code  INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    created_at   REAL NOT NULL,
    ttl_seconds  INTEGER NOT NULL
);
```

**Column semantics:**

| Column | Type | Purpose |
|--------|------|---------|
| `cache_key` | TEXT PK | SHA-256 hex digest of `method + sorted_params` |
| `method` | TEXT | Slack API method name (e.g., `conversations.history`) |
| `params_hash` | TEXT | SHA-256 hex digest of sorted request parameters only |
| `channel` | TEXT | Extracted channel ID from params (nullable for methods like `auth.test`) |
| `thread_ts` | TEXT | Extracted thread timestamp from params (nullable, used for `conversations.replies`) |
| `response_body` | TEXT | Raw JSON response body from Slack |
| `status_code` | INTEGER | HTTP status code (always 200 for cached entries since only `ok:true` is cached) |
| `content_type` | TEXT | Content-Type header value |
| `created_at` | REAL | Unix epoch timestamp when the entry was stored |
| `ttl_seconds` | INTEGER | TTL applied to this entry (denormalized for query convenience) |

**Index for targeted invalidation:**

```sql
CREATE INDEX IF NOT EXISTS idx_cache_channel ON cache_entries(channel);
CREATE INDEX IF NOT EXISTS idx_cache_method_channel ON cache_entries(method, channel);
CREATE INDEX IF NOT EXISTS idx_cache_thread ON cache_entries(channel, thread_ts);
```

### 3.2 Cache Key Generation

```
cache_key = SHA-256( "{method}?{sorted_query_params}" )
```

Where `sorted_query_params` is a deterministic `&`-joined string of `key=value` pairs sorted lexicographically by key. The `Authorization` header is excluded from the key because auth is pass-through and all agents share the same workspace token.

### 3.3 TTL Evaluation

A cache entry is valid when:

```
current_time - created_at < ttl_seconds
```

Expired entries are not proactively deleted; they are treated as cache misses and overwritten on the next request. A periodic cleanup is not required for MVP but the schema supports it via `SELECT ... WHERE (created_at + ttl_seconds) < :now`.

---

## 4. API Design

### 4.1 Route Definitions

| Route | Methods | Handler | Description |
|-------|---------|---------|-------------|
| `/api/{method:path}` | GET, POST | `proxy_slack()` | Main proxy route (Req 1.1-1.5) |
| `/health` | GET | `health_check()` | Service health (Req 14.1-14.3) |

### 4.2 Proxy Route Handler Interface

```python
@app.api_route("/api/{method:path}", methods=["GET", "POST"])
async def proxy_slack(method: str, request: Request) -> Response:
    """
    Proxy any Slack API call.

    GET requests for cacheable methods check cache first.
    POST requests pass through and trigger cache invalidation.
    Unknown methods are forwarded without caching.

    Response headers include X-Proxy-Cache: HIT | MISS | PASS
    """
```

**GET flow:**
1. Extract query params from `request.query_params`.
2. If method is in `CACHEABLE_METHODS`, compute cache key and query Stoolap.
3. On HIT: return cached response with `X-Proxy-Cache: HIT`.
4. On MISS: forward to Slack via `upstream.forward_get()`.
5. If response `ok:true`, store in cache via `cache.store()`.
6. Return response with `X-Proxy-Cache: MISS`.

**POST flow:**
1. Read request body via `await request.body()`.
2. Forward to Slack via `upstream.forward_post()`.
3. If response `ok:true` and method is in `INVALIDATING_METHODS`, execute invalidation rules.
4. Return response with `X-Proxy-Cache: PASS`.

### 4.3 Health Endpoint Interface

```python
@app.get("/health")
async def health_check() -> JSONResponse:
    """
    Returns:
        200: {"ok": true, "version": "...", "db_status": "ok", "cache_entries": N}
        503: {"ok": false, "version": "...", "db_status": "error", "error": "..."}
    """
```

### 4.4 Response Headers

All proxy responses include:

| Header | Values | Purpose |
|--------|--------|---------|
| `X-Proxy-Cache` | `HIT`, `MISS`, `PASS` | Cache diagnostic |
| `Content-Type` | Preserved from Slack | Response format |

### 4.5 Error Response Format

All proxy-generated errors use a JSON structure consistent with the Slack API format:

```json
{
    "ok": false,
    "error": "proxy_upstream_unreachable",
    "detail": "Connection to slack.com timed out after 30s"
}
```

---

## 5. Cache Engine

### 5.1 Public Interface

```python
class CacheEngine:
    """On-disk cache backed by Stoolap."""

    def __init__(self, db: Database, config: CacheConfig) -> None: ...

    def lookup(self, method: str, params: dict[str, str]) -> CacheResult | None:
        """Return cached response if valid, None on miss or expiry."""

    def store(
        self,
        method: str,
        params: dict[str, str],
        response_body: bytes,
        status_code: int,
        content_type: str,
    ) -> None:
        """Store a cacheable response. Overwrites any existing entry for same key."""

    def invalidate_channel(self, channel: str) -> int:
        """Remove all cache entries for a given channel. Returns count removed."""

    def invalidate_thread(self, channel: str, thread_ts: str) -> int:
        """Remove conversations.replies entries for a specific thread. Returns count."""

    def invalidate_reactions(self, channel: str, timestamp: str) -> int:
        """Remove reactions.get entries for a specific message. Returns count."""

    def count(self) -> int:
        """Return total number of cache entries (for health endpoint)."""

    def is_healthy(self) -> bool:
        """Return True if Stoolap database is accessible."""

    @staticmethod
    def make_key(method: str, params: dict[str, str]) -> str:
        """Compute deterministic SHA-256 cache key."""
```

### 5.2 CacheResult Type

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CacheResult:
    body: bytes
    status_code: int
    content_type: str
```

### 5.3 TTL Resolution

```python
def _resolve_ttl(self, method: str) -> int:
    """Look up per-method TTL from config, fall back to default."""
    return self.config.method_ttls.get(method, self.config.default_ttl)
```

### 5.4 Stoolap Connection Lifecycle

The Stoolap `Database` is opened once at application startup via the FastAPI lifespan context manager and closed on shutdown. All cache operations use this single connection.

```python
from contextlib import asynccontextmanager
from stoolap import Database

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database.open(f"file://{config.cache.db_path}")
    _init_schema(db)
    app.state.cache = CacheEngine(db, config.cache)
    app.state.upstream = UpstreamClient(config.upstream)
    yield
    db.close()
    await app.state.upstream.close()
```

### 5.5 Schema Initialization

On startup, `_init_schema(db)` executes the `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements from Section 3.1. If the database file is corrupted, the engine catches `StoolapError`, logs the error, deletes the file, and recreates the database (Req 5.5).

---

## 6. Cache Invalidation

### 6.1 Invalidation Rules

```python
INVALIDATION_MAP: dict[str, Callable[[CacheEngine, dict[str, str]], int]] = {
    "chat.postMessage":  _invalidate_post_message,
    "chat.update":       _invalidate_chat_update,
    "chat.delete":       _invalidate_chat_delete,
    "reactions.add":     _invalidate_reactions_add,
}
```

### 6.2 Rule Definitions

**`chat.postMessage` (Req 4.2):**
- Extract `channel` from the POST response body.
- Call `cache.invalidate_channel(channel)` to remove all `conversations.history` entries for the channel.
- If the request body contained `thread_ts`, also call `cache.invalidate_thread(channel, thread_ts)` to remove matching `conversations.replies` entries.

**`chat.update` (Req 4.3):**
- Extract `channel` and `ts` from the response body.
- Call `cache.invalidate_channel(channel)`.
- Call `cache.invalidate_thread(channel, ts)`.

**`chat.delete` (Req 4.4):**
- Extract `channel` and `ts` from the response body.
- Call `cache.invalidate_channel(channel)`.
- Call `cache.invalidate_thread(channel, ts)`.

**`reactions.add` (Req 4.5):**
- Extract `channel` and `timestamp` from the request body.
- Call `cache.invalidate_reactions(channel, timestamp)`.

### 6.3 Invalidation SQL

```sql
-- invalidate_channel: remove conversations.history for a channel
DELETE FROM cache_entries
WHERE channel = $1
  AND method = 'conversations.history';

-- invalidate_thread: remove conversations.replies for a thread
DELETE FROM cache_entries
WHERE channel = $1
  AND thread_ts = $2
  AND method = 'conversations.replies';

-- invalidate_reactions: remove reactions.get for a message
DELETE FROM cache_entries
WHERE channel = $1
  AND params_hash LIKE '%timestamp=' || $2 || '%';
```

For `reactions.get` invalidation, the `params_hash` column is not usable directly. Instead, the cache key for `reactions.get` entries will encode the `channel` and `timestamp` parameters into the `channel` and `thread_ts` columns respectively during storage, enabling targeted deletion via indexed lookup.

---

## 7. Configuration

### 7.1 Config Dataclasses

```python
from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8321

@dataclass(frozen=True, slots=True)
class CacheConfig:
    db_path: str = "/var/lib/slack-proxy/cache.db"
    default_ttl: int = 60
    method_ttls: dict[str, int] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class UpstreamConfig:
    base_url: str = "https://slack.com"
    timeout: float = 30.0

@dataclass(frozen=True, slots=True)
class LoggingConfig:
    level: str = "INFO"
    format: str = "%(asctime)s %(levelname)s %(name)s %(message)s"

@dataclass(frozen=True, slots=True)
class ProxyConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    upstream: UpstreamConfig = field(default_factory=UpstreamConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
```

### 7.2 Reference TOML Configuration

```toml
# /etc/slack-proxy/config.toml

[server]
host = "0.0.0.0"
port = 8321

[cache]
db_path = "/var/lib/slack-proxy/cache.db"
default_ttl = 60

[cache.method_ttls]
"conversations.history" = 60
"conversations.replies" = 60
"conversations.list" = 120
"conversations.info" = 120
"users.info" = 300
"users.list" = 300
"pins.list" = 300
"auth.test" = 300
"reactions.get" = 60

[upstream]
base_url = "https://slack.com"
timeout = 30.0

[logging]
level = "INFO"
format = "%(asctime)s %(levelname)s %(name)s %(message)s"
```

### 7.3 Config Loader

```python
import tomllib
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("/etc/slack-proxy/config.toml")

def load_config(path: Path = DEFAULT_CONFIG_PATH) -> ProxyConfig:
    """Load config from TOML, falling back to defaults on missing file.

    Raises SystemExit on invalid TOML syntax (Req 6.6).
    Logs warning and returns defaults on missing file (Req 6.5).
    """
```

The loader uses `tomllib` (stdlib in Python 3.11+). It applies a strict merge: only recognized keys are accepted; unknown keys are logged as warnings and ignored. This prevents TOML typos from silently passing.

### 7.4 Config Path Override

The config path can be overridden via:
1. `--config` CLI argument (highest priority).
2. `SLACK_PROXY_CONFIG` environment variable.
3. Default `/etc/slack-proxy/config.toml`.

---

## 8. Upstream Client

### 8.1 Interface

```python
class UpstreamClient:
    """Async HTTP client for forwarding requests to Slack."""

    def __init__(self, config: UpstreamConfig) -> None:
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout,
            follow_redirects=True,
        )

    async def forward_get(
        self,
        method: str,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> UpstreamResponse: ...

    async def forward_post(
        self,
        method: str,
        body: bytes,
        headers: dict[str, str],
    ) -> UpstreamResponse: ...

    async def close(self) -> None:
        await self._client.aclose()
```

### 8.2 UpstreamResponse Type

```python
@dataclass(frozen=True, slots=True)
class UpstreamResponse:
    status_code: int
    body: bytes
    content_type: str
    json_body: dict[str, object] | None  # Parsed if content-type is JSON
```

### 8.3 Client Lifecycle

The `httpx.AsyncClient` is created once during the FastAPI lifespan startup and reused for all requests. This avoids the overhead of creating a new client (and TCP connection) per request. The client is closed on shutdown.

### 8.4 Error Mapping

| Upstream Condition | Proxy Response | Req |
|-------------------|----------------|-----|
| Slack returns 4xx | Forward as-is | 13.1 |
| Slack returns 5xx | Forward as-is | 13.1 |
| Connection timeout | HTTP 502 + JSON error | 13.2 |
| DNS failure | HTTP 502 + JSON error | 13.2 |
| Connection refused | HTTP 502 + JSON error | 13.2 |
| Internal exception | HTTP 500 + generic error | 13.3 |

---

## 9. Agent-Side Fallback

### 9.1 Design

The fallback logic lives in the agent scripts, not in the proxy. It applies to the bash scripts that make `curl` calls to `https://slack.com/api/*`.

### 9.2 Fallback Wrapper Function

A shared shell function will be added to a common include file or inlined into scripts that make Slack API calls. The function:

1. Checks if `SLACK_PROXY_URL` is set in `~/.claude/slack.conf`.
2. If set, attempts the request against `${SLACK_PROXY_URL}/api/{method}`.
3. On connection failure (curl exit codes 7, 28, 6) or HTTP 5xx response, retries against `https://slack.com/api/{method}`.
4. On first fallback, checks `~/.claude/slack-proxy-fallback-alerted` for timestamp.
5. If no alert within last 10 minutes, emits a one-line warning to stderr and writes current epoch to the state file.

### 9.3 State File Format

`~/.claude/slack-proxy-fallback-alerted` contains a single line: the Unix epoch timestamp of the last alert.

### 9.4 Affected Scripts

| Script | API Calls | Modification |
|--------|-----------|--------------|
| `slack-poll` | `conversations.history`, `conversations.replies` | Replace `https://slack.com` with `${SLACK_API_BASE}` variable |
| `slack-send` | `chat.postMessage`, `chat.update` | Replace `https://slack.com` with `${SLACK_API_BASE}` variable |
| `slack-react` | `reactions.get`, `reactions.add` | Replace `https://slack.com` with `${SLACK_API_BASE}` variable |
| `slack-identity` | `auth.test`, `users.info` | Replace `https://slack.com` with `${SLACK_API_BASE}` variable |
| `slack-channels` | `conversations.info`, `conversations.list` | Replace `https://slack.com` with `${SLACK_API_BASE}` variable |
| `slack-resolve` | `users.info`, `users.list`, `conversations.list`, `conversations.info` | Replace `https://slack.com` with `${SLACK_API_BASE}` variable |
| `slack-heartbeat.py` | Multiple | Replace base URL in `slack_api()` helper |

Each script will resolve the base URL at the top:

```bash
SLACK_API_BASE="${SLACK_PROXY_URL:-https://slack.com}"
```

The Python script `slack-heartbeat.py` will use:

```python
SLACK_BASE = os.environ.get("SLACK_PROXY_URL") or "https://slack.com"
```

The `SLACK_PROXY_URL` value is loaded from `~/.claude/slack.conf` by the agent runtime before scripts execute, so it is available as an environment variable or can be sourced from the config file.

### 9.5 Fallback Shell Function

```bash
# slack_api_call URL [curl_args...]
# Tries proxy first, falls back to direct Slack on failure.
slack_api_call() {
    local url="$1"; shift
    local response exit_code

    response=$(curl -s -w "\n%{http_code}" "$url" "$@") || exit_code=$?
    local http_code="${response##*$'\n'}"
    local body="${response%$'\n'*}"

    # Success: proxy responded with non-5xx
    if [ "${exit_code:-0}" -eq 0 ] && [ "${http_code:-0}" -lt 500 ]; then
        echo "$body"
        return 0
    fi

    # Fallback: replace proxy URL with slack.com
    local direct_url="${url/${SLACK_PROXY_URL}/https://slack.com}"
    _emit_fallback_alert
    response=$(curl -s "$direct_url" "$@")
    echo "$response"
}
```

---

## 10. Logging

### 10.1 Log Events

| Event | Level | Fields |
|-------|-------|--------|
| Request received | INFO | `method`, `source_ip`, `cache_status` |
| Cache HIT | DEBUG | `method`, `cache_key`, `age_seconds` |
| Cache MISS | DEBUG | `method`, `cache_key` |
| Cache STORE | DEBUG | `method`, `cache_key`, `ttl_seconds` |
| Cache INVALIDATE | INFO | `method`, `cache_key`, `trigger_method`, `entries_removed` |
| Upstream error | WARNING | `method`, `status_code`, `error`, `elapsed_ms` |
| Upstream unreachable | ERROR | `method`, `error_type`, `elapsed_ms` |
| Config loaded | INFO | `host`, `port`, `db_path`, `default_ttl`, `method_count` |
| DB degraded | ERROR | `error`, `mode: pass-through` |
| Startup | INFO | `version`, `host`, `port` |
| Shutdown | INFO | `reason` |

### 10.2 Implementation

Standard Python `logging` module configured at startup via `logging_config.py`. Logs are written to stdout/stderr for capture by systemd journald (Req 12.5). Log level is set from the TOML config (Req 6.4, 12.5).

---

## 11. Error Handling Strategy

### 11.1 Error Categories and Responses

```
+-----------------------------------+----------+---------------------------+
| Condition                         | Status   | Behavior                  |
+-----------------------------------+----------+---------------------------+
| Slack returns 4xx                 | 4xx      | Forward verbatim (13.1)   |
| Slack returns 5xx                 | 5xx      | Forward verbatim (13.1)   |
| Upstream unreachable              | 502      | JSON error body (13.2)    |
| Internal proxy error              | 500      | Generic JSON error (13.3) |
| Stoolap DB unreachable            | 200*     | Pass-through mode (13.4)  |
| Stoolap DB corrupted at startup   | N/A      | Recreate DB, log (5.5)    |
| Invalid TOML config               | N/A      | Fail to start (6.6)       |
| Missing config file               | N/A      | Use defaults, warn (6.5)  |
+-----------------------------------+----------+---------------------------+
* Requests succeed via pass-through; only caching is degraded.
```

### 11.2 Pass-Through Degradation

When the Stoolap database becomes unreachable during operation (Req 13.4), the proxy sets an internal `_db_degraded` flag. All subsequent requests bypass cache lookup and storage, forwarding directly to Slack. The health endpoint returns HTTP 503 to signal degraded state. The flag is re-evaluated on each health check attempt to detect recovery.

### 11.3 Upstream Error Handling

All upstream calls are wrapped in a try/except that catches `httpx.TimeoutException`, `httpx.ConnectError`, and `httpx.HTTPError`. Each maps to an HTTP 502 response with a structured JSON body that includes the error type and a human-readable detail message. No internal state (paths, config values) is exposed in error responses (Req 13.3).

---

## 12. Deployment

### 12.1 systemd Unit File

```ini
# /etc/systemd/system/slack-proxy.service
[Unit]
Description=Slack Caching Proxy (scc-slack-proxy)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/env uv run /opt/scc-slack/src/proxy/service.py --config /etc/slack-proxy/config.toml
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=slack-proxy
WorkingDirectory=/opt/scc-slack

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/slack-proxy
ReadOnlyPaths=/etc/slack-proxy

[Install]
WantedBy=multi-user.target
```

### 12.2 Deployment Layout

```
/opt/scc-slack/                    # Application code (from repo)
  src/proxy/service.py             # Main entry point
  src/proxy/*.py                   # Module files

/etc/slack-proxy/
  config.toml                      # Configuration

/var/lib/slack-proxy/
  cache.db                         # Stoolap database (created at runtime)

/etc/systemd/system/
  slack-proxy.service              # systemd unit
```

### 12.3 Operational Commands

```bash
# Enable and start
sudo systemctl enable --now slack-proxy

# Check status
systemctl status slack-proxy

# View logs
journalctl -u slack-proxy -f

# Restart after config change
sudo systemctl restart slack-proxy

# Clear cache (stop, delete DB, start)
sudo systemctl stop slack-proxy
sudo rm /var/lib/slack-proxy/cache.db
sudo systemctl start slack-proxy
```

### 12.4 PEP 723 Inline Metadata

The `service.py` file declares all dependencies inline (Req 11.1, 11.2):

```python
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "fastapi>=0.115",
#     "uvicorn[standard]>=0.34",
#     "httpx>=0.28",
#     "stoolap-python>=0.2",
# ]
# ///
```

The systemd unit uses `uv run` which reads this metadata and resolves dependencies automatically (Req 11.3).

---

## 13. Constants and Method Classification

### 13.1 Cacheable Methods (Req 9.1)

```python
CACHEABLE_METHODS: frozenset[str] = frozenset({
    "conversations.history",
    "conversations.replies",
    "conversations.list",
    "conversations.info",
    "users.info",
    "users.list",
    "pins.list",
    "auth.test",
    "reactions.get",
})
```

### 13.2 Invalidating Methods (Req 9.2)

```python
INVALIDATING_METHODS: frozenset[str] = frozenset({
    "chat.postMessage",
    "chat.update",
    "chat.delete",
    "reactions.add",
})
```

### 13.3 Default TTL Values

```python
DEFAULT_METHOD_TTLS: dict[str, int] = {
    "conversations.history": 60,
    "conversations.replies": 60,
    "conversations.list": 120,
    "conversations.info": 120,
    "users.info": 300,
    "users.list": 300,
    "pins.list": 300,
    "auth.test": 300,
    "reactions.get": 60,
}
DEFAULT_TTL: int = 60
```

### 13.4 Pass-Through Methods

Any method not in `CACHEABLE_METHODS` is forwarded to Slack without caching (Req 1.5, 9.2). This includes the 18+ remaining methods used by the `slack` CLI (files.*, reminders.*, dnd.*, users.setPresence, users.setActive, users.profile.set, im.list) as well as any unknown methods.

---

## 14. Testing Strategy

### 14.1 Test Infrastructure

- **Framework**: pytest with pytest-asyncio for async test support.
- **HTTP Mocking**: `pytest-httpx` for mocking httpx upstream calls.
- **Coverage**: `pytest-cov` with 80% minimum line coverage target.
- **App Testing**: `httpx.AsyncClient` with `ASGITransport` for testing the FastAPI app directly (no server startup).
- **Database**: Stoolap in-memory mode (`Database.open(":memory:")`) for isolated tests.

### 14.2 Unit Test Plan

| Test Module | Focus | Key Test Cases |
|-------------|-------|----------------|
| `test_config.py` | TOML parsing | Valid config loads correctly; missing file returns defaults; invalid TOML raises SystemExit; partial config merges with defaults; unknown keys ignored |
| `test_cache.py` | Cache engine | Store and retrieve entry; TTL expiry returns None; overwrite existing key; invalidate by channel; invalidate by thread; invalidate reactions; count returns correct total; make_key determinism; make_key param order independence |
| `test_routes.py` | Route handler | GET cacheable method returns cached on HIT; GET cacheable method forwards on MISS; GET non-cacheable forwards without caching; POST forwards and invalidates; POST failure does not invalidate; X-Proxy-Cache header set correctly; auth header forwarded verbatim; unknown method passes through |
| `test_upstream.py` | HTTP client | Successful GET forward; successful POST forward; timeout returns 502; DNS failure returns 502; connection refused returns 502; 4xx forwarded as-is; 5xx forwarded as-is |
| `test_invalidation.py` | Invalidation rules | postMessage invalidates channel history; postMessage with thread_ts invalidates replies; chat.update invalidates channel and thread; chat.delete invalidates channel and thread; reactions.add invalidates reactions.get; failed POST does not invalidate |
| `test_health.py` | Health endpoint | Returns 200 with version, count, db_status; returns 503 when DB degraded |

### 14.3 End-to-End Test Plan

E2E tests use the full FastAPI app with a real in-memory Stoolap database and mocked upstream Slack responses via `pytest-httpx`.

| Test Case | Description | Requirements Verified |
|-----------|-------------|----------------------|
| Cache round-trip | GET conversations.history, verify MISS, repeat, verify HIT | 2.1, 2.2, 2.5 |
| TTL expiry | Store entry, advance time past TTL, verify MISS | 2.3, 3.3 |
| Per-method TTL | Configure different TTLs, verify each method expires independently | 3.1, 3.4-3.7 |
| Write-through invalidation | POST chat.postMessage, verify conversations.history cache cleared | 4.2 |
| Thread reply invalidation | POST chat.postMessage with thread_ts, verify conversations.replies cleared | 4.2 |
| Only cache ok:true | Mock Slack returning ok:false, verify not cached | 9.3, 9.4 |
| Pass-through method | Request files.list, verify forwarded without caching | 1.5, 9.2 |
| Auth pass-through | Send Authorization header, verify forwarded to Slack verbatim | 1.3 |
| DB degradation | Close DB mid-operation, verify pass-through mode | 13.4 |
| Health when healthy | GET /health, verify 200 with correct structure | 14.1, 14.2 |
| Health when degraded | Break DB, GET /health, verify 503 | 14.3 |
| Multiple agents | Two concurrent identical GETs, verify only one upstream call | 2.5 |
| Upstream timeout | Mock slow Slack response, verify 502 with JSON error | 13.2 |

### 14.4 Mocking Approach

- **Upstream Slack**: `pytest-httpx` intercepts all `httpx.AsyncClient` requests. Each test registers expected request/response pairs. Unmatched requests fail the test.
- **Stoolap Database**: In-memory database created per test via `Database.open(":memory:")`. Full schema is initialized. No mocking of the DB layer itself -- tests exercise real SQL.
- **Time**: `time.time()` is patched via `unittest.mock.patch` for TTL expiry tests, advancing the clock past the TTL boundary.
- **Config**: Test fixtures provide `ProxyConfig` instances with known values. No file I/O in unit tests.

### 14.5 Coverage Targets

| Scope | Target | Measurement |
|-------|--------|-------------|
| Unit tests | 80%+ line coverage of `src/proxy/` | `pytest --cov=src/proxy --cov-fail-under=80` |
| E2E tests | 80%+ of the 27 supported API methods exercised | Test case audit |
| Branch coverage | Not targeted for MVP | Future improvement |

---

## 15. Performance Considerations

### 15.1 Latency Budget

| Operation | Target | Mechanism |
|-----------|--------|-----------|
| Cache HIT response | < 50ms | Stoolap indexed lookup + in-process (Req NFR-1) |
| Cache MISS response | Slack latency + ~10ms overhead | Single upstream call |
| POST pass-through | Slack latency + ~5ms overhead | No cache interaction on forward |

### 15.2 Connection Reuse

The `httpx.AsyncClient` maintains a connection pool to `slack.com`. The default pool size (100 connections, 20 per host) is sufficient for the expected load of 4 agents at 1 request/minute each.

### 15.3 Concurrency

FastAPI handles concurrent requests via asyncio. The Stoolap `Database` connection is used from a single event loop. Stoolap supports concurrent reads. Write operations (cache store, invalidation) are serialized by the GIL and the single-connection model, which is acceptable for the expected write volume (~4 stores and ~1 invalidation per minute).

---

## 16. Security Considerations

### 16.1 Authentication

The proxy does not perform any authentication itself. The `Authorization` header from agent requests is forwarded verbatim to Slack (Req 1.3). The proxy binds to `0.0.0.0:8321` by default; in production, the host should be restricted to `127.0.0.1` or the local network if only local agents need access.

### 16.2 Token Exposure

Cached responses may contain sensitive data (message content, user information). The Stoolap database at `/var/lib/slack-proxy/cache.db` should have restricted file permissions (mode `0600`, owned by the service user). The systemd unit's `ProtectSystem=strict` and `ReadWritePaths` directives limit filesystem access.

### 16.3 Error Information Leakage

Proxy-generated error responses (502, 500) include descriptive error types but never expose internal paths, configuration values, or stack traces (Req 13.3).
