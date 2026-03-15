#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Long-poll daemon for Slack monitoring.

Runs continuously, polling Slack every POLL_INTERVAL seconds.
Only produces output (and exits) when actionable messages are found.
Designed to be launched via Bash(run_in_background: true).

Usage:
  slack-poll-daemon              — run until actionable messages found
  slack-poll-daemon --once       — run a single cycle (for testing)
  slack-poll-daemon --stop       — stop any running daemon
  slack-poll-daemon --status     — check if daemon is running

Output: JSON array of enriched actionable messages with sender names resolved
and thread context included. The agent receives everything needed to evaluate
and respond without additional API calls.
"""

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

import httpx

# --- Paths ---

CONFIG_FILE = Path.home() / ".claude" / "slack.conf"
IDENTITY_FILE = Path.home() / ".claude" / "slack-cache" / "identity"
CURSOR_FILE = Path.home() / ".claude" / "slack-cursors.conf"
THREAD_CURSOR_FILE = Path.home() / ".claude" / "slack-thread-cursors.conf"
CHANNEL_CACHE = Path.home() / ".claude" / "slack-cache" / "channels"
USER_CACHE = Path.home() / ".claude" / "slack-cache" / "users"
MENTION_TRACKER_STATE = Path.home() / ".claude" / "slack-mention-tracker.json"
PID_FILE = Path.home() / ".claude" / "slack-poll-daemon.pid"
FALLBACK_STATE_FILE = Path.home() / ".claude" / "slack-proxy-fallback-alerted"

# --- Constants ---

DEFAULT_POLL_INTERVAL = 60
HISTORY_LIMIT = 20
HISTORY_LIMIT_NO_CURSOR = 10
THREAD_HISTORY_LIMIT = 50
MAX_THREADS = 5
FALLBACK_COOLDOWN = 600  # 10 minutes

# --- Shutdown ---

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# --- Config ---


def load_config() -> dict:
    """Load key=value config from slack.conf."""
    config = {}
    if not CONFIG_FILE.exists():
        print(f"ERROR: No config at {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    for line in CONFIG_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip().strip('"').strip("'")
    return config


def load_identity() -> dict:
    """Load identity from ~/.claude/slack-cache/identity."""
    if not IDENTITY_FILE.exists():
        scripts_dir = _find_scripts_dir()
        if scripts_dir:
            subprocess.run(
                [str(scripts_dir / "slack-identity")],
                capture_output=True,
                timeout=30,
            )
    if not IDENTITY_FILE.exists():
        print("ERROR: No identity cached.", file=sys.stderr)
        sys.exit(1)
    identity = {}
    for line in IDENTITY_FILE.read_text().splitlines():
        line = line.strip()
        if "=" in line:
            key, _, value = line.partition("=")
            identity[key.strip()] = value.strip().strip('"')
    return identity


def load_token() -> str:
    """Load Slack token from slack-cli's .slack file."""
    slack_bin = shutil.which("slack")
    if not slack_bin:
        print("ERROR: slack-cli not found in PATH", file=sys.stderr)
        sys.exit(1)
    token_file = Path(slack_bin).parent / ".slack"
    if not token_file.exists():
        print("ERROR: No Slack token found.", file=sys.stderr)
        sys.exit(1)
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

    def __init__(self, token: str, proxy_url: str | None = None):
        self.token = token
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

    def _fallback_warn(self, reason: str):
        """Emit a proxy fallback warning with 10-minute cooldown."""
        now = time.time()
        if now - self._last_fallback_warn < FALLBACK_COOLDOWN:
            return
        self._last_fallback_warn = now
        print(
            f"WARN: Proxy {self.base_url} unreachable ({reason}), "
            f"falling back to direct Slack",
            file=sys.stderr,
        )
        FALLBACK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        FALLBACK_STATE_FILE.write_text(str(int(now)))

    def close(self):
        self._client.close()


# --- Channel resolution ---


