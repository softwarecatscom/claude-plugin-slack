---
name: read
description: Process Slack messages from the daemon. Use when the daemon-loop skill wakes you with actionable messages, or when the user says "check slack", "read slack".
---

# Read Slack Messages

Process actionable messages from the slack poller.

```bash
source ~/.claude/slack.conf
```

Use `scripts/slack-*` helpers for Slack operations. Prefer `ctx_execute` for scripts that produce output.

## Input

The daemon outputs a JSON array of enriched messages. Each message has:
- `channel`, `channel_id` — where it happened
- `sender`, `user` — display name and user ID
- `text`, `ts` — message content and timestamp
- `match_type` — `direct`/`broadcast`/`name`/`thread_participant`
- `thread_ts` — set if this is a thread reply
- `thread_context` — full thread history (array of `{sender, text, ts}`) if thread reply

Sender names are pre-resolved. Thread context is pre-fetched. Mention tracking for thread replies is auto-cleared. The agent only needs to evaluate and respond.

If invoked manually (not from daemon): `"${SCRIPTS_DIR}/slack-poll" --once`

## Process each message

For each message chronologically:

1. **Skip closures.** "Got it", "Thanks", emoji-only, sign-offs — don't respond unless there's a new request embedded.

2. **Decide.** Direct mentions: always respond. Broadcasts: respond if relevant to your capabilities or asks all agents to act; note reasoning if you stay silent. Thread participant: respond if needed.

3. **Do the work.** Default to action.
   - Quick tasks: respond with the answer.
   - Real work: react `eyes`, do it now, report with `white_check_mark`.
   - Blocked: acknowledge, state what you need.
   - Deferred: acknowledge, create Linear issue, mention ID in reply.

4. **Respond.** Always reply in a thread. For channel messages (`thread_ts` is null), use the message's own `ts` as the thread — this starts a new thread on that message:
   ```bash
   "${SCRIPTS_DIR}/slack-send" --thread "${TS}" "${CHANNEL_ID}" "@SenderName response"
   ```
   For thread messages (`thread_ts` is set), reply in the existing thread:
   ```bash
   "${SCRIPTS_DIR}/slack-send" --thread "${THREAD_TS}" "${CHANNEL_ID}" "@SenderName response"
   ```
   If you @mention another agent in a thread, track it:
   ```bash
   "${SCRIPTS_DIR}/slack-mention-tracker" add "${CHANNEL_ID}" "${THREAD_TS}" "${USER_ID}"
   ```

5. **Honor commitments.** If your reply promises action, execute now or `TaskCreate` to track it.
