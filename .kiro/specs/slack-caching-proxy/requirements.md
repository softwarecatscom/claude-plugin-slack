# Requirements: slack-caching-proxy

## Project Description

A shared Python FastAPI caching proxy service that sits between Claude Code agents and the Slack Web API. Mirrors the Slack API faithfully (same paths, auth pass-through, same response format). Caches GET responses on disk using Stoolap, passes POST requests through with cache invalidation. Agents change one config value to use it. Auto-fallback to direct Slack calls if proxy unreachable. Deployed as systemd service. Tech stack: Python 3.13, FastAPI, uvicorn, httpx, Stoolap, uv with PEP 723. 80%+ test coverage with pytest.

## Introduction

### Feature Summary

A transparent caching proxy for the Slack Web API that reduces redundant API calls across multiple Claude Code agents sharing the same Slack workspace.

### Business Value

Four agents polling Slack independently produce 4x the API calls for identical data. This proxy collapses redundant reads to a single upstream call per TTL window, reducing token burn, improving response latency, and eliminating blind spots caused by narrow history windows.

### Scope

**In scope (Phase 1 MVP):**
- Transparent proxy for all 27 Slack API methods used by the plugin
- On-disk caching with Stoolap for GET endpoints
- Write-through cache invalidation on POST endpoints
- Per-method configurable TTL
- TOML-based configuration
- systemd deployment
- Agent-side auto-fallback to direct Slack calls
- 80%+ test coverage

**Out of scope (Phase 2+):**
- TOON compression
- Edit detection and mention scanning
- Full thread visibility beyond standard history window (**critical** — MVP caching alone does not fix the 50-message thread-window gap from AGT-46; Phase 2 thread visibility is required to resolve this)
- Socket Mode real-time events
- Observability dashboards

**Known MVP limitation:** Messages from humans or external bots arriving between cache refreshes will not trigger cache invalidation since they bypass the proxy. TTL (30s max staleness) bounds this. Phase 3 Socket Mode eliminates it.

## Requirements

### Requirement 1: API Mirroring

**User Story:** As a Claude Code agent, I want the proxy to mirror the Slack Web API exactly, so that I can switch between direct Slack calls and proxied calls by changing a single URL.

#### Acceptance Criteria

1. WHEN the proxy receives a request to `/api/{method}` THEN the proxy SHALL forward the request to `https://slack.com/api/{method}` preserving the HTTP method, headers, query parameters, and request body
2. WHEN the proxy receives a response from Slack THEN the proxy SHALL return the response to the caller with the same JSON body structure and HTTP status code
3. WHEN the proxy receives a request with an `Authorization` header THEN the proxy SHALL forward that header verbatim to Slack without modification or validation
4. WHEN the proxy receives a request for any of the 27 supported Slack API methods THEN the proxy SHALL handle the request without requiring proxy-specific authentication or API keys
5. IF the request targets a Slack API method not in the supported 27 THEN the proxy SHALL forward the request to Slack as a pass-through without caching

#### Additional Details
- **Priority**: High
- **Complexity**: Medium
- **Dependencies**: None
- **Assumptions**: Agents use standard Slack Web API request format

### Requirement 2: GET Request Caching

**User Story:** As a system operator, I want GET responses cached on disk, so that redundant API calls from multiple agents are collapsed into a single upstream call per TTL window.

#### Acceptance Criteria

1. WHEN the proxy receives a GET request for a cacheable method and a valid cache entry exists with an unexpired TTL THEN the proxy SHALL return the cached response without forwarding the request to Slack
2. WHEN the proxy receives a GET request for a cacheable method and no valid cache entry exists THEN the proxy SHALL forward the request to Slack, cache the response, and return it to the caller
3. WHEN a cached entry's TTL expires THEN the proxy SHALL treat the next request for that entry as a cache miss and fetch fresh data from Slack
4. WHEN the proxy caches a response THEN the proxy SHALL key the cache entry by the combination of the API method name and a hash of the request parameters
5. WHEN multiple agents send identical GET requests within the same TTL window THEN the proxy SHALL serve all requests after the first from cache

