#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "typer"]
# ///
"""Long-poll daemon for Slack monitoring.

Runs continuously, polling Slack every POLL_INTERVAL seconds.
Only produces output (and exits) when actionable messages are found.
Designed to be launched via Bash(run_in_background: true).

Output: JSON array of enriched actionable messages with sender names resolved
and thread context included.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slack_cli_options import COMMON_OPTIONS

# --- Paths ---

CONFIG_FILE = Path.home() / ".claude" / "slack.conf"
IDENTITY_FILE = Path.home() / ".claude" / "slack-cache" / "identity"
CURSOR_FILE = Path.home() / ".claude" / "slack-cursors.conf"
THREAD_CURSOR_FILE = Path.home() / ".claude" / "slack-thread-cursors.conf"
CHANNEL_CACHE = Path.home() / ".claude" / "slack-cache" / "channels"
USER_CACHE = Path.home() / ".claude" / "slack-cache" / "users"
MENTION_TRACKER_STATE = Path.home() / ".claude" / "slack-mention-tracker.json"
PID_FILE = Path.home() / ".claude" / "slack-poll.pid"
FALLBACK_STATE_FILE = Path.home() / ".claude" / "slack-proxy-fallback-alerted"

# --- Constants ---

DEFAULT_POLL_INTERVAL = 60
HISTORY_LIMIT = 20
HISTORY_LIMIT_NO_CURSOR = 10
THREAD_HISTORY_LIMIT = 50
MAX_THREADS = 5
FALLBACK_COOLDOWN = 600  # 10 minutes

BROADCAST_RE = re.compile(
    r"<!here>|<!channel>|<!everyone>"
    r"|(^|\s)@here(\s|$)"
    r"|(^|\s)@channel(\s|$)"
    r"|(^|\s)@everyone(\s|$)",
)

# --- Daemon Options ---

POLL_OPTIONS = {
    "interval": typer.Option(None, "--interval", "-i", help="Poll interval in seconds"),
}

# --- App ---

app = typer.Typer(
    name="slack-poll",
    help="Long-poll daemon for Slack monitoring.",
    add_completion=False,
)

# --- Shutdown ---

_shutdown = False


def _handle_signal(_signum: int, _frame: object) -> None:
    global _shutdown  # noqa: PLW0603
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

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


# --- Config ---


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
        typer.echo(f"ERROR: No config at {CONFIG_FILE}", err=True)
        raise typer.Exit(code=1)
    _debug_log(f"Loading config from {CONFIG_FILE}")
    return _parse_key_value_file(CONFIG_FILE)


def load_identity() -> dict[str, str]:
    """Load identity from ~/.claude/slack-cache/identity."""
    if not IDENTITY_FILE.exists():
        scripts_dir = _find_scripts_dir()
        if scripts_dir:
            subprocess.run(  # noqa: S603
                [str(scripts_dir / "slack-identity")],
                capture_output=True,
                timeout=30,
                check=False,
            )
    if not IDENTITY_FILE.exists():
        typer.echo("ERROR: No identity cached.", err=True)
        raise typer.Exit(code=1)
    identity = _parse_key_value_file(IDENTITY_FILE)
    _debug_log(f"Identity: {identity.get('REAL_NAME', '?')} ({identity.get('USER_ID', '?')})")
    return identity


def load_token() -> str:
    """Load Slack token from slack-cli's .slack file."""
    slack_bin = shutil.which("slack")
    if not slack_bin:
        typer.echo("ERROR: slack-cli not found in PATH", err=True)
        raise typer.Exit(code=1)
    token_file = Path(slack_bin).parent / ".slack"
    if not token_file.exists():
        typer.echo("ERROR: No Slack token found.", err=True)
        raise typer.Exit(code=1)
    return token_file.read_text().strip()


def _find_scripts_dir() -> Path | None:
    """Find the scripts directory (this script's parent)."""
    scripts_dir = Path(__file__).resolve().parent
    if (scripts_dir / "slack-identity").exists():
        return scripts_dir
    return None


# --- HTTP client with proxy fallback ---


