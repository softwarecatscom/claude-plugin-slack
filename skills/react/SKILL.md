---
name: react
description: React to a Slack message with an emoji. Use when the user says "react", "add emoji", "thumbs up that", or wants to add a reaction to a message.
---

# React to Slack Message

Add an emoji reaction to a Slack message. When invoked with no arguments, autonomously pick the most appropriate message and emoji from recent read context.

## Arguments

All arguments are optional:

- `emoji` — emoji name without colons (e.g., `thumbsup`, `eyes`, `white_check_mark`). If omitted, infer from message content (see Step 3).
- `author` — narrow to a specific sender's message (e.g., "react to Z490's message"). If omitted, use the most recently read message.

## Emoji Blocklist

Never use these emojis autonomously: `skull`, `skull_and_crossbones`, `clown_face`, `middle_finger`, `poop`, `angry`, `rage`, `nauseated_face`, `vomiting_face`.

If the user explicitly requests a blocked emoji, use it — the blocklist only applies to autonomous selection.

## Safe Defaults

When inferring, prefer these high-confidence mappings:

| Message tone | Emoji |
|---|---|
| Acknowledgment, agreement, approval | `thumbsup` |
| Looking into it, will review | `eyes` |
| Task completed, done | `white_check_mark` |
| Greeting, welcome | `wave` |
| Celebration, great news, launch | `raised_hands` or `rocket` |
| Gratitude, thanks | `pray` |
| Funny, amusing | `joy` |
| **Ambiguous or uncertain tone** | **`thumbsup`** (always default here — a generic reaction is better than a wrong one) |

## Scripts

Load plugin config (provides SCRIPTS_DIR, DEFAULT_CHANNEL, AUTONOMOUS_CHANNELS):
```bash
source ~/.claude/slack.conf
```

**Prefer `ctx_execute` over Bash** when running scripts that produce output. This keeps raw output in the sandbox and protects your context window.

## Steps

### Step 1: Load scripts

Load plugin config (see Scripts above). **Always use `slack-react` for reactions — do not call the Slack API directly.**

### Step 2: Determine the target message

Get the last-read message timestamp and channel from `~/.claude/slack-cursors.conf`. The most recently updated entry is the target:
```bash
IFS='=' read -r CHANNEL_ID MESSAGE_TS < <(tail -1 ~/.claude/slack-cursors.conf)
```

**If an author name was specified**, resolve to a user ID:
```bash
"${SCRIPTS_DIR}/slack-resolve" --name "<author_name>"
```
Then scan the recently fetched messages for one with a matching `.user` field and use that message's `ts` instead.

### Step 3: Determine the emoji

In priority order:

1. **Explicit arg**: if the user provided an emoji name, use it exactly.
2. **Contextual inference**: if no emoji was provided, look at the target message content in your conversation context (from the most recent `/scc-slack:read`). Match the message tone to the safe defaults table above. If you are not confident in the mapping, use `thumbsup`.
3. **No context available**: if there is no recent read context in the conversation (e.g., invoked cold without a prior read), ask the user for the emoji name. Do not guess blind.

### Step 4: Dedup check

Before reacting, check if you have already reacted to this message with this emoji (via `ctx_execute`):

```bash
"${SCRIPTS_DIR}/slack-react" --check "${CHANNEL_ID}" "${MESSAGE_TS}" "${EMOJI}"
```

If the output is `yes`, the reaction is already there. Skip and confirm: "Already reacted with :emoji:".

### Step 5: Add the reaction

```bash
"${SCRIPTS_DIR}/slack-react" "${CHANNEL_ID}" "${MESSAGE_TS}" "${EMOJI}"
```

### Step 6: Confirm

Confirm the reaction was added. Keep it brief: "Reacted with :emoji: to [sender]'s message."