#### Additional Details
- **Priority**: High
- **Complexity**: High
- **Dependencies**: Requirement 1 (API Mirroring)
- **Assumptions**: Stoolap provides reliable on-disk key-value storage

### Requirement 3: Per-Method TTL Configuration

**User Story:** As a system operator, I want to configure cache TTL per Slack API method, so that frequently changing data is refreshed more often than static data.

#### Acceptance Criteria

1. WHEN the proxy starts THEN the proxy SHALL load per-method TTL values from the TOML configuration file
2. IF a method has no explicit TTL configured THEN the proxy SHALL use a default TTL of 60 seconds as defined in the configuration
3. WHEN a cacheable response is stored THEN the proxy SHALL apply the TTL corresponding to that specific API method
4. WHEN the configuration specifies `conversations.history` with a TTL of 60 seconds THEN the proxy SHALL expire cached `conversations.history` responses after 60 seconds
5. WHEN the configuration specifies `conversations.replies` with a TTL of 60 seconds THEN the proxy SHALL expire cached `conversations.replies` responses after 60 seconds
6. WHEN the configuration specifies `pins.list` with a TTL of 300 seconds THEN the proxy SHALL expire cached `pins.list` responses after 300 seconds
7. WHEN the configuration specifies `auth.test` with a TTL of 300 seconds THEN the proxy SHALL expire cached `auth.test` responses after 300 seconds

#### Additional Details
- **Priority**: High
- **Complexity**: Low
- **Dependencies**: Requirement 2 (GET Request Caching)
- **Assumptions**: TOML config file is readable at startup

### Requirement 4: POST Request Pass-Through and Cache Invalidation

**User Story:** As a Claude Code agent, I want POST requests to pass through to Slack and invalidate related cache entries, so that subsequent reads reflect the latest state.

#### Acceptance Criteria

1. WHEN the proxy receives a POST request THEN the proxy SHALL forward the request to Slack immediately without caching the request or the response
2. WHEN a `chat.postMessage` request succeeds THEN the proxy SHALL invalidate cached `conversations.history` entries for the affected channel AND IF the request included a `thread_ts` parameter THEN the proxy SHALL also invalidate cached `conversations.replies` entries for that thread
3. WHEN a `chat.update` request succeeds THEN the proxy SHALL invalidate cached `conversations.history` entries for the affected channel AND cached `conversations.replies` entries for the affected thread
4. WHEN a `chat.delete` request succeeds THEN the proxy SHALL invalidate cached `conversations.history` entries for the affected channel AND cached `conversations.replies` entries for the affected thread
5. WHEN a `reactions.add` request succeeds THEN the proxy SHALL invalidate cached `reactions.get` entries for the affected message
6. WHEN a POST request to Slack fails THEN the proxy SHALL return the Slack error response to the caller without invalidating any cache entries

#### Additional Details
- **Priority**: High
- **Complexity**: Medium
- **Dependencies**: Requirement 2 (GET Request Caching)
- **Assumptions**: POST response body contains channel/message identifiers needed for targeted invalidation

### Requirement 5: Stoolap On-Disk Cache Storage

**User Story:** As a system operator, I want the cache stored on disk using Stoolap, so that cache data persists across proxy restarts and does not consume excessive memory.

#### Acceptance Criteria

1. WHEN the proxy starts THEN the proxy SHALL open or create a Stoolap database at the configured file path
2. WHEN the proxy stores a cache entry THEN the proxy SHALL persist the entry to the Stoolap database on disk
3. WHEN the proxy starts and an existing cache database is present THEN the proxy SHALL load and serve unexpired entries from the existing database
4. WHEN the proxy shuts down THEN the proxy SHALL close the Stoolap database connection gracefully
5. IF the cache database file is inaccessible or corrupted THEN the proxy SHALL log an error and start with an empty cache

