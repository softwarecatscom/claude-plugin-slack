---
name: daemon-loop
description: Supervise the Slack poll daemon — launch if stopped, process messages when it wakes. Invoked by the /loop 1m cron every minute.
---

# Daemon Loop

Supervises the long-poll daemon. Called every minute by the `/loop 1m` cron. Zero token cost on quiet cycles — only loads the read skill when messages arrive.

## Setup

Locate scripts once per session:

```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-poll-daemon" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

## Step 1: Check daemon status

```bash
"${SCRIPTS_DIR}/slack-poll-daemon" --status
```

- **"running"**: Stop here. Say nothing. The daemon is healthy.
- **"stopped"**: Continue to Step 2.

## Step 2: Launch daemon

```bash
Bash(command: "${SCRIPTS_DIR}/slack-poll-daemon", run_in_background: true)
```

On first launch only, announce: "Slack daemon started."

The daemon polls every 60s internally, runs heartbeat and mention tracker each cycle, and only exits when it finds actionable messages.

## When the daemon exits (background task completes)

You will be notified that the background task completed. Read the output — it contains actionable messages in the same format as the old `slack-poll`: comment headers (`# channel=NAME id=ID`) followed by JSON arrays.

**Use the `scc-slack:read` skill to process the messages.** Pass the daemon output as the pre-fetched poll data — the read skill will handle parsing, evaluation, and responses without re-polling.

After processing, the daemon is stopped. The next cron tick (Step 1) will see "stopped" and re-launch it.

## Daemon management

```bash
# Stop the daemon manually
"${SCRIPTS_DIR}/slack-poll-daemon" --stop

# Single cycle for testing
"${SCRIPTS_DIR}/slack-poll-daemon" --once
```
