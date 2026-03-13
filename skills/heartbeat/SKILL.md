---
name: heartbeat
description: Update agent heartbeat and check for stale peers. Use when the user says "heartbeat", "update heartbeat", "check agent health", or when triggered by a recurring cron job.
---

# Agent Heartbeat

Update your heartbeat in the pinned "Agent Status Check" thread and check peers for staleness.

## Arguments

- `channel_id` — channel containing the pinned status thread (optional, defaults to value from `~/.claude/slack.conf`)

## How It Works

### Heartbeat Signal

Each agent maintains exactly one reply in the pinned "Agent Status Check" thread. The script updates this reply via `chat.update` (no new messages — keeps the thread clean).

- **Digit**: `(current_minute_of_hour // 6) + 1` — gives digits 1-10, cycling every 6 minutes
- **Format**: `:<digit_emoji>: v<version>` (e.g. `:seven: v0.21.0`)
- **Config**: Thread ts and own message ts are cached in `~/.claude/slack-heartbeat.conf`

### Watchdog (Stale Detection)

After updating its own heartbeat, the script checks all peer bot messages in the thread:

- Compares each peer's digit to own digit using modular arithmetic: `gap = (own - peer + 10) % 10`
- Flags peers that are **2+ digits behind** as potentially stale
- **Humans are excluded** — only messages with a `bot_id` field are checked
- Stale alerts resolve user IDs to display names via `slack-resolve`
- Alert format: `@here Heartbeat check: possibly stale agents: Name (digit N, M behind)`

## Steps

1. Run the heartbeat script:
   ```bash
   SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-heartbeat" 2>/dev/null | sort -V | tail -1 | xargs dirname)
   "${SCRIPTS_DIR}/slack-heartbeat" [CHANNEL_ID]
   ```

2. The script will:
   - Auto-discover the pinned thread and own message on first run (cached for subsequent runs)
   - Update own heartbeat digit
   - Check all peer bots for staleness
   - Post `@here` alert if any peers are 2+ digits behind

## Stale Response Protocol

When you see a stale alert (either from your own watchdog or another agent's):

1. **First non-stale agent to respond claims the rescue** — react with `:eyes:` or reply
2. **Run `/emt` skill** to check on the stale agent
3. **Report back**: recovered, down (needs human), or false alarm
4. No fixed buddy pairs — per-incident, first-available assignment

## Self-Bootstrapping

On first run, the script:
1. Finds the pinned "Agent Status Check" message via `pins.list`
2. Scans thread replies for an existing message from this bot
3. If no existing message, posts a new reply
4. Caches both timestamps in `~/.claude/slack-heartbeat.conf`

If cached state becomes invalid (e.g. message deleted), the script clears the cache and re-bootstraps on next run.

## Scheduling

Heartbeat runs automatically as part of `slack-poll` — every poll cycle updates the heartbeat after checking for messages.

**DO NOT create a separate cron job for `/heartbeat`.** The heartbeat is built into `slack-poll`. If you are polling, you are heartbeating. Creating a separate heartbeat cron is redundant, wastes API calls, and causes confusion when the cron dies independently of polling.

To run heartbeat manually (e.g. after a fresh start before the first poll fires, or to force an immediate update):
```bash
"${SCRIPTS_DIR}/slack-heartbeat" [CHANNEL_ID]
```
This is only for one-off manual use — never schedule it as a recurring job.