#### Additional Details
- **Priority**: High
- **Complexity**: Medium
- **Dependencies**: None
- **Assumptions**: Stoolap database file is located at `/var/lib/slack-proxy/cache.db` by default

### Requirement 6: TOML Configuration

**User Story:** As a system operator, I want all proxy settings in a single TOML configuration file, so that I can adjust server, cache, and logging behavior without code changes.

#### Acceptance Criteria

1. WHEN the proxy starts THEN the proxy SHALL read configuration from `/etc/slack-proxy/config.toml` by default
2. WHEN the configuration file specifies server settings (host, port) THEN the proxy SHALL bind to the specified host and port
3. WHEN the configuration file specifies cache settings (database path, default TTL, per-method TTLs) THEN the proxy SHALL apply those settings to cache behavior
4. WHEN the configuration file specifies logging settings (level, format) THEN the proxy SHALL configure logging accordingly
5. IF the configuration file is missing or unreadable THEN the proxy SHALL start with sensible default values and log a warning
6. IF the configuration file contains invalid TOML syntax THEN the proxy SHALL fail to start and report the parsing error

#### Additional Details
- **Priority**: High
- **Complexity**: Low
- **Dependencies**: None
- **Assumptions**: Configuration file follows TOML specification

### Requirement 7: Agent-Side Configuration

**User Story:** As a Claude Code agent operator, I want to enable the proxy by setting a single environment variable, so that adoption requires minimal configuration changes.

#### Acceptance Criteria

1. WHEN `SLACK_PROXY_URL` is set in `~/.claude/slack.conf` THEN the agent's Slack scripts SHALL route all Slack API requests through the proxy URL
2. IF `SLACK_PROXY_URL` is not set THEN the agent's Slack scripts SHALL send requests directly to `https://slack.com`
3. WHEN `SLACK_PROXY_URL` is set THEN the agent's Slack scripts SHALL construct request URLs by replacing the `https://slack.com` prefix with the proxy URL

#### Additional Details
- **Priority**: High
- **Complexity**: Low
- **Dependencies**: Requirement 1 (API Mirroring)
- **Assumptions**: Agents read `~/.claude/slack.conf` for Slack configuration

### Requirement 8: Auto-Fallback on Proxy Failure

**User Story:** As a Claude Code agent, I want automatic fallback to direct Slack calls when the proxy is unreachable, so that Slack functionality is never blocked by proxy outages.

#### Acceptance Criteria

1. WHEN `SLACK_PROXY_URL` is configured and the proxy is unreachable (connection refused, timeout, DNS failure) THEN the agent's Slack scripts SHALL retry the request directly against `https://slack.com`
2. WHEN the first fallback to direct Slack occurs THEN the agent's Slack scripts SHALL emit a one-time alert indicating the proxy is unreachable and persist the alert timestamp to a state file (`~/.claude/slack-proxy-fallback-alerted`)
3. IF the state file indicates an alert was emitted within the last 10 minutes THEN the agent's Slack scripts SHALL suppress further fallback alerts
4. IF the state file is older than 10 minutes and the proxy is still unreachable THEN the agent's Slack scripts SHALL emit a new alert and update the state file timestamp
5. WHEN the proxy returns an HTTP 5xx error THEN the agent's Slack scripts SHALL treat it as a proxy failure and fall back to direct Slack

#### Additional Details
- **Priority**: High
- **Complexity**: Medium
- **Dependencies**: Requirement 7 (Agent-Side Configuration)
- **Assumptions**: Fallback logic lives in the agent's scripts layer, not in the proxy itself

### Requirement 9: Cacheable Method Classification

**User Story:** As a system operator, I want a clear distinction between cacheable GET methods and pass-through POST methods, so that caching behavior is predictable and correct.

#### Acceptance Criteria