class SlackClient:
    """HTTP client for Slack API with proxy fallback."""

    def __init__(self, token: str, proxy_url: str | None = None) -> None:
        self.base_url = proxy_url or "https://slack.com"
        self.direct_url = "https://slack.com"
        self.using_proxy = self.base_url != self.direct_url
        self._client = httpx.Client(
            timeout=30.0,
            headers={"Authorization": f"Bearer {token}"},
        )
        self._last_fallback_warn = 0.0

    def get(self, method: str, params: dict | None = None) -> dict:
        """Call a Slack API method with proxy fallback."""
        _debug_log(f"API: {method} {params or ''}")
        url = f"{self.base_url}/api/{method}"
        try:
            resp = self._client.get(url, params=params)
            return resp.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            if not self.using_proxy:
                return {"ok": False, "error": str(exc)}
            self._fallback_warn(str(exc))
            try:
                url = f"{self.direct_url}/api/{method}"
                resp = self._client.get(url, params=params)
                return resp.json()
            except Exception as exc2:
                return {"ok": False, "error": str(exc2)}

    def _fallback_warn(self, reason: str) -> None:
        """Emit a proxy fallback warning with 10-minute cooldown."""
        now = time.time()
        if now - self._last_fallback_warn < FALLBACK_COOLDOWN:
            return
        self._last_fallback_warn = now
        _log(f"WARN: Proxy {self.base_url} unreachable ({reason}), falling back to direct Slack", level=0)
        FALLBACK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        FALLBACK_STATE_FILE.write_text(str(int(now)))

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


# --- Resolution helpers ---


def resolve_channel(client: SlackClient, name: str) -> str | None:
    """Resolve a channel name to an ID, using cache."""
    if re.match(r"^C[A-Z0-9]+$", name):
        return name
    if CHANNEL_CACHE.exists():
        for line in CHANNEL_CACHE.read_text().splitlines():
            if "=" in line:
                cached_id, _, cached_name = line.partition("=")
                if cached_name.lower() == name.lower():
                    _debug_log(f"Channel cache hit: {name} → {cached_id}")
                    return cached_id
    resp = client.get(
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


def resolve_user(client: SlackClient, user_id: str) -> str:
    """Resolve a user ID to display name, using cache."""
    if not user_id:
        return "unknown"
    if USER_CACHE.exists():
        for line in USER_CACHE.read_text().splitlines():
            if line.startswith(f"{user_id}="):
                return line.split("=", 1)[1]
    resp = client.get("users.info", {"user": user_id})
    if resp.get("ok"):
        profile = resp.get("user", {}).get("profile", {})
        name = profile.get("display_name") or profile.get("real_name") or resp.get("user", {}).get("name", "unknown")
        USER_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with USER_CACHE.open("a") as f:
            f.write(f"{user_id}={name}\n")
        return name
    return "unknown"


# --- Mention tracker (inline) ---


def mention_tracker_responded(channel: str, thread_ts: str, user_id: str) -> None:
    """Clear a tracked @mention (agent responded). No-op if not tracked."""
    if not MENTION_TRACKER_STATE.exists():
        return
    try:
        state = json.loads(MENTION_TRACKER_STATE.read_text())
    except (json.JSONDecodeError, ValueError):
        return
    new_state = [
        e
        for e in state
        if not (e.get("channel") == channel and e.get("thread_ts") == thread_ts and e.get("user_id") == user_id)
    ]
    if len(new_state) != len(state):
        MENTION_TRACKER_STATE.write_text(json.dumps(new_state, indent=2))


# --- Cursor management ---


def read_cursor(cursor_file: Path, channel_id: str) -> str:
    """Read cursor for a channel."""
    if not cursor_file.exists():
        return ""
    for line in cursor_file.read_text().splitlines():
        if line.startswith(f"{channel_id}="):
            return line.split("=", 1)[1]
    return ""


def write_cursor(cursor_file: Path, channel_id: str, ts: str) -> None:
    """Write cursor for a channel (atomic)."""
    cursor_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if cursor_file.exists():
        lines = [line for line in cursor_file.read_text().splitlines() if not line.startswith(f"{channel_id}=")]
    lines.append(f"{channel_id}={ts}")
    fd, tmp = tempfile.mkstemp(prefix="slack-cursors.", dir="/tmp")
    os.close(fd)
    Path(tmp).write_text("\n".join(lines) + "\n")
    Path(tmp).replace(cursor_file)


# --- Message filtering ---


def _classify_message(text: str, user_id: str, identity: dict, thread_participant: bool) -> str | None:
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
    client: SlackClient | None = None,
    *,
    thread_participant: bool = False,
) -> list[dict]:
    """Filter messages for actionable ones. Resolves sender names if client provided."""
    user_id = identity.get("USER_ID", "")
    results = []
    for msg in messages:
        if msg.get("user") == user_id:
            continue
        subtype = msg.get("subtype")
        if subtype and subtype not in ("bot_message", "thread_broadcast"):
            continue
        match_type = _classify_message(msg.get("text", ""), user_id, identity, thread_participant)
        if match_type:
            sender_id = msg.get("user", "")
            results.append(
                {
                    "ts": msg.get("ts"),
                    "user": sender_id,
                    "sender": resolve_user(client, sender_id) if client else sender_id,
                    "text": msg.get("text", ""),
                    "match_type": match_type,
                    "thread_ts": msg.get("thread_ts"),
                }
            )
    results.reverse()
    return results


