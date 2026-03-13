#!/usr/bin/env python3
"""Update this agent's heartbeat in the pinned Agent Status Check thread,
then check all peers for staleness and alert if any are 2+ digits behind.

Usage: slack-heartbeat [CHANNEL_ID]
  CHANNEL_ID — channel containing the pinned status thread (default: from slack.conf)

Config: ~/.claude/slack-heartbeat.conf (auto-created on first run)
  HEARTBEAT_THREAD_TS — ts of the pinned "Agent Status Check" parent message
  HEARTBEAT_MSG_TS    — ts of this agent's reply in that thread

The heartbeat digit is calculated from the current minute: (minute // 6) + 1
Format: :<digit_name>: v<scc-slack-version>
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

DIGIT_NAMES = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "keycap_ten",
}
NAME_TO_DIGIT = {v: k for k, v in DIGIT_NAMES.items()}

SCRIPT_DIR = Path(__file__).resolve().parent
HOME = Path.home()
CONFIG_FILE = HOME / ".claude" / "slack-heartbeat.conf"
SLACK_CONF = HOME / ".claude" / "slack.conf"
IDENTITY_FILE = HOME / ".claude" / "slack-cache" / "identity"


def slack_api(method: str, token: str, params: dict | None = None, post_data: dict | None = None) -> dict:
    """Call a Slack API method. GET if params only, POST if post_data provided."""
    if post_data is not None:
        data = json.dumps(post_data).encode()
        req = urllib.request.Request(
            f"https://slack.com/api/{method}",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-type": "application/json; charset=utf-8",
            },
        )
    else:
        qs = "&".join(f"{k}={v}" for k, v in (params or {}).items())
        url = f"https://slack.com/api/{method}?{qs}" if qs else f"https://slack.com/api/{method}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def load_token() -> str:
    """Load Slack token from the same location as other scripts."""
    try:
        slack_bin = subprocess.run(["which", "slack"], capture_output=True, text=True, check=True).stdout.strip()
        token_path = Path(slack_bin).parent / ".slack"
        return token_path.read_text().strip()
    except Exception:
        sys.exit("ERROR: No Slack token found.")


def load_identity(token: str) -> str:
    """Load or create cached identity, return USER_ID."""
    if not IDENTITY_FILE.exists():
        subprocess.run([str(SCRIPT_DIR / "slack-identity")], capture_output=True)
    if not IDENTITY_FILE.exists():
        sys.exit("ERROR: Could not establish identity.")
    for line in IDENTITY_FILE.read_text().splitlines():
        if line.startswith("USER_ID="):
            return line.split("=", 1)[1].strip('"')
    sys.exit("ERROR: USER_ID not found in identity file.")


def load_conf(path: Path) -> dict:
    """Load a key=value config file into a dict."""
    conf = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip().strip('"')
    return conf


def save_conf(path: Path, data: dict):
    """Save a dict as key=value config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{k}="{v}"' for k, v in data.items()]
    path.write_text("\n".join(lines) + "\n")


def resolve_channel(channel: str, token: str) -> str:
    """Resolve channel name to ID if needed."""
    if re.match(r"^C[A-Z0-9]+$", channel):
        return channel
    try:
        result = subprocess.run(
            [str(SCRIPT_DIR / "slack-resolve"), "--channel", channel],
            capture_output=True, text=True,
        )
        resolved = result.stdout.strip().split("\n")[0].split("=")[0]
        if resolved and resolved != "UNKNOWN":
            return resolved
    except Exception:
        pass
    sys.exit(f"ERROR: Could not resolve channel '{channel}'")


def resolve_user(uid: str) -> str:
    """Resolve a user ID to display name."""
    try:
        result = subprocess.run(
            [str(SCRIPT_DIR / "slack-resolve"), uid],
            capture_output=True, text=True,
        )
        line = result.stdout.strip().split("\n")[0]
        if "=" in line:
            name = line.split("=", 1)[1]
            if name and name != "UNKNOWN":
                return name
    except Exception:
        pass
    return uid


def detect_version() -> str:
    """Detect scc-slack version from the script path."""
    match = re.search(r"(\d+\.\d+\.\d+)", str(SCRIPT_DIR))
    return match.group(1) if match else "unknown"


