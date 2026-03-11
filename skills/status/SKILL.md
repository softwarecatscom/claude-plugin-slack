---
name: status
description: Set Slack status text and emoji. Use when the user says "set slack status", "update status", "change presence", or wants to update their Slack status.
---

# Set Slack Status

Set the bot's Slack profile status text and emoji.

## Arguments

- `text` — status text (e.g., "In a meeting", "Working on deploy")
- `emoji` — status emoji without colons (optional, defaults to `speech_balloon`)

## Steps

1. Set the status (uses CLI — token is read automatically):
   ```bash
   slack status edit --text "<text>" --emoji ":<emoji>:"
   ```

2. Confirm the status was updated.