# --- Thread helpers ---


def fetch_thread_context(client: SlackClient, channel_id: str, thread_ts: str) -> list[dict]:
    """Fetch full thread as simplified context for the agent."""
    resp = client.get(
        "conversations.replies",
        {"channel": channel_id, "ts": thread_ts, "limit": "50"},
    )
    if not resp.get("ok"):
        return []
    return [
        {
            "sender": resolve_user(client, msg.get("user", "")),
            "text": msg.get("text", ""),
            "ts": msg.get("ts", ""),
        }
        for msg in resp.get("messages", [])
    ]


def _find_active_threads(
    thread_messages: list[dict], user_id: str, effective_cursor: str, *, participating: bool
) -> list[dict]:
    """Find threads with new activity."""
    parents = []
    for msg in thread_messages:
        if msg.get("reply_count", 0) <= 0:
            continue
        reply_users = msg.get("reply_users", [])
        is_participant = msg.get("user") == user_id or user_id in reply_users
        if participating and not is_participant:
            continue
        if not participating and is_participant:
            continue
        latest_reply = msg.get("latest_reply", "")
        if effective_cursor and latest_reply <= effective_cursor:
            continue
        parents.append({"ts": msg["ts"], "latest_reply": latest_reply})
    parents.sort(key=lambda x: x["latest_reply"], reverse=True)
    return parents[:MAX_THREADS]


def _scan_threads(
    client: SlackClient,
    channel_id: str,
    channel_name: str,
    parents: list[dict],
    identity: dict,
    effective_cursor: str,
    *,
    participating: bool,
) -> list[dict]:
    """Scan threads for actionable messages and enrich with context."""
    results: list[dict] = []
    for parent in parents:
        parent_ts = parent["ts"]
        replies_resp = client.get(
            "conversations.replies",
            {"channel": channel_id, "ts": parent_ts, "oldest": effective_cursor or "0"},
        )
        reply_msgs = replies_resp.get("messages", []) if replies_resp.get("ok") else []
        # Skip thread parent (already processed as channel message) and thread_broadcast
        reply_msgs = [m for m in reply_msgs if m.get("subtype") != "thread_broadcast" and m.get("ts") != parent_ts]
        matches = filter_messages(
            reply_msgs,
            identity,
            client,
            thread_participant=participating,
        )
        if not participating and not matches:
            continue
        if matches:
            thread_ctx = fetch_thread_context(client, channel_id, parent_ts)
            for msg in matches:
                msg["channel"] = channel_name
                msg["channel_id"] = channel_id
                msg["thread_context"] = thread_ctx
                if participating:
                    mention_tracker_responded(channel_id, parent_ts, msg.get("user", ""))
            results.extend(matches)
    return results


# --- Poll cycle ---


