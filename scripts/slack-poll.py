#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "typer"]
# ///
"""Slack poller — long-poll monitor for Slack channels.

Runs continuously, polling Slack every POLL_INTERVAL seconds.
Only produces output (and exits) when actionable messages are found.
Designed to be launched via Bash(run_in_background: true).

Output: JSON array of enriched actionable messages with sender names resolved
and thread context included.
"""

from __future__ import annotations

import atexit
import contextlib
import importlib
import json
import os
import signal
import sys
import time
from functools import partial
from pathlib import Path
from typing import Optional

import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scc_slack import (
    SlackClient,
    filter_messages,
    load_config,
    load_identity,
    load_seen,
    load_token,
    resolve_channel,
    resolve_user,
    save_seen,
)
from slack_cli_options import COMMON_OPTIONS

# Import sibling modules (hyphenated names need importlib)
_heartbeat_mod = importlib.import_module("slack-heartbeat")
_mention_tracker_mod = importlib.import_module("slack-mention-tracker")

# --- Constants ---

DEFAULT_POLL_INTERVAL = 30
HISTORY_LIMIT = 20
THREAD_HISTORY_LIMIT = 50
MAX_THREADS = 5
CATCHUP_ACTIONABLE_LIMIT = 5
PID_FILE = Path.home() / ".claude" / "slack-poll.pid"

# --- Poller Options ---

POLL_OPTIONS = {
    "interval": typer.Option(None, "--interval", "-i", help="Poll interval in seconds"),
    "context": typer.Option(False, "--context", help="Include thread context in output"),
}

# --- App ---

