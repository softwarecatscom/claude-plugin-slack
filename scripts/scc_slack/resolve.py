"""Resolve Slack channel names and user IDs using cache."""

from __future__ import annotations

import re
from pathlib import Path

CHANNEL_CACHE = Path.home() / ".claude" / "slack-cache" / "channels"
USER_CACHE = Path.home() / ".claude" / "slack-cache" / "users"


def resolve_channel(api_get: callable, name: str) -> str | None:
    """Resolve a channel name to an ID, using cache."""
    if re.match(r"^C[A-Z0-9]+$", name):
        return name
    if CHANNEL_CACHE.exists():
        for line in CHANNEL_CACHE.read_text().splitlines():
            if "=" in line:
                cached_id, _, cached_name = line.partition("=")
                if cached_name.lower() == name.lower():
                    return cached_id
    resp = api_get(
        "conversations.list",
        {"types": "public_channel,private_channel", "limit": "200"},
    )
    if not resp.get("ok"):
        return None
    CHANNEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    found = None
    for ch in resp.get("channels", []):
        lines.append(f"{ch['id']}={ch['name']}")
        if ch["name"].lower() == name.lower():
            found = ch["id"]
    CHANNEL_CACHE.write_text("\n".join(lines) + "\n")
    return found


def resolve_user(api_get: callable, user_id: str) -> str:
    """Resolve a user ID to display name, using cache."""
    if not user_id:
        return "unknown"
    if USER_CACHE.exists():
        for line in USER_CACHE.read_text().splitlines():
            if line.startswith(f"{user_id}="):
                return line.split("=", 1)[1]
    resp = api_get("users.info", {"user": user_id})
    if resp.get("ok"):
        profile = resp.get("user", {}).get("profile", {})
        name = profile.get("display_name") or profile.get("real_name") or resp.get("user", {}).get("name", "unknown")
        USER_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with USER_CACHE.open("a") as f:
            f.write(f"{user_id}={name}\n")
        return name
    return "unknown"
