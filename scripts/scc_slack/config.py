"""Load plugin configuration from slack.conf."""

from __future__ import annotations

from pathlib import Path

CONFIG_FILE = Path.home() / ".claude" / "slack.conf"


def _parse_key_value_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE file, stripping quotes and comments."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def load_config() -> dict[str, str]:
    """Load key=value config from slack.conf."""
    if not CONFIG_FILE.exists():
        msg = f"No config at {CONFIG_FILE}"
        raise RuntimeError(msg)
    return _parse_key_value_file(CONFIG_FILE)
