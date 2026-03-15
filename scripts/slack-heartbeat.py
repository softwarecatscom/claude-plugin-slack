#!/usr/bin/env python3
"""Update this agent's heartbeat in the pinned Agent Status Check thread.

Then check all peers for staleness (2+ digits behind) and outdated versions.

Usage: slack-heartbeat [--maintenance [DURATION]] [CHANNEL_ID]
  CHANNEL_ID  -- channel containing the pinned status thread (default: from slack.conf)
  --maintenance [DURATION] -- signal maintenance mode in heartbeat status.
      Appends '| Maintenance <ISO time> [for DURATION]' to the status line.
      DURATION is optional: e.g. 2h, 30m, 1d, 90s.
      Peers in maintenance are skipped by the watchdog staleness check.

Config: ~/.claude/slack-heartbeat.conf (auto-created on first run)
  HEARTBEAT_THREAD_TS -- ts of the pinned "Agent Status Check" parent message
  HEARTBEAT_MSG_TS    -- ts of this agent's reply in that thread

The heartbeat digit is calculated from the current minute: (minute // 6) + 1
Format: :<digit_name>: v<scc-slack-version> [| Maintenance <ISO> [for <duration>]]
"""

import contextlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SLACK_BASE = os.environ.get("SLACK_PROXY_URL") or "https://slack.com"
SLACK_DIRECT = "https://slack.com"
FALLBACK_STATE_FILE = Path.home() / ".claude" / "slack-proxy-fallback-alerted"
FALLBACK_COOLDOWN_SECONDS = 600
STALENESS_THRESHOLD = 5
DEDUP_COOLDOWN_SECONDS = 600
DEDUP_HISTORY_LIMIT = "30"
THREAD_REPLY_LIMIT = "50"
PATCH_BEHIND_THRESHOLD = 2

DIGIT_NAMES = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "keycap_ten",
}
NAME_TO_DIGIT = {v: k for k, v in DIGIT_NAMES.items()}

SCRIPT_DIR = Path(__file__).resolve().parent
HOME = Path.home()
CONFIG_FILE = HOME / ".claude" / "slack-heartbeat.conf"
SLACK_CONF = HOME / ".claude" / "slack.conf"
IDENTITY_FILE = HOME / ".claude" / "slack-cache" / "identity"


def _build_request(
    base: str, method: str, token: str, params: dict | None = None, post_data: dict | None = None
) -> urllib.request.Request:
    """Build a urllib Request for a Slack API call."""
    if post_data is not None:
        data = json.dumps(post_data).encode()
        return urllib.request.Request(  # noqa: S310
            f"{base}/api/{method}",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-type": "application/json; charset=utf-8",
            },
        )
    qs = "&".join(f"{k}={v}" for k, v in (params or {}).items())
    url = f"{base}/api/{method}?{qs}" if qs else f"{base}/api/{method}"
    return urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})  # noqa: S310


def _fallback_warn(error: Exception) -> None:
    """Emit a one-time fallback warning (10-min cooldown)."""
    now = int(time.time())
    last_alert = 0
    if FALLBACK_STATE_FILE.exists():
        with contextlib.suppress(ValueError, OSError):
            last_alert = int(FALLBACK_STATE_FILE.read_text().strip())
    if now - last_alert >= FALLBACK_COOLDOWN_SECONDS:
        print(f"WARN: Proxy {SLACK_BASE} unreachable ({error}), falling back to direct Slack", file=sys.stderr)
        FALLBACK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        FALLBACK_STATE_FILE.write_text(str(now))


def slack_api(method: str, token: str, params: dict | None = None, post_data: dict | None = None) -> dict:
    """Call a Slack API method with proxy fallback.

    GET if params only, POST if post_data.
    """
    req = _build_request(SLACK_BASE, method, token, params, post_data)
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            return json.loads(resp.read())
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        # Only retry if using proxy
        if SLACK_BASE == SLACK_DIRECT:
            raise
        _fallback_warn(e)
        req = _build_request(SLACK_DIRECT, method, token, params, post_data)
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            return json.loads(resp.read())


