#!/usr/bin/env python3
"""Track @mentions to other agents in threads and detect unresponsive agents.

Usage:
  slack-mention-tracker add <channel> <thread_ts> <user_id>
  slack-mention-tracker responded <channel> <thread_ts> <user_id>
  slack-mention-tracker tick
  slack-mention-tracker list

Subcommands:
  add         Record a pending @mention in a thread
  responded   Clear a pending @mention (the agent responded)
  tick        Increment cycle count for all pending mentions, output expired ones
  list        Show all currently tracked mentions

State file: ~/.claude/slack-mention-tracker.json
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

STATE_FILE = Path.home() / ".claude" / "slack-mention-tracker.json"
ESCALATION_THRESHOLD = 5  # poll cycles before escalating (~5 minutes at 1m intervals)

ARGS_COUNT_MIN = 2
ARGS_COUNT_ADD = 5
ARGS_COUNT_RESPONDED = 5


def load_state():
    if STATE_FILE.exists():
        with STATE_FILE.open() as f:
            return json.load(f)
    return []


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w") as f:
        json.dump(state, f, indent=2)


def add(channel, thread_ts, user_id):
    state = load_state()
    for entry in state:
        if entry["channel"] == channel and entry["thread_ts"] == thread_ts and entry["user_id"] == user_id:
            return  # already tracking
    state.append(
        {
            "channel": channel,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "cycles": 0,
            "alerted": False,
            "added_at": datetime.now(UTC).isoformat(),
        }
    )
    save_state(state)


def responded(channel, thread_ts, user_id):
    state = load_state()
    state = [
        e for e in state if not (e["channel"] == channel and e["thread_ts"] == thread_ts and e["user_id"] == user_id)
    ]
    save_state(state)


def tick():
    state = load_state()
    expired = []
    for entry in state:
        entry["cycles"] += 1
        if entry["cycles"] >= ESCALATION_THRESHOLD and not entry["alerted"]:
            entry["alerted"] = True
            expired.append(dict(entry))
    save_state(state)
    print(json.dumps(expired))


def list_all():
    state = load_state()
    print(json.dumps(state, indent=2))


def main():
    if len(sys.argv) < ARGS_COUNT_MIN:
        print(
            "Usage: slack-mention-tracker {add|responded|tick|list} [args...]",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) != ARGS_COUNT_ADD:
            print(
                "Usage: slack-mention-tracker add <channel> <thread_ts> <user_id>",
                file=sys.stderr,
            )
            sys.exit(1)
        add(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "responded":
        if len(sys.argv) != ARGS_COUNT_RESPONDED:
            print(
                "Usage: slack-mention-tracker responded <channel> <thread_ts> <user_id>",
                file=sys.stderr,
            )
            sys.exit(1)
        responded(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "tick":
        tick()
    elif cmd == "list":
        list_all()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