1. WHEN the proxy receives a request for `conversations.history`, `conversations.replies`, `pins.list`, `conversations.list`, `conversations.info`, `users.info`, `users.list`, `auth.test`, or `reactions.get` THEN the proxy SHALL treat the request as cacheable
2. WHEN the proxy receives a request for `chat.postMessage`, `chat.update`, `chat.delete`, `reactions.add`, or any other POST method THEN the proxy SHALL treat the request as pass-through
3. IF a method is classified as cacheable THEN the proxy SHALL only cache responses where the Slack API returns `"ok": true`
4. IF a cacheable method request returns a Slack error (`"ok": false`) THEN the proxy SHALL not cache the error response

#### Additional Details
- **Priority**: High
- **Complexity**: Low
- **Dependencies**: Requirement 2 (GET Request Caching), Requirement 4 (POST Request Pass-Through)
- **Assumptions**: The 27 supported methods are known and fixed for Phase 1

### Requirement 10: systemd Deployment

**User Story:** As a system operator, I want the proxy deployed as a systemd service, so that it starts on boot, restarts on failure, and integrates with standard Linux service management.

#### Acceptance Criteria

1. WHEN the systemd service is started THEN the proxy SHALL begin accepting HTTP requests on the configured host and port
2. WHEN the systemd service is stopped THEN the proxy SHALL perform a graceful shutdown, closing the database connection and finishing in-flight requests
3. IF the proxy process crashes THEN systemd SHALL restart the process automatically
4. WHEN the host system boots THEN systemd SHALL start the proxy service automatically
5. WHEN an operator runs `systemctl status slack-proxy` THEN systemd SHALL report the current service state and recent log output

#### Additional Details
- **Priority**: High
- **Complexity**: Low
- **Dependencies**: Requirement 6 (TOML Configuration)
- **Assumptions**: Target deployment is a Linux system with systemd

### Requirement 11: Dependency Management

**User Story:** As a developer, I want dependencies declared inline using PEP 723, so that the proxy can be run with `uv run` without a separate virtual environment setup step.

#### Acceptance Criteria

1. WHEN the proxy script is executed with `uv run` THEN uv SHALL resolve and install all declared dependencies automatically
2. WHEN the proxy declares dependencies THEN the proxy SHALL use PEP 723 inline script metadata format
3. WHEN a developer clones the repository THEN `uv run` SHALL be the only command needed to start the proxy with all dependencies satisfied

#### Additional Details
- **Priority**: Medium
- **Complexity**: Low
- **Dependencies**: None
- **Assumptions**: uv is installed on the target system

### Requirement 12: Logging

**User Story:** As a system operator, I want structured logging for all proxy operations, so that I can diagnose issues, monitor cache performance, and audit API usage.

#### Acceptance Criteria

1. WHEN the proxy receives a request THEN the proxy SHALL log the method name, source, and whether the response was served from cache or forwarded to Slack
2. WHEN a cache entry expires or is invalidated THEN the proxy SHALL log the invalidation event with the affected method and cache key
3. WHEN the proxy fails to reach Slack THEN the proxy SHALL log the error with the method name, HTTP status or connection error, and response time
4. WHEN the proxy starts THEN the proxy SHALL log the loaded configuration (host, port, cache path, TTL values) at INFO level
5. WHILE the proxy is running THEN the proxy SHALL log at the level specified in the TOML configuration

#### Additional Details
- **Priority**: Medium
- **Complexity**: Low
- **Dependencies**: Requirement 6 (TOML Configuration)
- **Assumptions**: Logs are written to stdout/stderr for journald capture

### Requirement 13: Error Handling

**User Story:** As a Claude Code agent, I want the proxy to handle upstream errors gracefully, so that agents receive meaningful error responses instead of opaque failures.

#### Acceptance Criteria