def _poll_channel(client: SlackClient, channel_name: str, identity: dict) -> list[dict]:
    """Poll a single channel for actionable messages."""
    channel_id = resolve_channel(client, channel_name)
    if not channel_id:
        _log(f"ERROR: Could not resolve channel '{channel_name}'", level=0)
        return []

    _debug_log(f"Polling #{channel_name} ({channel_id})")
    user_id = identity.get("USER_ID", "")
    old_cursor = read_cursor(CURSOR_FILE, channel_id)
    _debug_log(f"Channel cursor: {old_cursor or '(none)'}")

    # Fetch channel history
    params: dict[str, str] = {
        "channel": channel_id,
        "limit": str(HISTORY_LIMIT if old_cursor else HISTORY_LIMIT_NO_CURSOR),
    }
    if old_cursor:
        params["oldest"] = old_cursor

    history = client.get("conversations.history", params)
    messages = history.get("messages", []) if history.get("ok") else []
    _debug_log(f"Channel messages: {len(messages)}")

    # Filter channel messages
    actionable: list[dict] = []
    channel_matches = filter_messages(messages, identity, client)
    for msg in channel_matches:
        msg["channel"] = channel_name
        msg["channel_id"] = channel_id
    actionable.extend(channel_matches)
    _debug_log(f"Channel matches: {len(channel_matches)}")

    # Thread scanning
    thread_history = client.get(
        "conversations.history",
        {"channel": channel_id, "limit": str(THREAD_HISTORY_LIMIT)},
    )
    thread_messages = thread_history.get("messages", []) if thread_history.get("ok") else []
    old_thread_cursor = read_cursor(THREAD_CURSOR_FILE, channel_id)
    effective_cursor = old_thread_cursor or old_cursor

    # Participating threads
    participating = _find_active_threads(thread_messages, user_id, effective_cursor, participating=True)
    _debug_log(f"Participating threads with activity: {len(participating)}")
    actionable.extend(
        _scan_threads(
            client,
            channel_id,
            channel_name,
            participating,
            identity,
            effective_cursor,
            participating=True,
        )
    )

    # Non-participating threads with @mentions
    non_participating = _find_active_threads(thread_messages, user_id, effective_cursor, participating=False)
    _debug_log(f"Non-participating threads with activity: {len(non_participating)}")
    actionable.extend(
        _scan_threads(
            client,
            channel_id,
            channel_name,
            non_participating,
            identity,
            effective_cursor,
            participating=False,
        )
    )

    # Advance cursors
    if messages:
        newest_ts = messages[0].get("ts", "")
        if newest_ts:
            write_cursor(CURSOR_FILE, channel_id, newest_ts)

    # Advance thread cursor across ALL scanned threads (participating + non-participating)
    newest_thread_ts = ""
    for parent in [*participating, *non_participating]:
        for msg in thread_messages:
            if msg["ts"] == parent["ts"]:
                newest_thread_ts = max(newest_thread_ts, msg.get("latest_reply", ""))
                break
    if newest_thread_ts:
        write_cursor(THREAD_CURSOR_FILE, channel_id, newest_thread_ts)

    return actionable


def _run_subprocess(cmd: list[str], timeout: int = 30) -> None:
    """Run a subprocess, suppressing errors."""
    with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, OSError):
        subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)  # noqa: S603


def poll_cycle(
    client: SlackClient,
    channels: list[str],
    identity: dict,
    scripts_dir: Path | None,
    *,
    dry_run: bool = False,
) -> str:
    """Run one poll cycle. Returns enriched JSON if actionable, empty if quiet."""
    all_actionable: list[dict] = []
    for channel in channels:
        stripped = channel.strip()
        if stripped:
            all_actionable.extend(_poll_channel(client, stripped, identity))

    if scripts_dir and not dry_run:
        _run_subprocess([str(scripts_dir / "slack-heartbeat")], timeout=30)
        _run_subprocess([str(scripts_dir / "slack-mention-tracker"), "tick"], timeout=10)
    elif dry_run:
        _log("DRY RUN: skipping heartbeat and mention tracker", level=0)

    if all_actionable:
        _log(f"Found {len(all_actionable)} actionable message(s)", level=1)
        return json.dumps(all_actionable, indent=2)
    _debug_log("No actionable messages")
    return ""


# --- PID management ---


