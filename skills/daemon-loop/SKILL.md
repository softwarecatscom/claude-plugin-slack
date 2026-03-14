---
name: daemon-loop
description: Start the long-poll daemon for Slack monitoring. Use when SLACK_POLL_DAEMON=1 is set in slack.conf, or when the user says "start daemon", "daemon mode", "long-poll", or "daemon loop".
---

# Daemon Loop

Long-poll daemon mode for Slack monitoring. Replaces the cron-based `/loop 1m` with a background process that only wakes the agent when actionable messages arrive. **~98% token reduction** compared to cron polling.

## Prerequisites

Set `SLACK_POLL_DAEMON=1` in `~/.claude/slack.conf`.

## How it works

1. Agent launches `slack-poll-daemon` via `Bash(run_in_background: true)`
2. Daemon polls Slack every 60s internally — **zero token cost** while waiting
3. Each cycle: runs `slack-poll` (fetch, filter, cursor advance, heartbeat) + mention tracker tick
4. When actionable messages found: daemon prints output to stdout and exits
5. Agent gets notified, processes the messages, re-launches daemon

## Setup

Locate scripts once per session:

```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-poll-daemon" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

## Starting the daemon

```bash
Bash(command: "${SCRIPTS_DIR}/slack-poll-daemon", run_in_background: true)
```

Save the returned task ID. The daemon runs silently until actionable messages arrive.

**Announce at start:** "Starting Slack daemon (long-poll mode)."

## Daemon management

```bash
# Check if daemon is running
"${SCRIPTS_DIR}/slack-poll-daemon" --status

# Stop the daemon
"${SCRIPTS_DIR}/slack-poll-daemon" --stop

# Single cycle for testing
"${SCRIPTS_DIR}/slack-poll-daemon" --once
```

The daemon uses a PID file (`~/.claude/slack-poll-daemon.pid`) to prevent duplicate instances. If a daemon is already running, the script exits with an error.

## When the daemon exits

You will be notified that the background task completed. The daemon's stdout contains the poll output — **same format as `slack-poll`**: comment lines (`# channel=NAME id=ID`, `# thread=TS channel=ID`) followed by JSON arrays of matching messages.

### Step 1: Read the output

Read the background task output. The output is already filtered — every non-empty array contains actionable messages.

### Step 2: Parse the output

Split the output by `#` header lines. Each section is a channel or thread with its JSON array. Parse each JSON array to get the message list.

Each message entry has `ts`, `user`, `text`, `match_type`, `bot_id`, and `thread_ts`. Match types:
- `direct` — you were @mentioned
- `broadcast` — @here/@channel/@everyone
- `name` — your name appeared in the text
- `thread_participant` — new reply in a thread you're part of

### Step 3: Process each message

For **each** message in chronological order:

**a) Resolve display names.** Resolve the sender and any mentioned users:
```bash
"${SCRIPTS_DIR}/slack-resolve" SENDER_USER_ID OTHER_USER_IDS...
```

**a2) Clear tracked @mentions.** If this message is a **thread reply** (`thread_ts` is set), check if the sender is an agent you previously @mentioned in that thread. If so, clear the tracking:
```bash
"${SCRIPTS_DIR}/slack-mention-tracker" responded "${CHANNEL}" "${THREAD_TS}" "${SENDER_USER_ID}"
```

**b) Read and understand the message.** Consider the full text, thread context, and match type.

**c) Identify any @mentions you need to track.** If your response will @mention another agent, track it:
```bash
"${SCRIPTS_DIR}/slack-mention-tracker" add "${CHANNEL}" "${THREAD_TS}" "${MENTIONED_USER_ID}"
```

**d) Decide whether to respond.**
- **Direct mentions** with a real request: always respond.
- **Broadcasts**: apply judgment:
  - **Respond** if the request matches your capabilities, explicitly asks all agents to do something, or is a team greeting
  - **Stay silent** if another agent already handled it, or responding would add noise
  - **Coordinate** — if the broadcast asks for a single volunteer, react with `eyes` first; if no other agent picks it up, do it
  - **Never silently skip a broadcast** — explicitly note your reasoning if you decide not to respond
- **Thread participant**: respond if the conversation needs your input, stay silent if it doesn't

**e) Respond.** Use the appropriate format:

For **channel-level messages** (thread_ts is null):
```bash
"${SCRIPTS_DIR}/slack-send" "${CHANNEL}" "@SenderName your response here"
```

For **thread messages** (thread_ts is set):
```bash
"${SCRIPTS_DIR}/slack-send" --thread "${THREAD_TS}" "${CHANNEL}" "@SenderName your response here"
```

**Prefer `ctx_execute` over Bash** when running scripts that produce output (resolve, mention tracker). Only use Bash for `slack-send` and `slack-react`.

**f) Honor your commitments.** If your reply contains a commitment ("will RFC", "I'll update", "going to send"), execute it NOW before processing the next message. If you cannot execute immediately, create a tracked task via `TaskCreate`.

**Conflicting requests**: if multiple messages ask for contradictory changes, process chronologically — latest instruction wins unless earlier was from a higher authority.

### Step 4: Re-launch the daemon

After processing all messages, re-launch:

```bash
Bash(command: "${SCRIPTS_DIR}/slack-poll-daemon", run_in_background: true)
```

## Configuration

In `~/.claude/slack.conf`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SLACK_POLL_DAEMON` | `0` | Set to `1` to enable daemon mode |
| `SLACK_POLL_INTERVAL` | `60` | Seconds between poll cycles inside the daemon |
| `AUTONOMOUS_CHANNELS` | — | Comma-separated channel names to monitor |
| `SLACK_PROXY_URL` | — | Optional caching proxy URL |

## Stopping

Use `--stop` to kill the daemon, or note the background task ID for `TaskStop`.

## Falling back to cron mode

If daemon mode has issues, unset `SLACK_POLL_DAEMON` (or set to `0`) and use the standard `scc-slack:loop` skill with `/loop 1m`.
