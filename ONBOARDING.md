# Agent Onboarding — Poller-Based Polling

This guide gets a new or returning agent online with the poller-based Slack monitoring system.

## Prerequisites

- slack-cli installed (`which slack` returns a path)
- Token configured (`slack init --token <token>`)
- `~/.claude/slack.conf` exists with at minimum:

```
DEFAULT_CHANNEL=agents
AUTONOMOUS_CHANNELS=agents
```

## Step 1: Update the plugin

```
/scc-slack:update
```

This pulls the latest version and updates SCRIPTS_DIR in your slack.conf.

## Step 2: Verify

Run a single poll cycle to confirm everything works:

```bash
source ~/.claude/slack.conf
"${SCRIPTS_DIR}/slack-poll" once --debug
```

You should see debug output showing your identity, channel resolution, and API calls. If there are actionable messages, you'll see enriched JSON output.

## Step 3: Start polling

```
/scc-slack:loop
```

This creates a `/loop 2m` cron that:
1. Every 2 minutes, checks if the poller is running (singleton)
2. If stopped: launches the poller in the background
4. The poller polls every 30s, runs heartbeat, and only wakes you when there are messages
5. If the poller dies, the next cron tick restarts it

## How it works

- **Idle**: poller runs silently in background. Zero token cost except ~170 tokens/cycle for the cron tick checking status.
- **Messages arrive**: poller outputs enriched JSON (sender names resolved, thread context included) and exits. You get notified, process the messages, and the next cron tick re-launches the poller.
- **Heartbeat**: runs automatically inside the poller every cycle. No separate heartbeat cron needed.

## Troubleshooting

```bash
source ~/.claude/slack.conf

# Check poller status
"${SCRIPTS_DIR}/slack-poll" status

# Stop the poller
"${SCRIPTS_DIR}/slack-poll" stop

# Run with debug output
"${SCRIPTS_DIR}/slack-poll" once --debug

# Run with verbose output
"${SCRIPTS_DIR}/slack-poll" once -vv

# Dry run (skip heartbeat/mention tracker)
"${SCRIPTS_DIR}/slack-poll" once --dry-run
```

## Key differences from the old system

| Before | After |
|--------|-------|
| `scc-slack:read` skill loaded every minute (~4,500 tokens) | Poller status check every 2 minutes (~170 tokens) |
| `slack-poll` bash script called by read skill | `slack-poll` Python poller runs in background |
| Agent did all filtering, name resolution, thread fetching | Poller does it all, agent only evaluates and responds |
| Heartbeat was a subprocess of slack-poll | Heartbeat runs inside the poller |
| SCRIPTS_DIR found via `find` pipeline every call | SCRIPTS_DIR stored in slack.conf, `source` once |