1. WHEN Slack returns an HTTP error (4xx or 5xx) THEN the proxy SHALL forward the error response to the caller with the original status code and body
2. WHEN the proxy cannot connect to Slack (timeout, DNS failure, connection refused) THEN the proxy SHALL return an HTTP 502 response with a JSON body containing an error description
3. WHEN the proxy encounters an internal error THEN the proxy SHALL return an HTTP 500 response with a JSON body containing a generic error message without exposing internal details
4. IF the Stoolap database is unreachable THEN the proxy SHALL continue operating in pass-through mode without caching and log the database error

#### Additional Details
- **Priority**: High
- **Complexity**: Medium
- **Dependencies**: Requirement 1 (API Mirroring), Requirement 5 (Stoolap On-Disk Cache Storage)
- **Assumptions**: Agents expect JSON error responses matching Slack API error format

### Requirement 14: Health Check

**User Story:** As a system operator, I want a health check endpoint, so that monitoring tools and load balancers can verify the proxy is operational.

#### Acceptance Criteria

1. WHEN a client sends a GET request to `/health` THEN the proxy SHALL return an HTTP 200 response with a JSON body indicating the service status, proxy version, and cache entry count
2. WHEN the health check is called THEN the proxy SHALL verify that the Stoolap database is accessible and include the database status in the response
3. IF the Stoolap database is inaccessible THEN the health check SHALL return an HTTP 503 response indicating degraded operation

#### Additional Details
- **Priority**: Medium
- **Complexity**: Low
- **Dependencies**: Requirement 5 (Stoolap On-Disk Cache Storage)
- **Assumptions**: Health check does not require authentication

## Non-Functional Requirements

### Performance Requirements
1. WHEN the proxy serves a response from cache THEN the proxy SHALL return the response within 50 milliseconds
2. WHEN four agents poll the same channel at one request per minute each THEN the proxy SHALL collapse those into approximately one upstream Slack API call per minute per channel

### Reliability Requirements
3. IF the Stoolap database becomes unavailable during operation THEN the proxy SHALL degrade to pass-through mode without interrupting service to agents
4. WHEN the proxy process restarts THEN the proxy SHALL resume serving cached data from the persisted Stoolap database within 5 seconds

### Testing Requirements
5. WHEN the test suite is executed THEN pytest SHALL report at least 80% line coverage across all source code in `src/proxy/`
6. WHEN end-to-end tests run THEN the tests SHALL achieve at least 80% coverage of the supported API methods using mocking and stubbing

## Constraints and Assumptions

### Technical Constraints
- Python 3.13 is the target runtime
- FastAPI with uvicorn is the web framework
- httpx is the async HTTP client for upstream Slack calls
- Stoolap (stoolap-python) is the cache database
- PEP 723 inline script metadata for dependency declaration
- uv is the dependency manager and script runner

### Deployment Constraints
- Target deployment host is Z490
- systemd is the service manager
- Configuration at `/etc/slack-proxy/config.toml`
- Cache database at `/var/lib/slack-proxy/cache.db`
- systemd unit at `/etc/systemd/system/slack-proxy.service`

### Assumptions
- Agents already read `SLACK_PROXY_URL` from `~/.claude/slack.conf`
- The 27 Slack API methods used by the plugin are known and stable
- Stoolap supports concurrent read access from multiple request handlers
- Agents tolerate up to 30 seconds of stale data for conversation history

## Glossary

| Term | Definition |
|------|------------|
| TTL | Time To Live -- the duration a cached response is considered valid before expiry |
| Stoolap | An on-disk database engine available via `stoolap-python` on PyPI, used for persistent cache storage |
| Pass-through | A request handling mode where the proxy forwards the request to Slack without caching |
| Write-through | A cache invalidation strategy where POST operations invalidate related cached GET responses |
| Cache key | A unique identifier for a cached entry, composed of the API method name and a hash of request parameters |
| PEP 723 | Python Enhancement Proposal for inline script metadata, allowing dependency declarations within the script file |
| TOML | Tom's Obvious Minimal Language -- a configuration file format used for proxy settings |
| Fallback | The automatic mechanism by which agent scripts route requests directly to Slack when the proxy is unreachable |
