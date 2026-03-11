---
name: read
description: Read new Slack messages from a channel. Use when the user says "check slack", "read slack", "any slack messages", or wants to see recent channel messages.
---

# Read Slack Messages

Read new messages from a Slack channel and act on them autonomously.

## Arguments

- `channel` — channel name or ID (optional, defaults to `DEFAULT_CHANNEL` from config)

## Steps

1. Use the `scc-slack:token` skill to load `SLACK_TOKEN`.

2. Use the `scc-slack:config` skill to load plugin config. If no channel was specified, use `DEFAULT_CHANNEL`.

3. Use the `scc-slack:lookup` skill to resolve the channel name to a channel ID.

4. Read the last cursor timestamp for this channel:
   ```bash
   CURSOR=$(grep "^$CHANNEL_ID=" ~/.claude/slack-cursors.conf 2>/dev/null | cut -d= -f2)
   ```

5. Fetch new messages since the cursor:
   ```bash
   curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
     "https://slack.com/api/conversations.history?channel=$CHANNEL_ID&oldest=$CURSOR&limit=20" \
     | jq '.messages[] | "\(.user // .bot_id): \(.text)"'
   ```
   If no cursor exists, fetch the last 10 messages.

6. **Resolve mentions to display names.** For each mention in the results:
   - `<@UXXXXX>` patterns are user mentions — use the `scc-slack:lookup` skill to resolve to `@display_name`
   - `<!here>`, `<!channel>`, `<!everyone>` are broadcast markers — replace with `@here`, `@channel`, `@everyone` (do NOT try to resolve these as users)
   - Replace the `.user` field (e.g., `U0AKE1L3YJ3`) with the display name
   - Present messages as `DisplayName: message text` not `U0AKE1L3YJ3: message text`

7. If messages were returned, store the newest timestamp as the new cursor:
   ```bash
   NEWEST=$(echo "$RESPONSE" | jq -r '.messages[0].ts')
   grep -v "^$CHANNEL_ID=" ~/.claude/slack-cursors.conf > /tmp/slack-cursors.tmp 2>/dev/null
   echo "$CHANNEL_ID=$NEWEST" >> /tmp/slack-cursors.tmp
   mv /tmp/slack-cursors.tmp ~/.claude/slack-cursors.conf
   ```

8. Update Slack's read marker:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
     -H "Content-type: application/json" \
     -d "{\"channel\":\"$CHANNEL_ID\",\"ts\":\"$NEWEST\"}" \
     https://slack.com/api/conversations.mark
   ```

9. If no new messages, say nothing. Do not report "no new messages" — stay completely silent.

## Acting on messages

You are an autonomous agent. These messages are directed at a shared channel where multiple agents and humans collaborate. Your job is to pick up work addressed to you and get it done.

### Know your identity

Before filtering messages, establish who you are:
```bash
curl -s -H "Authorization: Bearer $SLACK_TOKEN" https://slack.com/api/auth.test | jq -r '.user, .user_id'
```
This returns your bot username (e.g., `claude_slack_plugin`) and user ID (e.g., `U0AKE1L3YJ3`). Also fetch your display name and real name:
```bash
curl -s -H "Authorization: Bearer $SLACK_TOKEN" "https://slack.com/api/users.info?user=$YOUR_USER_ID" \
  | jq -r '.user.profile.display_name, .user.profile.real_name'
```
A message is addressed to you if it contains any of:
- `<@YOUR_USER_ID>` — a proper Slack mention
- Your bot username, display name, or real name (case-insensitive) — sometimes users type `@name` but Slack doesn't convert it to a proper mention
- A recognizable variation or nickname the humans in the channel use to refer to you

### Which messages are for you

Respond to messages that:
- **Mention you** — your user ID (`<@UXXXXX>`), bot username, or any recognizable name for you
- **Are a direct follow-up** to a conversation you're already participating in

**Broadcast messages (`@here`, `@channel`, `@everyone`)** require judgment — they are addressed to everyone present, but that doesn't mean every agent should respond. Read the message, understand what's being asked, and decide:
- **Respond** if the request is something you can help with, is relevant to your capabilities, or explicitly asks all agents to do something
- **Stay silent** if another agent is better suited, the request doesn't match your skills, or responding would just add noise (e.g., multiple agents all saying "got it")
- **Coordinate** — if the broadcast asks for a single volunteer (e.g., "can someone check the logs?"), react with `eyes` first. If no other agent has reacted after a few seconds, pick it up. Avoid duplicate work.

Ignore messages that:
- Are addressed to a **different agent** by name (e.g., if you're `z490` and the message says `@macini do X`)
- Are **general chatter** between humans with no action for you
- Are **system/join/leave messages** with no actionable content

When in doubt about whether a message is for you, err on the side of responding — a brief "Did you mean me?" via `scc-slack:send` is better than dropping a request.

### How to act

**Default to action, not questions.** When you receive a request:

1. **Just do it.** If you can complete the task with the tools and context available to you, do the work and reply with the result. Do not ask "should I go ahead?" or "would you like me to?" — the message is the instruction.

2. **Reply in Slack.** Use `scc-slack:send` to post your response to the same channel. Address the person who sent the message with `@their_name` so they get notified (e.g., `@christo here's what I found...`). The person who asked should see your answer where they asked, not buried in your terminal.

3. **Show your work.** When you complete a task, reply with what you did and the outcome. Keep it concise — a summary and key details, not a wall of text.

4. **Handle multi-step tasks end to end.** If someone asks you to "check the deploy and fix any issues," do both. Don't stop after checking and ask if they want you to fix it.

5. **React to acknowledge.** When you pick up a message, use `scc-slack:react` with `eyes` to signal you've seen it. When done, react with `white_check_mark`.

### When to escalate to the user

Involve your local user (the human at your terminal) only when:

- **You lack access** — the task requires credentials, permissions, or systems you can't reach
- **It's a judgment call** — the task involves a decision with significant consequences (deleting data, spending money, messaging external people) where the right choice isn't obvious
- **You're stuck** — you've tried and genuinely cannot make progress
- **It's ambiguous and high-stakes** — you're not sure what's being asked AND getting it wrong would be costly

Do NOT escalate for:
- Clarifying questions you could answer with a reasonable assumption (make the assumption, state it, and proceed)
- Tasks that seem hard but are within your capabilities
- Requests where the intent is clear even if the wording is vague
