---
name: read
description: Process Slack messages from the daemon. Use when the daemon-loop skill wakes you with actionable messages, or when the user says "check slack", "read slack".
---

# Read Slack Messages

Process actionable messages from the poll daemon.

```bash
source ~/.claude/slack.conf
```

Use `scripts/slack-*` helpers for all Slack operations — never call the API directly with curl. Prefer `ctx_execute` over Bash for scripts that produce output.

## Step 1: Identity (once per session)

Skip if you already have `USER_ID`, `USERNAME`, `DISPLAY_NAME`, `REAL_NAME`.

```bash
eval "$("${SCRIPTS_DIR}/slack-identity")"
```

## Step 2: Get messages

Messages come from daemon output (via `scc-slack:daemon-loop`). If invoked manually:
```bash
"${SCRIPTS_DIR}/slack-poll-daemon" --once
```

Output format: `# channel=NAME id=ID` headers + JSON arrays. Each message has `ts`, `user`, `text`, `match_type` (`direct`/`broadcast`/`name`/`thread_participant`), `bot_id`, `thread_ts`.

**Empty output or all `[]`:** stop silently.

## Step 3: Process each message

For each message chronologically:

**a) Resolve sender.** Via `ctx_execute`:
```bash
"${SCRIPTS_DIR}/slack-resolve" SENDER_USER_ID
```

If `thread_ts` is set, clear mention tracking (no-op if not tracked):
```bash
"${SCRIPTS_DIR}/slack-mention-tracker" responded "${CHANNEL}" "${THREAD_TS}" "${SENDER_USER_ID}"
```

**b) Read thread context.** If `thread_ts` is set, fetch via `ctx_execute`:
```bash
"${SCRIPTS_DIR}/slack-thread" "${CHANNEL}" "${THREAD_TS}"
```

**c) Skip conversation closures.** "Got it", "Thanks", "Sounds good", "Will do", emoji-only, sign-offs — don't respond. But act if there's a new request embedded ("Thanks — can you also check X?").

**d) Decide whether to respond.**
- **Direct mentions**: always respond.
- **Broadcasts**: respond if it matches your capabilities or asks all agents to act. Stay silent if another agent handled it. Never silently skip — note your reasoning.
- **Thread participant**: respond if conversation needs your input.

**e) Do the work.** Default to action, not questions.

- **Quick tasks**: do it, respond with the answer.
- **Real work**: react `eyes`, do the work now, report back with `white_check_mark`. If >3 files or architectural, acknowledge scope first.
- **Blocked**: acknowledge, state what you need, do the work when unblocked.
- **Deferred**: acknowledge, create a Linear issue (Agents team), mention the issue ID in your reply.

**f) Respond.** Same context as the message — same channel, same thread.

Channel messages:
```bash
"${SCRIPTS_DIR}/slack-send" "${CHANNEL}" "@SenderName response"
```

Thread messages:
```bash
"${SCRIPTS_DIR}/slack-send" --thread "${THREAD_TS}" "${CHANNEL}" "@SenderName response"
```

If you @mention another agent in a thread, track it:
```bash
"${SCRIPTS_DIR}/slack-mention-tracker" add "${CHANNEL}" "${THREAD_TS}" "${MENTIONED_USER_ID}"
```

**g) Honor commitments.** If your reply promises future action ("will RFC", "I'll update"), execute it now or create a `TaskCreate` to track it. Do not advance to the next message until commitments are resolved.

## Escalate only when

You lack access, it's a high-stakes judgment call, or you're genuinely stuck. Do not escalate for things you can handle with a reasonable assumption.