def calculate_heartbeat() -> tuple[int, str, str]:
    """Calculate heartbeat digit, emoji, and full text."""
    minute = datetime.now().minute
    digit = (minute // 6) + 1
    emoji = f":{DIGIT_NAMES[digit]}:"
    version = detect_version()
    return digit, emoji, f"{emoji} v{version}"


def parse_digit(text: str) -> int | None:
    """Parse a digit emoji from heartbeat text."""
    match = re.search(r":(" + "|".join(NAME_TO_DIGIT.keys()) + r"):", text)
    if match:
        return NAME_TO_DIGIT[match.group(1)]
    return None


def discover_thread(token: str, channel_id: str) -> str:
    """Find the pinned 'Agent Status Check' message ts."""
    pins = slack_api("pins.list", token, params={"channel": channel_id})
    for item in pins.get("items", []):
        msg = item.get("message", {})
        if "agent status check" in msg.get("text", "").lower():
            return msg["ts"]
    sys.exit("ERROR: No pinned 'Agent Status Check' message found in channel.")


def discover_own_message(token: str, channel_id: str, thread_ts: str, user_id: str) -> str | None:
    """Find this agent's most recent reply in the thread."""
    replies = slack_api("conversations.replies", token, params={
        "channel": channel_id, "ts": thread_ts, "limit": "50",
    })
    own_msgs = [
        m for m in replies.get("messages", [])
        if m.get("user") == user_id and m.get("ts") != thread_ts
    ]
    if own_msgs:
        return sorted(own_msgs, key=lambda m: m["ts"])[-1]["ts"]
    return None


def main():
    token = load_token()
    user_id = load_identity(token)

    # Determine channel
    channel_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not channel_id:
        slack_conf = load_conf(SLACK_CONF)
        default = slack_conf.get("DEFAULT_CHANNEL", "")
        if default:
            channel_id = resolve_channel(default, token)
    if not channel_id:
        sys.exit("ERROR: No channel specified and no DEFAULT_CHANNEL in slack.conf")

    digit, emoji, heartbeat_text = calculate_heartbeat()

    # Load cached config
    conf = load_conf(CONFIG_FILE)
    thread_ts = conf.get("HEARTBEAT_THREAD_TS", "")
    msg_ts = conf.get("HEARTBEAT_MSG_TS", "")

    # Bootstrap: discover pinned thread
    if not thread_ts:
        thread_ts = discover_thread(token, channel_id)

    # Bootstrap: discover own message in thread
    if not msg_ts:
        msg_ts = discover_own_message(token, channel_id, thread_ts, user_id)
        if not msg_ts:
            # Post a new reply
            result = slack_api("chat.postMessage", token, post_data={
                "channel": channel_id,
                "text": heartbeat_text,
                "thread_ts": thread_ts,
            })
            msg_ts = result.get("message", {}).get("ts") or result.get("ts")
            if not msg_ts:
                sys.exit("ERROR: Failed to post heartbeat message.")

    # Save config
    save_conf(CONFIG_FILE, {
        "HEARTBEAT_THREAD_TS": thread_ts,
        "HEARTBEAT_MSG_TS": msg_ts,
    })

    # Update own heartbeat message
    result = slack_api("chat.update", token, post_data={
        "channel": channel_id,
        "text": heartbeat_text,
        "ts": msg_ts,
    })
    if not result.get("ok"):
        # Clear cache so next run re-bootstraps
        CONFIG_FILE.unlink(missing_ok=True)
        sys.exit(f"ERROR: Failed to update heartbeat: {result.get('error')}")

    # --- Watchdog: check peers ---
    replies = slack_api("conversations.replies", token, params={
        "channel": channel_id, "ts": thread_ts, "limit": "50",
    })

    # Group by user, take latest message per bot user (excluding self and parent)
    bot_msgs: dict[str, dict] = {}
    for msg in replies.get("messages", []):
        if msg.get("ts") == thread_ts:
            continue
        if msg.get("user") == user_id:
            continue
        if msg.get("bot_id") is None:
            continue
        uid = msg["user"]
        if uid not in bot_msgs or msg["ts"] > bot_msgs[uid]["ts"]:
            bot_msgs[uid] = msg

    # Check each peer's digit
    stale = []
    for uid, msg in bot_msgs.items():
        their_digit = parse_digit(msg.get("text", ""))
        if their_digit is None:
            continue
        gap = (digit - their_digit + 10) % 10
        if gap >= 2:
            display = resolve_user(uid)
            stale.append(f"{display} (digit {their_digit}, {gap} behind)")

    if stale:
        alert = "@here Heartbeat check: possibly stale agents: " + ", ".join(stale)
        subprocess.run(
            [str(SCRIPT_DIR / "slack-send"), channel_id, alert],
            capture_output=True,
        )

    print(f"ok: {heartbeat_text}")


if __name__ == "__main__":
    main()