def read_pid() -> int | None:
    """Read PID from PID file, return None if not running."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return None


def write_pid() -> None:
    """Write current PID and register cleanup."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: PID_FILE.unlink(missing_ok=True))


# --- Commands ---


@app.command()
def stop() -> None:
    """Stop a running daemon."""
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            typer.echo(f"Stopped daemon (PID {pid})")
        except ProcessLookupError:
            typer.echo("Daemon not running (stale PID file)")
        PID_FILE.unlink(missing_ok=True)
    else:
        typer.echo("Daemon not running")


@app.command()
def status() -> None:
    """Check if daemon is running."""
    pid = read_pid()
    if pid:
        typer.echo(f"running (PID {pid})")
    else:
        typer.echo("stopped")


def _apply_globals(verbose: int, debug: bool) -> None:
    """Set global verbosity and debug flags."""
    global _verbose, _debug  # noqa: PLW0603
    _verbose = verbose
    _debug = debug


@app.command()
def once(
    verbose: int = COMMON_OPTIONS["verbose"],
    debug: bool = COMMON_OPTIONS["debug"],
    dry_run: bool = COMMON_OPTIONS["dry_run"],
) -> None:
    """Run a single poll cycle (for testing)."""
    _apply_globals(verbose, debug)
    _run_daemon(once=True, dry_run=dry_run)


@app.command()
def run(
    verbose: int = COMMON_OPTIONS["verbose"],
    debug: bool = COMMON_OPTIONS["debug"],
    dry_run: bool = COMMON_OPTIONS["dry_run"],
    interval: Optional[int] = POLL_OPTIONS["interval"],  # noqa: UP045
) -> None:
    """Run daemon until actionable messages found (default command)."""
    _apply_globals(verbose, debug)
    _run_daemon(once=False, dry_run=dry_run, interval_override=interval)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    verbose: int = COMMON_OPTIONS["verbose"],
    debug: bool = COMMON_OPTIONS["debug"],
    dry_run: bool = COMMON_OPTIONS["dry_run"],
    interval: Optional[int] = POLL_OPTIONS["interval"],  # noqa: UP045
) -> None:
    """Long-poll daemon for Slack monitoring."""
    _apply_globals(verbose, debug)
    if ctx.invoked_subcommand is None:
        _run_daemon(once=False, dry_run=dry_run, interval_override=interval)


def _run_daemon(*, once: bool = False, dry_run: bool = False, interval_override: int | None = None) -> None:
    """Core daemon loop."""
    existing_pid = read_pid()
    if existing_pid:
        typer.echo(
            f"ERROR: Daemon already running (PID {existing_pid}). Use 'stop' first.",
            err=True,
        )
        raise typer.Exit(code=1)

    write_pid()

    config = load_config()
    channels_str = config.get("AUTONOMOUS_CHANNELS", "")
    if not channels_str:
        typer.echo("ERROR: AUTONOMOUS_CHANNELS not set in config", err=True)
        raise typer.Exit(code=1)

    channels = [c.strip() for c in channels_str.split(",") if c.strip()]
    proxy_url = config.get("SLACK_PROXY_URL")
    poll_interval = interval_override or int(config.get("SLACK_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL)))

    _debug_log(f"Channels: {channels}")
    _debug_log(f"Proxy: {proxy_url or '(direct)'}")
    _debug_log(f"Interval: {poll_interval}s")
    _debug_log(f"Mode: {'once' if once else 'daemon'}")
    if dry_run:
        _log("DRY RUN mode enabled", level=0)

    token = load_token()
    identity = load_identity()
    scripts_dir = _find_scripts_dir()

    client = SlackClient(token, proxy_url)

    try:
        while not _shutdown:
            try:
                output = poll_cycle(client, channels, identity, scripts_dir, dry_run=dry_run)
            except Exception as exc:
                _log(f"ERROR: Poll cycle failed: {exc}", level=0)
                output = ""

            if output:
                typer.echo(output)
                sys.stdout.flush()
                break

            if once:
                break

            _debug_log(f"Sleeping {poll_interval}s")
            time.sleep(poll_interval)
    finally:
        client.close()


if __name__ == "__main__":
    app()
