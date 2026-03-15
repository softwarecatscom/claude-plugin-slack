---
name: read
description: Process Slack messages. Launches the poller if not running, processes output when it exits. Use when the loop cron fires, or when the user says "check slack", "read slack".
---

# Read Slack Messages

```bash
source ~/.claude/slack.conf
```

## Launch the poller

```
Bash(command: "source ~/.claude/slack.conf && ${SCRIPTS_DIR}/slack-poll run", description: "slack-poll", run_in_background: true, timeout: 600000)
```

## What to expect

- **Poller already running**: The poller rejects the duplicate and exits silently. No action needed.
- **Poller exited with messages (exit 0)**: You receive a background task notification. Read (not cat) the .output file and show its path. Then follow the Agent Algorithm below.

## Input format

The poller outputs a JSON array of enriched messages. Each message has:
- `channel`, `channel_id` — where it happened
- `sender`, `user` — display name and user ID
- `text`, `ts` — message content and timestamp
- `match_type` — `direct`/`broadcast`/`name`/`thread_participant`
- `thread_ts` — set if this is a thread reply

Sender names are pre-resolved. Mention tracking for thread replies is auto-cleared.

## Agent Algorithm

1. **Read** (not cat) the poller output and show the path of the .output file
2. **Scan the actionables** — check for conversation closure, classify, don't skip blindly
3. **Exclude conversation closures** — build the actionable list and note the count
4. **For each actionable message do the following:**
   i. **Evaluate** what's needed (task, question, greeting, broadcast relevance)
   ii. **Decide** whether to respond (direct: always. broadcast: judgment with reasoning. thread participant: if conversation needs your input)
   iii. **Do the work** (quick: respond with answer. real: eyes → do it → report with checkmark. blocked: acknowledge → ask what you need. deferred: acknowledge → Linear issue → mention ID)
   iv. **Respond appropriately** — start a new thread on channel messages, reply in existing threads, or @mention in the channel when the response is relevant to everyone
   v. **Track @mentions** to agents in your response
   vi. **Honor commitments** — if your reply promises action, execute now or TaskCreate
   vii. **Scan** your response for commitments you missed in step vi
   viii. **Move** to next message
5. **Cross check** the number of actionables from step 3 with the number of responses you made and use the counters to make sure you do not forget to respond to some messages

## Response commands

Start a new thread on a channel message:
```bash
"${SCRIPTS_DIR}/slack-send" --thread "${TS}" "${CHANNEL_ID}" "@SenderName response"
```

Reply in an existing thread:
```bash
"${SCRIPTS_DIR}/slack-send" --thread "${THREAD_TS}" "${CHANNEL_ID}" "@SenderName response"
```

Track an @mention to another agent:
```bash
"${SCRIPTS_DIR}/slack-mention-tracker" add "${CHANNEL_ID}" "${THREAD_TS}" "${USER_ID}"
```
