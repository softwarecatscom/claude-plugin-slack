#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "typer"]
# ///
"""Update this agent's heartbeat in the pinned Agent Status Check thread.

Then check all peers for staleness (2+ digits behind) and outdated versions.

Config: ~/.claude/slack-heartbeat.conf (auto-created on first run)
  HEARTBEAT_THREAD_TS -- ts of the pinned "Agent Status Check" parent message
  HEARTBEAT_MSG_TS    -- ts of this agent's reply in that thread

The heartbeat digit is calculated from the current minute: (minute // 6) + 1
Format: :<digit_name>: v<scc-slack-version> [| Maintenance <ISO> [for <duration>]]
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scc_slack import SlackClient, load_config, load_identity, load_token, resolve_channel, resolve_user
from scc_slack.config import _parse_key_value_file
from slack_cli_options import COMMON_OPTIONS

# --- Constants ---

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
CONFIG_FILE = Path.home() / ".claude" / "slack-heartbeat.conf"

# --- App ---

app = typer.Typer(
    name="slack-heartbeat",
    help="Update agent heartbeat in Slack status thread.",
    add_completion=False,
)

# --- Logging ---

_verbose = 0
_debug = False


def _log(msg: str, level: int = 1) -> None:
    """Print to stderr if verbosity >= level."""
    if _verbose >= level:
        typer.echo(msg, err=True)


def _debug_log(msg: str) -> None:
    """Print to stderr if --debug enabled."""
    if _debug:
        typer.echo(f"DEBUG: {msg}", err=True)


def _apply_globals(verbose: int, debug: bool) -> None:
    global _verbose, _debug  # noqa: PLW0603
    _verbose = verbose
    _debug = debug


# --- Config helpers (heartbeat-specific) ---


def load_conf(path: Path) -> dict:
    """Load heartbeat-specific key=value config file."""
    return _parse_key_value_file(path)


def save_conf(path: Path, data: dict) -> None:
    """Save a dict as key=value config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{k}="{v}"' for k, v in data.items()]
    path.write_text("\n".join(lines) + "\n")


# --- Heartbeat logic ---


def detect_version() -> str:
    """Detect scc-slack version from script path or plugin.json."""
    match = re.search(r"(\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?)", str(SCRIPT_DIR))
    if match:
        return match.group(1)
    # Fallback: read from plugin.json (when running from repo)
    plugin_json = SCRIPT_DIR.parent / ".claude-plugin" / "plugin.json"
    if plugin_json.exists():
        import json

        data = json.loads(plugin_json.read_text())
        if "version" in data:
            return data["version"]
    return "unknown"


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


def discover_thread(client: SlackClient, channel_id: str) -> str:
    """Find the pinned 'Agent Status Check' message ts."""
    pins = client.get("pins.list", params={"channel": channel_id})
    for item in pins.get("items", []):
        msg = item.get("message", {})
        if "agent status check" in msg.get("text", "").lower():
            return msg["ts"]
    sys.exit("ERROR: No pinned 'Agent Status Check' message found in channel.")