def resolve_channel(client: SlackClient, name: str) -> str | None:
    """Resolve a channel name to an ID, using cache."""
    if re.match(r"^C[A-Z0-9]+$", name):
        return name
    # Check cache
    if CHANNEL_CACHE.exists():
        for line in CHANNEL_CACHE.read_text().splitlines():
            if "=" in line:
                cached_id, _, cached_name = line.partition("=")
                if cached_name.lower() == name.lower():
                    return cached_id
    # API call
    resp = client.get(
        "conversations.list",
        {"types": "public_channel,private_channel", "limit": "200"},
    )
    if resp.get("ok"):
        CHANNEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        found = None
        for ch in resp.get("channels", []):
            lines.append(f"{ch['id']}={ch['name']}")
            if ch["name"].lower() == name.lower():
                found = ch["id"]
        CHANNEL_CACHE.write_text("\n".join(lines) + "\n")
        return found
    return None


# --- User resolution ---


def resolve_user(client: SlackClient, user_id: str) -> str:
    """Resolve a user ID to display name, using cache."""
    if not user_id:
        return "unknown"
    # Check cache
    if USER_CACHE.exists():
        for line in USER_CACHE.read_text().splitlines():
            if line.startswith(f"{user_id}="):
                return line.split("=", 1)[1]
    # API call
    resp = client.get("users.info", {"user": user_id})
    if resp.get("ok"):
        profile = resp.get("user", {}).get("profile", {})
        name = (
            profile.get("display_name")
            or profile.get("real_name")
            or resp.get("user", {}).get("name", "unknown")
        )
        # Append to cache
        USER_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(USER_CACHE, "a") as f:
            f.write(f"{user_id}={name}\n")
        return name
    return "unknown"


# --- Mention tracker (inline) ---


def mention_tracker_responded(channel: str, thread_ts: str, user_id: str):
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
        if not (
            e.get("channel") == channel
            and e.get("thread_ts") == thread_ts
            and e.get("user_id") == user_id
        )
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


def write_cursor(cursor_file: Path, channel_id: str, ts: str):
    """Write cursor for a channel (atomic)."""
    cursor_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if cursor_file.exists():
        lines = [
            line
            for line in cursor_file.read_text().splitlines()
            if not line.startswith(f"{channel_id}=")
        ]
    lines.append(f"{channel_id}={ts}")
    fd, tmp = tempfile.mkstemp(prefix="slack-cursors.", dir="/tmp")
    os.close(fd)
    Path(tmp).write_text("\n".join(lines) + "\n")
    os.replace(tmp, str(cursor_file))


# --- Message filtering ---


def filter_messages(
    messages: list[dict],
    identity: dict,
    client: SlackClient | None = None,
    thread_participant: bool = False,
) -> list[dict]:
    """Filter messages for actionable ones. Resolves sender names if client provided."""
    user_id = identity.get("USER_ID", "")
    username = identity.get("USERNAME", "").lower()
    display_name = identity.get("DISPLAY_NAME", "").lower()
    real_name = identity.get("REAL_NAME", "").lower()

    results = []
    for msg in messages:
        # Skip own messages
        if msg.get("user") == user_id:
            continue
        # Skip non-standard subtypes
        subtype = msg.get("subtype")
        if subtype and subtype not in ("bot_message", "thread_broadcast"):
            continue

        text = msg.get("text", "")
        text_lower = text.lower()
        match_type = None

        # Direct mention <@USER_ID>
        if f"<@{user_id}>" in text:
            match_type = "direct"
        # Broadcast mentions
        elif re.search(
            r"<!here>|<!channel>|<!everyone>"
            r"|(^|\s)@here(\s|$)"
            r"|(^|\s)@channel(\s|$)"
            r"|(^|\s)@everyone(\s|$)",
            text,
        ):
            match_type = "broadcast"
        # @name mentions (case-insensitive, require @ prefix)
        elif username and f"@{username}" in text_lower:
            match_type = "name"
        elif display_name and f"@{display_name}" in text_lower:
            match_type = "name"
        elif (
            real_name
            and real_name != display_name
            and f"@{real_name}" in text_lower
        ):
            match_type = "name"
        # Thread participant mode
        elif thread_participant:
            match_type = "thread_participant"

        if match_type:
            sender_id = msg.get("user", "")
            entry = {
                "ts": msg.get("ts"),
                "user": sender_id,
                "sender": resolve_user(client, sender_id) if client else sender_id,
                "text": text,
                "match_type": match_type,
                "thread_ts": msg.get("thread_ts"),
            }
            results.append(entry)

    # Reverse to chronological order (oldest first)
    results.reverse()
    return results