def load_token() -> str:
    """Load Slack token from the same location as other scripts."""
    try:
        slack_bin = subprocess.run(
            ["which", "slack"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        token_path = Path(slack_bin).parent / ".slack"
        return token_path.read_text().strip()
    except Exception:
        sys.exit("ERROR: No Slack token found.")


def load_identity(_token: str) -> str:
    """Load or create cached identity, return USER_ID."""
    if not IDENTITY_FILE.exists():
        subprocess.run(  # noqa: S603
            [str(SCRIPT_DIR / "slack-identity")], capture_output=True, check=False
        )
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
        for raw_line in path.read_text().splitlines():
            stripped = raw_line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                k, v = stripped.split("=", 1)
                conf[k.strip()] = v.strip().strip('"')
    return conf


def save_conf(path: Path, data: dict) -> None:
    """Save a dict as key=value config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{k}="{v}"' for k, v in data.items()]
    path.write_text("\n".join(lines) + "\n")


def resolve_channel(channel: str, _token: str) -> str:
    """Resolve channel name to ID if needed."""
    if re.match(r"^C[A-Z0-9]+$", channel):
        return channel
    try:
        result = subprocess.run(  # noqa: S603
            [str(SCRIPT_DIR / "slack-resolve"), "--channel", channel],
            capture_output=True,
            text=True,
            check=False,
        )
        resolved = result.stdout.strip().split("\n")[0].split("=")[0]
        if resolved and resolved != "UNKNOWN":
            return resolved
    except Exception:  # noqa: S110
        pass
    sys.exit(f"ERROR: Could not resolve channel '{channel}'")


def resolve_user(uid: str) -> str:
    """Resolve a user ID to display name."""
    try:
        result = subprocess.run(  # noqa: S603
            [str(SCRIPT_DIR / "slack-resolve"), uid],
            capture_output=True,
            text=True,
            check=False,
        )
        line = result.stdout.strip().split("\n")[0]
        if "=" in line:
            name = line.split("=", 1)[1]
            if name and name != "UNKNOWN":
                return name
    except Exception:  # noqa: S110
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
    minute = datetime.now(tz=timezone.utc).minute
    digit = (minute // 6) + 1
    emoji = f":{DIGIT_NAMES[digit]}:"
    version = detect_version()
    text = f"{emoji} v{version}"
    if maintenance:
        iso_time = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M")
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
    if peer[0] == own[0] and peer[1] == own[1] and (own[2] - peer[2]) >= PATCH_BEHIND_THRESHOLD:
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
    replies = slack_api(
        "conversations.replies",
        token,
        params={
            "channel": channel_id,
            "ts": thread_ts,
            "limit": THREAD_REPLY_LIMIT,
        },
    )
    own_msgs = [m for m in replies.get("messages", []) if m.get("user") == user_id and m.get("ts") != thread_ts]
    if own_msgs:
        return sorted(own_msgs, key=lambda m: m["ts"])[-1]["ts"]
    return None


def parse_args(argv: list[str]) -> tuple[str | None, bool, str | None]:
    """Parse CLI arguments.

    Returns (channel_id, maintenance, duration).
    """
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


def _resolve_channel_id(channel_id: str | None, token: str) -> str:
    """Resolve channel ID from argument or slack.conf default."""
    if not channel_id:
        slack_conf = load_conf(SLACK_CONF)
        default = slack_conf.get("DEFAULT_CHANNEL", "")
        if default:
            channel_id = resolve_channel(default, token)
    if not channel_id:
        sys.exit("ERROR: No channel specified and no DEFAULT_CHANNEL in slack.conf")
    return channel_id


def _bootstrap_thread(token: str, channel_id: str, conf: dict) -> str:
    """Bootstrap: discover or load the pinned thread ts."""
    thread_ts = conf.get("HEARTBEAT_THREAD_TS", "")
    if not thread_ts:
        thread_ts = discover_thread(token, channel_id)
    return thread_ts


def _bootstrap_message(
    token: str, channel_id: str, thread_ts: str, user_id: str, conf: dict, heartbeat_text: str
) -> str:
    """Bootstrap: discover or create this agent's heartbeat message."""
    msg_ts = conf.get("HEARTBEAT_MSG_TS", "")
    if not msg_ts:
        msg_ts = discover_own_message(token, channel_id, thread_ts, user_id)
        if not msg_ts:
            result = slack_api(
                "chat.postMessage",
                token,
                post_data={
                    "channel": channel_id,
                    "text": heartbeat_text,
                    "thread_ts": thread_ts,
                },
            )
            msg_ts = result.get("message", {}).get("ts") or result.get("ts")
            if not msg_ts:
                sys.exit("ERROR: Failed to post heartbeat message.")
    return msg_ts


def _update_heartbeat(token: str, channel_id: str, heartbeat_text: str, msg_ts: str) -> None:
    """Update own heartbeat message in Slack."""
    result = slack_api(
        "chat.update",
        token,
        post_data={
            "channel": channel_id,
            "text": heartbeat_text,
            "ts": msg_ts,
        },
    )
    if not result.get("ok"):
        CONFIG_FILE.unlink(missing_ok=True)
        sys.exit(f"ERROR: Failed to update heartbeat: {result.get('error')}")


def _collect_peer_messages(token: str, channel_id: str, thread_ts: str, user_id: str) -> dict[str, dict]:
    """Fetch thread replies and group by user, keeping latest message per bot user."""
    replies = slack_api(
        "conversations.replies",
        token,
        params={
            "channel": channel_id,
            "ts": thread_ts,
            "limit": THREAD_REPLY_LIMIT,
        },
    )
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
    return bot_msgs


def _check_peers(bot_msgs: dict[str, dict], digit: int, heartbeat_text: str) -> tuple[list[str], list[str]]:
    """Check each peer's digit and version, return (stale, outdated) lists."""
    own_version = parse_version(heartbeat_text)
    stale: list[str] = []
    outdated: list[str] = []
    for uid, msg in bot_msgs.items():
        peer_text = msg.get("text", "")
        display = resolve_user(uid)

        if parse_maintenance(peer_text):
            continue

        their_digit = parse_digit(peer_text)
        if their_digit is not None:
            gap = (digit - their_digit + 10) % 10
            if gap >= STALENESS_THRESHOLD:
                stale.append(f"{display} (digit {their_digit}, {gap} behind)")

        if own_version:
            peer_version = parse_version(peer_text)
            if peer_version:
                behind = check_version_behind(own_version, peer_version)
                if behind:
                    outdated.append(f"{display} on {behind}")
    return stale, outdated


def _fetch_recent_alerts(token: str, channel_id: str) -> list[str]:
    """Fetch recent bot messages for dedup checking."""
    now_ts = datetime.now(tz=timezone.utc).timestamp()
    oldest_ts = str(now_ts - DEDUP_COOLDOWN_SECONDS)
    try:
        history = slack_api(
            "conversations.history",
            token,
            params={
                "channel": channel_id,
                "limit": DEDUP_HISTORY_LIMIT,
                "oldest": oldest_ts,
            },
        )
        return [m.get("text", "") for m in history.get("messages", []) if m.get("bot_id") is not None]
    except Exception:
        return []  # If dedup check fails, fall through and post anyway


def _send_alerts(stale: list[str], outdated: list[str], channel_id: str, recent_alerts: list[str]) -> None:
    """Send stale/outdated alerts if not already reported."""
    if stale:
        alert = "@here Heartbeat check: possibly stale agents: " + ", ".join(stale)
        already_reported = any("Heartbeat check: possibly stale" in a for a in recent_alerts)
        if not already_reported:
            subprocess.run(  # noqa: S603
                [str(SCRIPT_DIR / "slack-send"), channel_id, alert],
                capture_output=True,
                check=False,
            )

    if outdated:
        alert = "@here Version check: outdated agents: " + ", ".join(outdated)
        already_reported = any("Version check: outdated" in a for a in recent_alerts)
        if not already_reported:
            subprocess.run(  # noqa: S603
                [str(SCRIPT_DIR / "slack-send"), channel_id, alert],
                capture_output=True,
                check=False,
            )


def run_heartbeat(
    channel_id: str | None = None,
    maintenance: bool = False,
    duration: str | None = None,
) -> str:
    """Run heartbeat update and peer watchdog check.

    Callable from other modules (e.g. the poll daemon) without subprocess.
    Returns the heartbeat status text.
    """
    token = load_token()
    user_id = load_identity(token)

    resolved_channel = _resolve_channel_id(channel_id, token)

    _digit, _emoji, heartbeat_text = calculate_heartbeat(maintenance, duration)

    # Load cached config and bootstrap thread/message
    conf = load_conf(CONFIG_FILE)
    thread_ts = _bootstrap_thread(token, resolved_channel, conf)
    msg_ts = _bootstrap_message(token, resolved_channel, thread_ts, user_id, conf, heartbeat_text)

    # Save config
    save_conf(
        CONFIG_FILE,
        {
            "HEARTBEAT_THREAD_TS": thread_ts,
            "HEARTBEAT_MSG_TS": msg_ts,
        },
    )

    # Update own heartbeat message
    _update_heartbeat(token, resolved_channel, heartbeat_text, msg_ts)

    # --- Watchdog: check peers ---
    bot_msgs = _collect_peer_messages(token, resolved_channel, thread_ts, user_id)
    stale, outdated = _check_peers(bot_msgs, _digit, heartbeat_text)

    # Dedup and send alerts
    recent_alerts: list[str] = []
    if stale or outdated:
        recent_alerts = _fetch_recent_alerts(token, resolved_channel)
    _send_alerts(stale, outdated, resolved_channel, recent_alerts)

    return heartbeat_text


def main() -> None:
    """CLI entry point — parses args and calls run_heartbeat."""
    channel_id_arg, maintenance, duration = parse_args(sys.argv)
    result = run_heartbeat(channel_id_arg, maintenance, duration)
    print(f"ok: {result}")


if __name__ == "__main__":
    main()
