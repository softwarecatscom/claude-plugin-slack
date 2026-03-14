"""Configuration loading for the Slack caching proxy.

Config path resolution order:
  1. Explicit ``--config`` CLI argument
  2. ``SLACK_PROXY_CONFIG`` environment variable
  3. ``/etc/slack-proxy/config.toml`` (system default)

A missing file is non-fatal — the proxy starts with built-in defaults and
logs a warning.  An *invalid* TOML file is fatal (``sys.exit(1)``).
"""

from __future__ import annotations

import logging
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from proxy.constants import DEFAULT_METHOD_TTLS, DEFAULT_TTL

logger = logging.getLogger(__name__)

_SYSTEM_CONFIG_PATH = "/etc/slack-proxy/config.toml"


# ---------------------------------------------------------------------------
# Frozen dataclasses — immutable after construction
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8321


@dataclass(frozen=True)
class CacheConfig:
    db_path: str = "/var/lib/slack-proxy/cache.db"
    default_ttl: int = DEFAULT_TTL
    method_ttls: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_METHOD_TTLS))


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "info"
    redact_tokens: bool = True


@dataclass(frozen=True)
class ProxyConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _resolve_config_path(cli_path: str | None) -> str | None:
    """Return the config file path to use, or None if nothing is specified."""
    if cli_path is not None:
        return cli_path
    env_path = os.environ.get("SLACK_PROXY_CONFIG")
    if env_path is not None:
        return env_path
    if Path(_SYSTEM_CONFIG_PATH).exists():
        return _SYSTEM_CONFIG_PATH
    return None


def _merge_section(raw: dict, section: str, cls: type):
    """Instantiate *cls* from the TOML section, ignoring unknown keys."""
    section_data = raw.get(section, {})
    known_fields = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in section_data.items() if k in known_fields}
    return cls(**filtered)


def load_config(path: str | None = None) -> ProxyConfig:
    """Load and return a ``ProxyConfig``.

    Parameters
    ----------
    path:
        Explicit path passed via ``--config``.  Takes highest priority.
    """
    resolved = _resolve_config_path(path)

    if resolved is None:
        logger.warning(
            "No config file found; using built-in defaults "
            "(looked at SLACK_PROXY_CONFIG env var and %s)",
            _SYSTEM_CONFIG_PATH,
        )
        return ProxyConfig()

    config_path = Path(resolved)
    if not config_path.exists():
        logger.warning("Config file %s not found; using built-in defaults", resolved)
        return ProxyConfig()

    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        logger.error("Invalid TOML in %s: %s", resolved, exc)
        sys.exit(1)

    server = _merge_section(raw, "server", ServerConfig)
    cache = _merge_section(raw, "cache", CacheConfig)
    logging_cfg = _merge_section(raw, "logging", LoggingConfig)

    return ProxyConfig(server=server, cache=cache, logging=logging_cfg)