app = typer.Typer(
    name="slack-poll",
    help="Slack poller — long-poll monitor for Slack channels.",
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


# --- Thread helpers ---


def _fetch_thread_context(api_get: callable, channel_id: str, thread_ts: str) -> list[dict]:
    """Fetch full thread as simplified context for the agent."""
    resp = api_get("conversations.replies", {"channel": channel_id, "ts": thread_ts, "limit": "50"})
    if not resp.get("ok"):
        return []
    return [
        {
            "sender": resolve_user(api_get, msg.get("user", "")),
            "text": msg.get("text", ""),
            "ts": msg.get("ts", ""),
        }
        for msg in resp.get("messages", [])
    ]


def _find_active_threads(thread_messages: list[dict], user_id: str, *, participating: bool) -> list[dict]:
    """Find threads with replies."""
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
        parents.append({"ts": msg["ts"], "latest_reply": msg.get("latest_reply", "")})
    parents.sort(key=lambda x: x["latest_reply"], reverse=True)
    return parents[:MAX_THREADS]


def _scan_threads(
    api_get: callable,
    channel_id: str,
    channel_name: str,
    parents: list[dict],
    identity: dict,
    seen: dict[str, str | None],
    *,
    participating: bool,
    include_context: bool = False,
) -> list[dict]:
    """Scan threads for actionable messages. Optionally include thread context."""
    resolve_fn = partial(resolve_user, api_get)
    results: list[dict] = []
    for parent in parents:
        parent_ts = parent["ts"]
        replies_resp = api_get("conversations.replies", {"channel": channel_id, "ts": parent_ts})
        reply_msgs = replies_resp.get("messages", []) if replies_resp.get("ok") else []
        reply_msgs = [m for m in reply_msgs if m.get("subtype") != "thread_broadcast" and m.get("ts") != parent_ts]
        matches = filter_messages(reply_msgs, identity, resolve_fn, thread_participant=participating)
        matches = [m for m in matches if m["ts"] not in seen]
        if not participating and not matches:
            continue
        if matches:
            thread_ctx = _fetch_thread_context(api_get, channel_id, parent_ts) if include_context else None
            for msg in matches:
                msg["channel"] = channel_name
                msg["channel_id"] = channel_id
                if thread_ctx is not None:
                    msg["thread_context"] = thread_ctx
                if participating:
                    _mention_tracker_mod.responded(channel_id, parent_ts, msg.get("user", ""))
            results.extend(matches)
    return results


# --- Poll cycle ---


def _poll_channel(
    api_get: callable, channel_name: str, identity: dict, seen: dict[str, str | None], *, include_context: bool = False
) -> list[dict]:
    """Poll a single channel for actionable messages, skipping already-seen ones."""
    channel_id = resolve_channel(api_get, channel_name)
    if not channel_id:
        _log(f"ERROR: Could not resolve channel '{channel_name}'", level=0)
        return []

    _debug_log(f"Polling #{channel_name} ({channel_id})")
    user_id = identity.get("USER_ID", "")
    resolve_fn = partial(resolve_user, api_get)

    # Fetch recent channel history
    history = api_get("conversations.history", {"channel": channel_id, "limit": str(HISTORY_LIMIT)})
    messages = history.get("messages", []) if history.get("ok") else []
    _debug_log(f"Channel messages: {len(messages)}")

    # Catchup: if seen is empty (first run / long offline), seed all but last N
    if not seen and messages:
        _log("First run catchup: seeding seen set from channel history", level=0)
        for msg in messages[CATCHUP_ACTIONABLE_LIMIT:]:
            seen[msg["ts"]] = msg.get("thread_ts")

    # Filter and strip seen
    actionable: list[dict] = []
    channel_matches = filter_messages(messages, identity, resolve_fn)
    channel_matches = [m for m in channel_matches if m["ts"] not in seen]
    for msg in channel_matches:
        msg["channel"] = channel_name
        msg["channel_id"] = channel_id
    actionable.extend(channel_matches)
    _debug_log(f"Channel matches (unseen): {len(channel_matches)}")

    # Thread scanning
    if len(messages) < THREAD_HISTORY_LIMIT:
        thread_resp = api_get("conversations.history", {"channel": channel_id, "limit": str(THREAD_HISTORY_LIMIT)})
        thread_messages = thread_resp.get("messages", []) if thread_resp.get("ok") else []
    else:
        thread_messages = messages

    participating = _find_active_threads(thread_messages, user_id, participating=True)
    _debug_log(f"Participating threads: {len(participating)}")
    actionable.extend(
        _scan_threads(
            api_get,
            channel_id,
            channel_name,
            participating,
            identity,
            seen,
            participating=True,
            include_context=include_context,
        )
    )

    non_participating = _find_active_threads(thread_messages, user_id, participating=False)
    _debug_log(f"Non-participating threads: {len(non_participating)}")
    actionable.extend(
        _scan_threads(
            api_get,
            channel_id,
            channel_name,
            non_participating,
            identity,
            seen,
            participating=False,
            include_context=include_context,
        )
    )

    return actionable


def poll_cycle(
    client: SlackClient,
    channels: list[str],
    identity: dict,
    *,
    dry_run: bool = False,
    include_context: bool = False,
) -> str:
    """Run one poll cycle. Returns enriched JSON if actionable, empty if quiet."""
    seen = load_seen()
    all_actionable: list[dict] = []
    for channel in channels:
        stripped = channel.strip()
        if stripped:
            all_actionable.extend(_poll_channel(client.get, stripped, identity, seen, include_context=include_context))

    # Mark all output messages as seen
    for msg in all_actionable:
        seen[msg["ts"]] = msg.get("thread_ts")
    save_seen(seen)

    if not dry_run:
        with contextlib.suppress(Exception):
            _heartbeat_mod.run_heartbeat()
        with contextlib.suppress(Exception):
            _mention_tracker_mod.tick()
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
        os.kill(pid, 0)
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


def _apply_globals(verbose: int, debug: bool) -> None:
    """Set global verbosity and debug flags."""
    global _verbose, _debug  # noqa: PLW0603
    _verbose = verbose
    _debug = debug


@app.command()
def stop() -> None:
    """Stop a running poller."""
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            typer.echo(f"Stopped poller (PID {pid})")
        except ProcessLookupError:
            typer.echo("Poller not running (stale PID file)")
        PID_FILE.unlink(missing_ok=True)
    else:
        typer.echo("Poller not running")


@app.command()
def status() -> None:
    """Check if poller is running."""
    pid = read_pid()
    if pid:
        typer.echo(f"running (PID {pid})")
    else:
        typer.echo("stopped")


@app.command()
def once(
    verbose: int = COMMON_OPTIONS["verbose"],
    debug: bool = COMMON_OPTIONS["debug"],
    dry_run: bool = COMMON_OPTIONS["dry_run"],
    context: bool = POLL_OPTIONS["context"],
) -> None:
    """Run a single poll cycle (for testing)."""
    _apply_globals(verbose, debug)
    _run_poller(once=True, dry_run=dry_run, include_context=context)


@app.command()
def run(
    verbose: int = COMMON_OPTIONS["verbose"],
    debug: bool = COMMON_OPTIONS["debug"],
    dry_run: bool = COMMON_OPTIONS["dry_run"],
    interval: Optional[int] = POLL_OPTIONS["interval"],  # noqa: UP045
    context: bool = POLL_OPTIONS["context"],
) -> None:
    """Run poller until actionable messages found (default command)."""
    _apply_globals(verbose, debug)
    _run_poller(once=False, dry_run=dry_run, interval_override=interval, include_context=context)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    verbose: int = COMMON_OPTIONS["verbose"],
    debug: bool = COMMON_OPTIONS["debug"],
    dry_run: bool = COMMON_OPTIONS["dry_run"],
    interval: Optional[int] = POLL_OPTIONS["interval"],  # noqa: UP045
    context: bool = POLL_OPTIONS["context"],
) -> None:
    """Slack poller — long-poll monitor for Slack channels."""
    _apply_globals(verbose, debug)
    if ctx.invoked_subcommand is None:
        _run_poller(once=False, dry_run=dry_run, interval_override=interval, include_context=context)


