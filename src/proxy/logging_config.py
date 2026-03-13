"""Logging configuration for the Slack caching proxy.

Configures stdlib logging for journald capture via stdout/stderr.
Provides structured log helpers for consistent, grep-friendly output.
"""

import logging
import re
import sys

LOGGER_NAME = "slack_proxy"

_BEARER_RE = re.compile(r"Bearer\s+xoxb-[A-Za-z0-9\-]+")
_REDACTED = "Bearer [REDACTED]"

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class _TokenRedactFilter(logging.Filter):
    """Strip Bearer tokens from log records before they hit the handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _BEARER_RE.sub(_REDACTED, record.msg)
        if record.args:
            sanitised = []
            for arg in record.args:
                if isinstance(arg, str):
                    sanitised.append(_BEARER_RE.sub(_REDACTED, arg))
                else:
                    sanitised.append(arg)
            record.args = tuple(sanitised)
        return True


def setup_logging(level: str = "info", redact_tokens: bool = True) -> logging.Logger:
    """Configure the ``slack_proxy`` logger for journald capture.

    Parameters
    ----------
    level:
        Log level name (case-insensitive).  Defaults to ``"info"``.
    redact_tokens:
        When *True* (the default), Bearer tokens in log messages are
        replaced with ``Bearer [REDACTED]``.

    Returns
    -------
    logging.Logger
        The configured ``slack_proxy`` logger.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers when called more than once (e.g. tests).
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)

        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.WARNING)
        stderr_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(stderr_handler)

    if redact_tokens:
        # Ensure only one instance of the filter is attached.
        if not any(isinstance(f, _TokenRedactFilter) for f in logger.filters):
            logger.addFilter(_TokenRedactFilter())

    return logger


# ---------------------------------------------------------------------------
# Structured log helpers
# ---------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def log_request(method: str, source_ip: str, cache_status: str) -> None:
    """Log an incoming API request (INFO)."""
    _get_logger().info(
        "request method=%s source=%s cache=%s", method, source_ip, cache_status
    )


def log_cache_hit(method: str, cache_key: str) -> None:
    """Log a cache hit (DEBUG)."""
    _get_logger().debug("cache_hit method=%s key=%s", method, cache_key)


def log_cache_miss(method: str, cache_key: str) -> None:
    """Log a cache miss (DEBUG)."""
    _get_logger().debug("cache_miss method=%s key=%s", method, cache_key)


def log_cache_store(method: str, cache_key: str, ttl: int) -> None:
    """Log a new entry being stored in the cache (DEBUG)."""
    _get_logger().debug(
        "cache_store method=%s key=%s ttl=%ds", method, cache_key, ttl
    )


def log_cache_invalidation(trigger_method: str, entries_removed: int) -> None:
    """Log cache entries being invalidated (INFO)."""
    _get_logger().info(
        "cache_invalidation trigger=%s removed=%d", trigger_method, entries_removed
    )


def log_upstream_error(method: str, error: str, elapsed: float) -> None:
    """Log a Slack upstream error (WARNING for client errors, ERROR otherwise).

    Uses WARNING for HTTP 4xx-class issues and ERROR for everything else.
    """
    logger = _get_logger()
    msg = "upstream_error method=%s error=%s elapsed=%.3fs"
    if error.startswith("4"):
        logger.warning(msg, method, error, elapsed)
    else:
        logger.error(msg, method, error, elapsed)


def log_config_loaded(
    host: str, port: int, db_path: str, ttl_count: int
) -> None:
    """Log proxy configuration at startup (INFO)."""
    _get_logger().info(
        "config_loaded host=%s port=%d db=%s ttl_rules=%d",
        host,
        port,
        db_path,
        ttl_count,
    )


def log_startup() -> None:
    """Log proxy startup (INFO)."""
    _get_logger().info("proxy_startup")


def log_shutdown() -> None:
    """Log proxy shutdown (INFO)."""
    _get_logger().info("proxy_shutdown")
