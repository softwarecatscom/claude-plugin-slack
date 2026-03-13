"""Tests for proxy.config — config loading, merging, and error handling."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from proxy.config import (
    CacheConfig,
    LoggingConfig,
    ProxyConfig,
    ServerConfig,
    load_config,
)
from proxy.constants import DEFAULT_METHOD_TTLS, DEFAULT_TTL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_toml(tmp_path: Path, content: str) -> str:
    """Write a TOML string to a temp file and return its path."""
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# Valid config loads
# ---------------------------------------------------------------------------

class TestValidConfig:
    def test_full_config(self, tmp_path: Path):
        path = _write_toml(tmp_path, """\
            [server]
            host = "127.0.0.1"
            port = 9999

            [cache]
            db_path = "/tmp/test.db"
            default_ttl = 120

            [cache.method_ttls]
            "auth.test" = 600

            [logging]
            level = "debug"
            redact_tokens = false
        """)
        cfg = load_config(path)

        assert cfg.server.host == "127.0.0.1"
        assert cfg.server.port == 9999
        assert cfg.cache.db_path == "/tmp/test.db"
        assert cfg.cache.default_ttl == 120
        assert cfg.cache.method_ttls == {"auth.test": 600}
        assert cfg.logging.level == "debug"
        assert cfg.logging.redact_tokens is False

    def test_empty_file_returns_defaults(self, tmp_path: Path):
        path = _write_toml(tmp_path, "")
        cfg = load_config(path)

        assert cfg == ProxyConfig()

    def test_config_is_frozen(self, tmp_path: Path):
        path = _write_toml(tmp_path, "")
        cfg = load_config(path)

        with pytest.raises(AttributeError):
            cfg.server = ServerConfig(host="1.2.3.4")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Missing file returns defaults
# ---------------------------------------------------------------------------

class TestMissingFile:
    def test_explicit_missing_path(self):
        cfg = load_config("/no/such/file.toml")

        assert cfg == ProxyConfig()
        assert cfg.server.host == "0.0.0.0"
        assert cfg.server.port == 8321
        assert cfg.cache.default_ttl == DEFAULT_TTL
        assert cfg.cache.method_ttls == DEFAULT_METHOD_TTLS
        assert cfg.logging.level == "info"
        assert cfg.logging.redact_tokens is True

    def test_no_path_no_env_no_system(self, monkeypatch):
        monkeypatch.delenv("SLACK_PROXY_CONFIG", raising=False)
        cfg = load_config(None)

        assert cfg == ProxyConfig()


# ---------------------------------------------------------------------------
# Invalid TOML raises SystemExit
# ---------------------------------------------------------------------------

class TestInvalidToml:
    def test_malformed_toml_exits(self, tmp_path: Path):
        path = _write_toml(tmp_path, "this is not [valid toml = ")

        with pytest.raises(SystemExit):
            load_config(path)

    def test_unclosed_string_exits(self, tmp_path: Path):
        path = _write_toml(tmp_path, '[server]\nhost = "unclosed')

        with pytest.raises(SystemExit):
            load_config(path)


# ---------------------------------------------------------------------------
# Partial config merges with defaults
# ---------------------------------------------------------------------------

class TestPartialMerge:
    def test_only_server_section(self, tmp_path: Path):
        path = _write_toml(tmp_path, """\
            [server]
            port = 7777
        """)
        cfg = load_config(path)

        # Overridden
        assert cfg.server.port == 7777
        # Defaults preserved
        assert cfg.server.host == "0.0.0.0"
        assert cfg.cache == CacheConfig()
        assert cfg.logging == LoggingConfig()

    def test_only_cache_section(self, tmp_path: Path):
        path = _write_toml(tmp_path, """\
            [cache]
            default_ttl = 999
        """)
        cfg = load_config(path)

        assert cfg.cache.default_ttl == 999
        assert cfg.cache.db_path == "/var/lib/slack-proxy/cache.db"
        assert cfg.server == ServerConfig()

    def test_only_logging_section(self, tmp_path: Path):
        path = _write_toml(tmp_path, """\
            [logging]
            level = "warning"
        """)
        cfg = load_config(path)

        assert cfg.logging.level == "warning"
        assert cfg.logging.redact_tokens is True
        assert cfg.server == ServerConfig()
        assert cfg.cache == CacheConfig()


# ---------------------------------------------------------------------------
# Unknown keys ignored
# ---------------------------------------------------------------------------

class TestUnknownKeys:
    def test_unknown_top_level_key(self, tmp_path: Path):
        path = _write_toml(tmp_path, """\
            [server]
            host = "127.0.0.1"

            [experimental]
            feature_x = true
        """)
        cfg = load_config(path)

        assert cfg.server.host == "127.0.0.1"
        assert not hasattr(cfg, "experimental")

    def test_unknown_key_in_section(self, tmp_path: Path):
        path = _write_toml(tmp_path, """\
            [server]
            host = "10.0.0.1"
            secret_option = "ignored"
        """)
        cfg = load_config(path)

        assert cfg.server.host == "10.0.0.1"
        assert not hasattr(cfg.server, "secret_option")


# ---------------------------------------------------------------------------
# Environment variable config path
# ---------------------------------------------------------------------------

class TestEnvVarPath:
    def test_env_var_takes_precedence_over_system(self, tmp_path: Path, monkeypatch):
        path = _write_toml(tmp_path, """\
            [server]
            port = 1111
        """)
        monkeypatch.setenv("SLACK_PROXY_CONFIG", path)

        cfg = load_config(None)

        assert cfg.server.port == 1111

    def test_cli_arg_takes_precedence_over_env(self, tmp_path: Path, monkeypatch):
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        env_file = env_dir / "config.toml"
        env_file.write_text("[server]\nport = 2222", encoding="utf-8")
        monkeypatch.setenv("SLACK_PROXY_CONFIG", str(env_file))

        cli_file = tmp_path / "cli.toml"
        cli_file.write_text("[server]\nport = 3333", encoding="utf-8")

        cfg = load_config(str(cli_file))

        assert cfg.server.port == 3333