def _run_poller(
    *, once: bool = False, dry_run: bool = False, interval_override: int | None = None, include_context: bool = False
) -> None:
    """Core poller loop."""
    existing_pid = read_pid()
    if existing_pid:
        typer.echo(f"ERROR: Poller already running (PID {existing_pid}). Use 'stop' first.", err=True)
        raise typer.Exit(code=1)

    write_pid()

    config = load_config()
    channels_str = config.get("AUTONOMOUS_CHANNELS", "")
    if not channels_str:
        typer.echo("ERROR: AUTONOMOUS_CHANNELS not set in config", err=True)
        raise typer.Exit(code=1)

    channels = [c.strip() for c in channels_str.split(",") if c.strip()]
    proxy_url = os.environ.get("SLACK_PROXY_URL", config.get("SLACK_PROXY_URL"))
    poll_interval = interval_override or int(config.get("SLACK_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL)))

    _debug_log(f"Channels: {channels}")
    _debug_log(f"Proxy: {proxy_url or '(direct)'}")
    _debug_log(f"Interval: {poll_interval}s")
    _debug_log(f"Mode: {'once' if once else 'poller'}")
    if dry_run:
        _log("DRY RUN mode enabled", level=0)

    token = load_token()
    client = SlackClient(token, proxy_url)
    identity = load_identity(api_get=client.get)
    _debug_log(f"Identity: {identity.get('REAL_NAME', '?')} ({identity.get('USER_ID', '?')})")

    try:
        while not _shutdown:
            try:
                output = poll_cycle(client, channels, identity, dry_run=dry_run, include_context=include_context)
            except Exception as exc:
                _log(f"ERROR: Poll cycle failed: {exc}", level=0)
                output = ""

            if output:
                typer.echo(output)
                typer.echo("\nUse the `scc-slack:read` skill to process these messages.")
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
