#!/usr/bin/env python3
"""Update this agent's heartbeat in the pinned Agent Status Check thread,
then check all peers for staleness (2+ digits behind) and outdated versions.

Usage: slack-heartbeat [--maintenance [DURATION]] [CHANNEL_ID]
  CHANNEL_ID  — channel containing the pinned status thread (default: from slack.conf)
  --maintenance [DURATION] — signal maintenance mode in heartbeat status.
      Appends '| Maintenance <ISO time> [for DURATION]' to the status line.
      DURATION is optional: e.g. 2h, 30m, 1d, 90s.
      Peers in maintenance are skipped by the watchdog staleness check.

Config: ~/.claude/slack-heartbeat.conf (auto-created on first run)
  HEARTBEAT_THREAD_TS — ts of the pinned "Agent Status Check" parent message
  HEARTBEAT_MSG_TS    — ts of this agent's reply in that thread

The heartbeat digit is calculated from the current minute: (minute // 6) + 1
Format: :<digit_name>: v<scc-slack-version> [| Maintenance <ISO> [for <duration>]]
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

SLACK_BASE = os.environ.get("SLACK_PROXY_URL") or "https://slack.com"
SLACK_DIRECT = "https://slack.com"
FALLBACK_STATE_FILE = Path.home() / ".claude" / "slack-proxy-fallback-alerted"

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


def _build_request(base: str, method: str, token: str, params: dict | None = None, post_data: dict | None = None) -> urllib.request.Request:
    """Build a urllib Request for a Slack API call."""
    if post_data is not None:
        data = json.dumps(post_data).encode()
        return urllib.request.Request(
            f"{base}/api/{method}",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-type": "application/json; charset=utf-8",
            },
        )
    qs = "&".join(f"{k}={v}" for k, v in (params or {}).items())
    url = f"{base}/api/{method}?{qs}" if qs else f"{base}/api/{method}"
    return urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})


def _fallback_warn(error: Exception) -> None:
    """Emit a one-time fallback warning (10-min cooldown)."""
    now = int(time.time())
    last_alert = 0
    if FALLBACK_STATE_FILE.exists():
        try:
            last_alert = int(FALLBACK_STATE_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
    if now - last_alert >= 600:
        print(f"WARN: Proxy {SLACK_BASE} unreachable ({error}), falling back to direct Slack", file=sys.stderr)
        FALLBACK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        FALLBACK_STATE_FILE.write_text(str(now))


def slack_api(method: str, token: str, params: dict | None = None, post_data: dict | None = None) -> dict:
    """Call a Slack API method with proxy fallback. GET if params only, POST if post_data."""
    req = _build_request(SLACK_BASE, method, token, params, post_data)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        # Only retry if using proxy
        if SLACK_BASE == SLACK_DIRECT:
            raise
        _fallback_warn(e)
        req = _build_request(SLACK_DIRECT, method, token, params, post_data)
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


def calculate_heartbeat(maintenance: bool = False, duration: str | None = None) -> tuple[int, str, str]:
    """Calculate heartbeat digit, emoji, and full text.
    If maintenance is True, appends '| Maintenance <ISO> [for <duration>]'.
    """
    minute = datetime.now().minute
    digit = (minute // 6) + 1
    emoji = f":{DIGIT_NAMES[digit]}:"
    version = detect_version()
    text = f"{emoji} v{version}"
    if maintenance:
        iso_time = datetime.now().strftime("%Y-%m-%dT%H:%M")
        text += f" | Maintenance {iso_time}"
        if duration:
            text += f" for {duration}"
    return digit, emoji, text


def parse_maintenance(text: str) -> bool:
    """Check if a heartbeat status line indicates maintenance mode."""
    return "| Maintenance " in text


def parse_digit(text: str) -> int | None:
    """Parse a digit emoji from heartbeat text."""
    match = re.search(r":(" + "|".join(NAME_TO_DIGIT.keys()) + r"):", text)
    if match:
        return NAME_TO_DIGIT[match.group(1)]
    return None


def parse_version(text: str) -> tuple[int, int, int] | None:
    """Parse semver from heartbeat text (e.g. ':seven: v0.23.0' -> (0, 23, 0))."""
    match = re.search(r"v(\d+)\.(\d+)\.(\d+)", text)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def check_version_behind(own: tuple[int, int, int], peer: tuple[int, int, int]) -> str | None:
    """Check if peer version is behind own version.
    Returns description string if behind, None if ok.
    Flags: major/minor delta >= 1, patch delta >= 2.
    """
    if peer[0] < own[0]:
        return f"v{peer[0]}.{peer[1]}.{peer[2]} (major {own[0] - peer[0]} behind)"
    if peer[0] == own[0] and peer[1] < own[1]:
        return f"v{peer[0]}.{peer[1]}.{peer[2]} (minor {own[1] - peer[1]} behind)"
    if peer[0] == own[0] and peer[1] == own[1] and (own[2] - peer[2]) >= 2:
        return f"v{peer[0]}.{peer[1]}.{peer[2]} (patch {own[2] - peer[2]} behind)"
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


def parse_args(argv: list[str]) -> tuple[str | None, bool, str | None]:
    """Parse CLI arguments. Returns (channel_id, maintenance, duration)."""
    maintenance = False
    duration = None
    channel_id = None
    args = argv[1:]  # skip script name
    i = 0
    while i < len(args):
        if args[i] == "--maintenance":
            maintenance = True
            # Next arg is duration if it looks like one (digits + unit suffix)
            if i + 1 < len(args) and re.match(r"^\d+[smhd]$", args[i + 1]):
                duration = args[i + 1]
                i += 2
            else:
                i += 1
        else:
            channel_id = args[i]
            i += 1
    return channel_id, maintenance, duration


def main():
    token = load_token()
    user_id = load_identity(token)

    channel_id, maintenance, duration = parse_args(sys.argv)

    # Determine channel
    if not channel_id:
        slack_conf = load_conf(SLACK_CONF)
        default = slack_conf.get("DEFAULT_CHANNEL", "")
        if default:
            channel_id = resolve_channel(default, token)
    if not channel_id:
        sys.exit("ERROR: No channel specified and no DEFAULT_CHANNEL in slack.conf")

    digit, emoji, heartbeat_text = calculate_heartbeat(maintenance, duration)

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

    # Check each peer's digit and version
    own_version = parse_version(heartbeat_text)
    stale = []
    outdated = []
    for uid, msg in bot_msgs.items():
        peer_text = msg.get("text", "")
        display = resolve_user(uid)

        # Skip peers in maintenance mode
        if parse_maintenance(peer_text):
            continue

        # Digit staleness check
        their_digit = parse_digit(peer_text)
        if their_digit is not None:
            gap = (digit - their_digit + 10) % 10
            if gap >= 2:
                stale.append(f"{display} (digit {their_digit}, {gap} behind)")

        # Version check
        if own_version:
            peer_version = parse_version(peer_text)
            if peer_version:
                behind = check_version_behind(own_version, peer_version)
                if behind:
                    outdated.append(f"{display} on {behind}")

    # Dedup: check recent channel messages to avoid repeating alerts (AGT-48)
    recent_alerts: list[str] = []
    if stale or outdated:
        cooldown_seconds = 600  # 10 minutes
        now_ts = datetime.now().timestamp()
        oldest_ts = str(now_ts - cooldown_seconds)
        try:
            history = slack_api("conversations.history", token, params={
                "channel": channel_id, "limit": "30", "oldest": oldest_ts,
            })
            recent_alerts = [
                m.get("text", "") for m in history.get("messages", [])
                if m.get("bot_id") is not None
            ]
        except Exception:
            pass  # If dedup check fails, fall through and post anyway

    if stale:
        alert = "@here Heartbeat check: possibly stale agents: " + ", ".join(stale)
        # Skip if any recent bot message already contains a stale alert for the same agents
        already_reported = any("Heartbeat check: possibly stale" in a for a in recent_alerts)
        if not already_reported:
            subprocess.run(
                [str(SCRIPT_DIR / "slack-send"), channel_id, alert],
                capture_output=True,
            )

    if outdated:
        alert = "@here Version check: outdated agents: " + ", ".join(outdated)
        already_reported = any("Version check: outdated" in a for a in recent_alerts)
        if not already_reported:
            subprocess.run(
                [str(SCRIPT_DIR / "slack-send"), channel_id, alert],
                capture_output=True,
            )

    print(f"ok: {heartbeat_text}")


if __name__ == "__main__":
    main()
