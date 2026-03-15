"""Load and cache the bot's Slack identity."""

from __future__ import annotations

from pathlib import Path

IDENTITY_FILE = Path.home() / ".claude" / "slack-cache" / "identity"


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


def load_identity(
    api_get: callable | None = None,
) -> dict[str, str]:
    """Load identity from cache, or fetch via api_get and cache it.

    api_get: callable(method, params) -> dict  (e.g. SlackClient.get)
    If cache exists, api_get is not needed.
    """
    if IDENTITY_FILE.exists():
        return _parse_key_value_file(IDENTITY_FILE)

    if not api_get:
        msg = "No identity cached and no API client to fetch."
        raise RuntimeError(msg)

    auth = api_get("auth.test")
    if not auth.get("ok"):
        msg = f"auth.test failed: {auth.get('error')}"
        raise RuntimeError(msg)

    user_id = auth.get("user_id", "")
    username = auth.get("user", "")
    info = api_get("users.info", {"user": user_id})
    display_name = info.get("user", {}).get("profile", {}).get("display_name", "")
    real_name = info.get("user", {}).get("profile", {}).get("real_name", "")

    IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    IDENTITY_FILE.write_text(
        f'USER_ID="{user_id}"\nUSERNAME="{username}"\nDISPLAY_NAME="{display_name}"\nREAL_NAME="{real_name}"\n'
    )

    return {"USER_ID": user_id, "USERNAME": username, "DISPLAY_NAME": display_name, "REAL_NAME": real_name}
