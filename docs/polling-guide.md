# Slack Polling Guide

How agents monitor Slack channels for messages.

## Quick Start

```
/scc-slack:loop
```

This creates a 1-minute cron that manages the slack poller automatically.

## How It Works

```
/loop 2m cron fires
    → poller-loop skill checks: is poller running?
    → if stopped: launch via Bash(run_in_background: true, timeout: 600000)
    → if running: do nothing (zero cost)

poller runs in background
    → polls Slack every 30s
    → filters for actionable messages (direct @mentions, broadcasts, thread replies)
    → resolves sender names
    → fetches thread context
    → runs heartbeat + mention tracker tick
    → if actionable: outputs enriched JSON to stdout, exits
    → if quiet: sleeps 60s, polls again

agent gets notified (background task completed)
    → reads output with Read tool
    → processes messages: evaluate, respond in thread
    → next cron tick re-launches poller
```

## Message Format

The poller outputs a JSON array. Each message has:

```json
{
  "ts": "1773586114.731659",
  "user": "U09GJ25DZCP",
  "sender": "Christo",
  "text": "the message text",
  "match_type": "direct",
  "thread_ts": null,
  "channel": "agents",
  "channel_id": "C0AKTEMDP9C",
  "thread_context": [...]
}
```

- `sender` — pre-resolved display name (no API call needed)
- `match_type` — `direct` (you were @mentioned), `broadcast` (@here/@channel), `name` (your name in text), `thread_participant` (reply in a thread you're in)
- `thread_ts` — null for channel messages, set for thread replies
- `thread_context` — full thread history if this is a thread reply (array of `{sender, text, ts}`)

## Processing Messages

For each message chronologically:

1. **Skip closures** — "Got it", "Thanks", emoji-only, sign-offs. Unless there's a new request embedded.
2. **Decide** — Direct: always respond. Broadcast: respond if relevant, note reasoning if silent. Thread participant: respond if needed.
3. **Do the work** — Default to action, not questions.
4. **Respond in a thread** — Always. Channel messages: use the message's own `ts` as thread. Thread messages: use `thread_ts`.
5. **Honor commitments** — If your reply promises action, execute now or TaskCreate to track.

## Responding

```bash
source ~/.claude/slack.conf

# Reply to a channel message (starts a thread on it)
"${SCRIPTS_DIR}/slack-send" --thread "${TS}" "${CHANNEL_ID}" "@SenderName response"

# Reply in an existing thread
"${SCRIPTS_DIR}/slack-send" --thread "${THREAD_TS}" "${CHANNEL_ID}" "@SenderName response"
```

## Seen Set

The poller tracks every message it has output in `~/.claude/slack-seen.json`. A message is never output twice. The seen set prunes entries older than 24 hours.

On first run (empty seen set) or after long offline: the poller seeds all but the last 5 messages as "seen" so you don't respond to stale @mentions from hours ago.

## DO

- Use `Read` to read poller output (not `cat` via Bash or ctx_execute)
- Respond in threads, not the channel
- Let the cron manage the poller lifecycle
- Use `--debug` and `--dry-run` for troubleshooting

## DO NOT

- Do NOT call the Slack API directly with curl — use the scripts
- Do NOT create a separate heartbeat cron — heartbeat is built into the poller
- Do NOT manually manage cursors — the seen set handles deduplication
- Do NOT load the read skill on quiet cycles — the poller-loop skill handles status checks
- Do NOT run `slack-poll once` without consuming the output — messages will be marked seen

## Troubleshooting

```bash
source ~/.claude/slack.conf

# Check poller status
"${SCRIPTS_DIR}/slack-poll" status

# Stop the poller
"${SCRIPTS_DIR}/slack-poll" stop

# Single cycle with debug output
"${SCRIPTS_DIR}/slack-poll" once --debug

# Single cycle without side effects
"${SCRIPTS_DIR}/slack-poll" once --dry-run

# Verbose output
"${SCRIPTS_DIR}/slack-poll" once -vv

# Reset seen set (force re-scan with catchup)
rm ~/.claude/slack-seen.json
```

## Stopping

```
/scc-slack:stop
```

This stops the poller and deletes the cron job.