# --- Poll cycle ---


def fetch_thread_context(
    client: SlackClient, channel_id: str, thread_ts: str
) -> list[dict]:
    """Fetch full thread as simplified context for the agent."""
    resp = client.get(
        "conversations.replies",
        {"channel": channel_id, "ts": thread_ts, "limit": "50"},
    )
    if not resp.get("ok"):
        return []
    context = []
    for msg in resp.get("messages", []):
        context.append(
            {
                "sender": resolve_user(client, msg.get("user", "")),
                "text": msg.get("text", ""),
                "ts": msg.get("ts", ""),
            }
        )
    return context


def poll_cycle(
    client: SlackClient,
    channels: list[str],
    identity: dict,
    scripts_dir: Path | None,
) -> str:
    """Run one poll cycle. Returns enriched JSON if actionable, empty if quiet."""
    all_actionable: list[dict] = []
    user_id = identity.get("USER_ID", "")

    for channel_name in channels:
        channel_name = channel_name.strip()
        if not channel_name:
            continue

        channel_id = resolve_channel(client, channel_name)
        if not channel_id:
            print(
                f"ERROR: Could not resolve channel '{channel_name}'",
                file=sys.stderr,
            )
            continue

        # Read cursors
        old_cursor = read_cursor(CURSOR_FILE, channel_id)

        # Fetch channel history
        params: dict[str, str] = {
            "channel": channel_id,
            "limit": str(HISTORY_LIMIT if old_cursor else HISTORY_LIMIT_NO_CURSOR),
        }
        if old_cursor:
            params["oldest"] = old_cursor

        history = client.get("conversations.history", params)
        messages = history.get("messages", []) if history.get("ok") else []

        # Filter channel messages
        channel_matches = filter_messages(messages, identity, client)
        for msg in channel_matches:
            msg["channel"] = channel_name
            msg["channel_id"] = channel_id
        all_actionable.extend(channel_matches)

        # --- Thread scanning ---
        thread_history = client.get(
            "conversations.history",
            {"channel": channel_id, "limit": str(THREAD_HISTORY_LIMIT)},
        )
        thread_messages = (
            thread_history.get("messages", []) if thread_history.get("ok") else []
        )

        old_thread_cursor = read_cursor(THREAD_CURSOR_FILE, channel_id)
        effective_cursor = old_thread_cursor or old_cursor

        # --- Participating threads ---
        thread_parents = []
        for msg in thread_messages:
            if msg.get("reply_count", 0) <= 0:
                continue
            reply_users = msg.get("reply_users", [])
            if msg.get("user") != user_id and user_id not in reply_users:
                continue
            latest_reply = msg.get("latest_reply", "")
            if effective_cursor and latest_reply <= effective_cursor:
                continue
            thread_parents.append(
                {"ts": msg["ts"], "latest_reply": latest_reply}
            )

        thread_parents.sort(key=lambda x: x["latest_reply"], reverse=True)
        thread_parents = thread_parents[:MAX_THREADS]

        for parent in thread_parents:
            parent_ts = parent["ts"]
            replies_resp = client.get(
                "conversations.replies",
                {
                    "channel": channel_id,
                    "ts": parent_ts,
                    "oldest": effective_cursor or "0",
                },
            )
            reply_msgs = (
                replies_resp.get("messages", []) if replies_resp.get("ok") else []
            )
            reply_msgs = [
                m for m in reply_msgs if m.get("subtype") != "thread_broadcast"
            ]
            thread_matches = filter_messages(
                reply_msgs, identity, client, thread_participant=True
            )
            # Enrich with channel info and thread context
            if thread_matches:
                thread_ctx = fetch_thread_context(client, channel_id, parent_ts)
                for msg in thread_matches:
                    msg["channel"] = channel_name
                    msg["channel_id"] = channel_id
                    msg["thread_context"] = thread_ctx
                    # Auto-clear mention tracking
                    mention_tracker_responded(
                        channel_id, parent_ts, msg.get("user", "")
                    )
                all_actionable.extend(thread_matches)

        # --- Non-participating threads with @mentions ---
        mention_parents = []
        for msg in thread_messages:
            if msg.get("reply_count", 0) <= 0:
                continue
            reply_users = msg.get("reply_users", [])
            if msg.get("user") == user_id or user_id in reply_users:
                continue
            latest_reply = msg.get("latest_reply", "")
            if effective_cursor and latest_reply <= effective_cursor:
                continue
            mention_parents.append(
                {"ts": msg["ts"], "latest_reply": latest_reply}
            )

        mention_parents.sort(key=lambda x: x["latest_reply"], reverse=True)
        mention_parents = mention_parents[:MAX_THREADS]

        for parent in mention_parents:
            parent_ts = parent["ts"]
            replies_resp = client.get(
                "conversations.replies",
                {
                    "channel": channel_id,
                    "ts": parent_ts,
                    "oldest": effective_cursor or "0",
                },
            )
            reply_msgs = (
                replies_resp.get("messages", []) if replies_resp.get("ok") else []
            )
            reply_msgs = [
                m for m in reply_msgs if m.get("subtype") != "thread_broadcast"
            ]
            mention_matches = filter_messages(reply_msgs, identity, client)
            if mention_matches:
                thread_ctx = fetch_thread_context(client, channel_id, parent_ts)
                for msg in mention_matches:
                    msg["channel"] = channel_name
                    msg["channel_id"] = channel_id
                    msg["thread_context"] = thread_ctx
                all_actionable.extend(mention_matches)

        # --- Advance cursors ---
        if messages:
            newest_ts = messages[0].get("ts", "")
            if newest_ts:
                write_cursor(CURSOR_FILE, channel_id, newest_ts)

        newest_thread_ts = ""
        for parent in thread_parents:
            for msg in thread_messages:
                if msg["ts"] == parent["ts"]:
                    lr = msg.get("latest_reply", "")
                    if lr > newest_thread_ts:
                        newest_thread_ts = lr
                    break
        if newest_thread_ts:
            write_cursor(THREAD_CURSOR_FILE, channel_id, newest_thread_ts)

    # --- Heartbeat ---
    if scripts_dir:
        try:
            subprocess.run(
                [str(scripts_dir / "slack-heartbeat")],
                capture_output=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    # --- Mention tracker tick ---
    if scripts_dir:
        try:
            subprocess.run(
                [str(scripts_dir / "slack-mention-tracker"), "tick"],
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    if all_actionable:
        return json.dumps(all_actionable, indent=2)
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


def write_pid():
    """Write current PID and register cleanup."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    def cleanup():
        PID_FILE.unlink(missing_ok=True)

    import atexit

    atexit.register(cleanup)


# --- Commands ---


def cmd_stop():
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Stopped daemon (PID {pid})")
        except ProcessLookupError:
            print("Daemon not running (stale PID file)")
        PID_FILE.unlink(missing_ok=True)
    else:
        print("Daemon not running")


def cmd_status():
    pid = read_pid()
    if pid:
        print(f"running (PID {pid})")
    else:
        print("stopped")


# --- Main ---


def main():
    args = sys.argv[1:]

    if "--stop" in args:
        cmd_stop()
        return
    if "--status" in args:
        cmd_status()
        return

    once = "--once" in args

    # Singleton check
    existing_pid = read_pid()
    if existing_pid:
        print(
            f"ERROR: Daemon already running (PID {existing_pid}). Use --stop first.",
            file=sys.stderr,
        )
        sys.exit(1)

    write_pid()

    # Load configuration
    config = load_config()
    channels_str = config.get("AUTONOMOUS_CHANNELS", "")
    if not channels_str:
        print("ERROR: AUTONOMOUS_CHANNELS not set in config", file=sys.stderr)
        sys.exit(1)

    channels = [c.strip() for c in channels_str.split(",") if c.strip()]
    proxy_url = config.get("SLACK_PROXY_URL")
    poll_interval = int(
        config.get("SLACK_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL))
    )

    token = load_token()
    identity = load_identity()
    scripts_dir = _find_scripts_dir()

    client = SlackClient(token, proxy_url)

    try:
        while not _shutdown:
            try:
                output = poll_cycle(client, channels, identity, scripts_dir)
            except Exception as exc:
                print(f"ERROR: Poll cycle failed: {exc}", file=sys.stderr)
                output = ""

            if output:
                print(output)
                sys.stdout.flush()
                break

            if once:
                break

            time.sleep(poll_interval)
    finally:
        client.close()


if __name__ == "__main__":
    main()