def discover_own_message(client: SlackClient, channel_id: str, thread_ts: str, user_id: str) -> str | None:
    """Find this agent's most recent reply in the thread."""
    replies = client.get(
        "conversations.replies",
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


def _resolve_channel_id(channel_id: str | None, client: SlackClient) -> str:
    """Resolve channel ID from argument or slack.conf default."""
    if not channel_id:
        slack_conf = load_config()
        default = slack_conf.get("DEFAULT_CHANNEL", "")
        if default:
            channel_id = resolve_channel(client.get, default)
    if not channel_id:
        sys.exit("ERROR: No channel specified and no DEFAULT_CHANNEL in slack.conf")
    return channel_id


def _bootstrap_thread(client: SlackClient, channel_id: str, conf: dict) -> str:
    """Bootstrap: discover or load the pinned thread ts."""
    thread_ts = conf.get("HEARTBEAT_THREAD_TS", "")
    if not thread_ts:
        thread_ts = discover_thread(client, channel_id)
    return thread_ts


def _bootstrap_message(
    client: SlackClient, channel_id: str, thread_ts: str, user_id: str, conf: dict, heartbeat_text: str
) -> str:
    """Bootstrap: discover or create this agent's heartbeat message."""
    msg_ts = conf.get("HEARTBEAT_MSG_TS", "")
    if not msg_ts:
        msg_ts = discover_own_message(client, channel_id, thread_ts, user_id)
        if not msg_ts:
            result = client.post(
                "chat.postMessage",
                {
                    "channel": channel_id,
                    "text": heartbeat_text,
                    "thread_ts": thread_ts,
                },
            )
            msg_ts = result.get("message", {}).get("ts") or result.get("ts")
            if not msg_ts:
                sys.exit("ERROR: Failed to post heartbeat message.")
    return msg_ts


def _update_heartbeat(client: SlackClient, channel_id: str, heartbeat_text: str, msg_ts: str) -> None:
    """Update own heartbeat message in Slack."""
    result = client.post(
        "chat.update",
        {
            "channel": channel_id,
            "text": heartbeat_text,
            "ts": msg_ts,
        },
    )
    if not result.get("ok"):
        CONFIG_FILE.unlink(missing_ok=True)
        sys.exit(f"ERROR: Failed to update heartbeat: {result.get('error')}")


def _collect_peer_messages(client: SlackClient, channel_id: str, thread_ts: str, user_id: str) -> dict[str, dict]:
    """Fetch thread replies and group by user, keeping latest message per bot user."""
    replies = client.get(
        "conversations.replies",
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


def _check_peers(
    client: SlackClient, bot_msgs: dict[str, dict], digit: int, heartbeat_text: str
) -> tuple[list[str], list[str]]:
    """Check each peer's digit and version, return (stale, outdated) lists."""
    own_version = parse_version(heartbeat_text)
    stale: list[str] = []
    outdated: list[str] = []
    for uid, msg in bot_msgs.items():
        peer_text = msg.get("text", "")
        display = resolve_user(client.get, uid)

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


def _fetch_recent_alerts(client: SlackClient, channel_id: str) -> list[str]:
    """Fetch recent bot messages for dedup checking."""
    now_ts = datetime.now(tz=timezone.utc).timestamp()
    oldest_ts = str(now_ts - DEDUP_COOLDOWN_SECONDS)
    try:
        history = client.get(
            "conversations.history",
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


# --- Core function (no typer deps) ---


def run_heartbeat(
    channel_id: str | None = None,
    maintenance: bool = False,
    duration: str | None = None,
) -> str:
    """Run heartbeat update and peer watchdog check.

    Callable from other modules (e.g. the poller) without subprocess.
    Returns the heartbeat status text.
    """
    import os

    config = load_config()
    token = load_token()
    proxy_url = os.environ.get("SLACK_PROXY_URL", config.get("SLACK_PROXY_URL"))
    client = SlackClient(token, proxy_url=proxy_url)
    try:
        identity = load_identity(client.get)
        user_id = identity["USER_ID"]

        resolved_channel = _resolve_channel_id(channel_id, client)

        _digit, _emoji, heartbeat_text = calculate_heartbeat(maintenance, duration)

        # Load cached config and bootstrap thread/message
        conf = load_conf(CONFIG_FILE)
        thread_ts = _bootstrap_thread(client, resolved_channel, conf)
        msg_ts = _bootstrap_message(client, resolved_channel, thread_ts, user_id, conf, heartbeat_text)

        # Save config
        save_conf(
            CONFIG_FILE,
            {
                "HEARTBEAT_THREAD_TS": thread_ts,
                "HEARTBEAT_MSG_TS": msg_ts,
            },
        )

        # Update own heartbeat message
        _update_heartbeat(client, resolved_channel, heartbeat_text, msg_ts)

        # --- Watchdog: check peers ---
        bot_msgs = _collect_peer_messages(client, resolved_channel, thread_ts, user_id)
        stale, outdated = _check_peers(client, bot_msgs, _digit, heartbeat_text)

        # Dedup and send alerts
        recent_alerts: list[str] = []
        if stale or outdated:
            recent_alerts = _fetch_recent_alerts(client, resolved_channel)
        _send_alerts(stale, outdated, resolved_channel, recent_alerts)
    finally:
        client.close()

    return heartbeat_text


# --- Typer CLI ---


@app.command()
def run(
    channel_id: Optional[str] = typer.Argument(None, help="Channel ID (default: from slack.conf)"),  # noqa: UP045
    maintenance: bool = typer.Option(False, "--maintenance", help="Signal maintenance mode"),
    duration: Optional[str] = typer.Option(None, "--duration", help="Maintenance duration (e.g. 2h, 30m, 1d)"),  # noqa: UP045
    verbose: int = COMMON_OPTIONS["verbose"],
    debug: bool = COMMON_OPTIONS["debug"],
    dry_run: bool = COMMON_OPTIONS["dry_run"],
) -> None:
    """Run heartbeat update and peer watchdog check."""
    _apply_globals(verbose, debug)
    _debug_log(f"channel_id={channel_id}, maintenance={maintenance}, duration={duration}")
    if dry_run:
        _digit, _emoji, text = calculate_heartbeat(maintenance, duration)
        typer.echo(f"dry-run: {text}")
        return
    result = run_heartbeat(channel_id, maintenance, duration)
    typer.echo(f"ok: {result}")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    channel_id: Optional[str] = typer.Argument(None, help="Channel ID (default: from slack.conf)"),  # noqa: UP045
    maintenance: bool = typer.Option(False, "--maintenance", help="Signal maintenance mode"),
    duration: Optional[str] = typer.Option(None, "--duration", help="Maintenance duration (e.g. 2h, 30m, 1d)"),  # noqa: UP045
    verbose: int = COMMON_OPTIONS["verbose"],
    debug: bool = COMMON_OPTIONS["debug"],
    dry_run: bool = COMMON_OPTIONS["dry_run"],
) -> None:
    """Update agent heartbeat in Slack status thread."""
    _apply_globals(verbose, debug)
    if ctx.invoked_subcommand is None:
        _debug_log(f"channel_id={channel_id}, maintenance={maintenance}, duration={duration}")
        if dry_run:
            _digit, _emoji, text = calculate_heartbeat(maintenance, duration)
            typer.echo(f"dry-run: {text}")
            return
        result = run_heartbeat(channel_id, maintenance, duration)
        typer.echo(f"ok: {result}")


if __name__ == "__main__":
    app()
