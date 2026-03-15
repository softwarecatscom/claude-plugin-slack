"""Message filtering — classify and filter Slack messages for actionable ones."""

from __future__ import annotations

import re

BROADCAST_RE = re.compile(
    r"<!here>|<!channel>|<!everyone>"
    r"|(^|\s)@here(\s|$)"
    r"|(^|\s)@channel(\s|$)"
    r"|(^|\s)@everyone(\s|$)",
)


def classify_message(text: str, user_id: str, identity: dict, thread_participant: bool) -> str | None:
    """Determine match type for a message. Returns None if not actionable."""
    if f"<@{user_id}>" in text:
        return "direct"
    if BROADCAST_RE.search(text):
        return "broadcast"
    text_lower = text.lower()
    username = identity.get("USERNAME", "").lower()
    display_name = identity.get("DISPLAY_NAME", "").lower()
    real_name = identity.get("REAL_NAME", "").lower()
    if (username and f"@{username}" in text_lower) or (display_name and f"@{display_name}" in text_lower):
        return "name"
    if real_name and real_name != display_name and f"@{real_name}" in text_lower:
        return "name"
    if thread_participant:
        return "thread_participant"
    return None


def filter_messages(
    messages: list[dict],
    identity: dict,
    resolve_user_fn: callable | None = None,
    *,
    thread_participant: bool = False,
) -> list[dict]:
    """Filter messages for actionable ones. Resolves sender names if resolve_user_fn provided."""
    user_id = identity.get("USER_ID", "")
    results = []
    for msg in messages:
        if msg.get("user") == user_id:
            continue
        subtype = msg.get("subtype")
        if subtype and subtype not in ("bot_message", "thread_broadcast"):
            continue
        match_type = classify_message(msg.get("text", ""), user_id, identity, thread_participant)
        if match_type:
            sender_id = msg.get("user", "")
            results.append(
                {
                    "ts": msg.get("ts"),
                    "user": sender_id,
                    "sender": resolve_user_fn(sender_id) if resolve_user_fn else sender_id,
                    "text": msg.get("text", ""),
                    "match_type": match_type,
                    "thread_ts": msg.get("thread_ts"),
                }
            )
    results.reverse()
    return results
