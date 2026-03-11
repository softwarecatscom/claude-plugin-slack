---
name: read
description: Read new Slack messages from a channel. Use when the user says "check slack", "read slack", "any slack messages", or wants to see recent channel messages.
---

# Read Slack Messages

Read new messages from a Slack channel, identify messages that need your attention, and act on them.

## Arguments

- `channel` — channel name or ID (optional, defaults to `DEFAULT_CHANNEL` from config)

## Scripts

This skill uses helper scripts in `scripts/` (found via the plugin cache). Locate them once per session:
```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

## Steps

### Step 1: Load config (once per session)

If you already have `DEFAULT_CHANNEL` and `AUTONOMOUS_CHANNELS` from a previous read, skip this step.

Use the `scc-slack:config` skill to load plugin config. If no channel was specified, use `DEFAULT_CHANNEL`.

### Step 2: Establish your identity (once per session)

If you already know your user ID, username, display name, and real name from a previous read, skip this step.

```bash
eval "$("${SCRIPTS_DIR}/slack-identity")"
```

This sets `USER_ID`, `USERNAME`, `DISPLAY_NAME`, and `REAL_NAME`. Keep these for the rest of the session.

### Step 3: Resolve channel to ID

```bash
CHANNEL_ID=$("${SCRIPTS_DIR}/slack-resolve" --channel "${CHANNEL}" | cut -d= -f1)
```

### Step 4: Fetch messages

```bash
MESSAGES=$("${SCRIPTS_DIR}/slack-fetch" "${CHANNEL_ID}")
```

### Step 5: Filter for actionable messages

```bash
ACTION_LIST=$(echo "${MESSAGES}" | "${SCRIPTS_DIR}/slack-filter")
```

This returns a JSON array of messages that mention you (direct, broadcast, or name match), excluding your own messages. Each entry has `ts`, `user`, `text`, `match_type`, and `bot_id`.

**If the action list is empty** (`[]`), update the cursor (step 8) and stop. Say nothing — do not report "no new messages."

### Step 6: Process each action message

For **each** message on the action list, in chronological order:

**a) Resolve display names.** Resolve the sender and any mentioned users:
```bash
"${SCRIPTS_DIR}/slack-resolve" SENDER_USER_ID OTHER_USER_IDS...
```
Cache results — the script handles this automatically across calls.

Replace `<!here>`, `<!channel>`, `<!everyone>` with `@here`, `@channel`, `@everyone` when presenting messages. Do NOT try to resolve these as users.

**b) Check for conversation closure.** Before acting, determine if this message is a **new request** or a **conversation closure**. This prevents infinite ping-pong between agents.

A message is **conversation closure** if:
- It is an acknowledgment of something you said: "Got it", "Thanks", "Sounds good", "No worries", "Will do", "Done"
- It is a sign-off: "Cheers", "Talk later", emoji-only responses
- It confirms receipt of your completed work without adding a new request
- It is a social nicety that expects no further action

A message is **NOT closure** (act on it) if:
- It contains a new task or question, even embedded in a thank-you: "Thanks — can you also check X?"
- It asks for clarification on your previous response
- It redirects you to something new: "Got it. Now can you..."
- It expresses dissatisfaction or asks you to redo something

**If you determine the message is conversation closure, do not respond.** Move to the next message. This is how conversations end naturally — not every message needs a reply.

**c) Evaluate what's needed.** Read the message and understand what the sender is asking:
- Is this a task you can do?
- Is this a question you can answer?
- Is this a greeting that warrants a brief reply?
- For broadcasts: is this relevant to your capabilities, or is another agent better suited?

**d) Decide whether to respond.** For direct mentions with a real request: always respond. For broadcasts, apply judgment:
- **Respond** if the request matches your capabilities or explicitly asks all agents to do something
- **Stay silent** if another agent already handled it, or responding would just add noise
- **Coordinate** — if the broadcast asks for a single volunteer, react with `eyes` first; if no other agent picks it up, do it
- **Never silently skip a broadcast** — if you decide not to respond, explicitly note your reasoning (e.g., "Z490 already handled this"). Dropping a broadcast without evaluation is a bug.

When in doubt about whether a message is for you, err on the side of responding — a brief reply is better than dropping a request.

**e) Do the work.** Default to action, not questions. If you can complete the task with the tools and context available, do it. Do not ask "should I go ahead?" — the message is the instruction. Handle multi-step tasks end to end.

**f) Respond.** Always respond **in the same channel** where the message was received. Never open a DM unless the sender explicitly asks for one — DMs fragment conversations and hide context from other agents and humans.

Use the send script to reply, addressing the sender:
```bash
"${SCRIPTS_DIR}/slack-send" "${CHANNEL}" "@SenderName your response here"
```
The script auto-resolves `@Name` to proper Slack mentions using the resolve cache. When you need to look up who's in the conversation, resolve users from the channel context — the people you're talking to are the people in that channel.

Use `scc-slack:react` with `eyes` when you pick up a message, and `white_check_mark` when done.

Keep responses concise — summary and key details, not a wall of text.

**g) Move to the next message.**

### Step 7: Update cursor

After processing all messages (or if there were no actionable messages), update the cursor to the newest message timestamp. Use the `MESSAGES` variable from step 4 — do not re-fetch:
```bash
NEWEST=$(echo "${MESSAGES}" | jq -r '.messages[0].ts')
"${SCRIPTS_DIR}/slack-cursor" write "${CHANNEL_ID}" "${NEWEST}"
```
**Tip:** Store `NEWEST` right after the fetch in step 4 so it's available here even if `MESSAGES` has been lost from context.

### Step 8: Mark channel as read

```bash
SLACK_TOKEN=$(cat "$(dirname "$(which slack)")/.slack" 2>/dev/null)
curl -s -X POST -H "Authorization: Bearer ${SLACK_TOKEN}" \
  -H "Content-type: application/json" \
  -d "{\"channel\":\"${CHANNEL_ID}\",\"ts\":\"${NEWEST}\"}" \
  https://slack.com/api/conversations.mark
```

## When to escalate

Involve your local user (the human at your terminal) only when:

- **You lack access** — the task requires credentials, permissions, or systems you can't reach
- **It's a judgment call** — significant consequences (deleting data, spending money, messaging external people) where the right choice isn't obvious
- **You're stuck** — you've tried and genuinely cannot make progress
- **It's ambiguous and high-stakes** — you're not sure what's being asked AND getting it wrong would be costly

Do NOT escalate for:
- Clarifying questions you could answer with a reasonable assumption (make the assumption, state it, proceed)
- Tasks that seem hard but are within your capabilities
- Requests where the intent is clear even if the wording is vague
