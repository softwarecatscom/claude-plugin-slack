"""Seen-set tracking — prevent duplicate message processing."""

from __future__ import annotations

import json
import time
from pathlib import Path

SEEN_FILE = Path.home() / ".claude" / "slack-seen.json"
SEEN_MAX_AGE = 86400  # 24 hours


def load_seen() -> dict[str, str | None]:
    """Load the seen map: {message_ts: thread_ts_or_null}."""
    if not SEEN_FILE.exists():
        return {}
    try:
        data = json.loads(SEEN_FILE.read_text())
        return data.get("seen", {})
    except (json.JSONDecodeError, ValueError):
        return {}


def save_seen(seen: dict[str, str | None]) -> None:
    """Save the seen map, pruning entries older than SEEN_MAX_AGE."""
    now = time.time()
    pruned = {ts: thread_ts for ts, thread_ts in seen.items() if now - float(ts) < SEEN_MAX_AGE}
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps({"seen": pruned}))
