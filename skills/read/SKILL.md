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

**ALWAYS use the `scripts/slack-*` helpers for Slack operations.** Do NOT call the Slack API directly with curl. The scripts handle token loading, channel resolution, mention encoding (`@here` → `<!here>`, `@Name` → `<@USERID>`), and JSON payload construction correctly. Calling the API directly bypasses this and introduces bugs (e.g., Claude Code's Bash tool escapes `!` in `<!here>`, breaking broadcast mentions). If a script doesn't exist for what you need, add one — don't inline curl calls.

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

### Step 3: Poll for actionable messages

**ALWAYS use `slack-poll`** — never call `slack-fetch` or `slack-filter` directly. `slack-poll` handles channel resolution, cursor-based fetching, mention filtering, AND thread scanning in one call. Calling `slack-fetch` directly skips thread scanning, which means you miss thread replies entirely.

```bash
POLL_OUTPUT=$("${SCRIPTS_DIR}/slack-poll")
```

The output contains `# channel=NAME id=ID` headers followed by JSON arrays of filtered messages, plus `# thread=TS channel=ID` sections for threads you participate in. Parse each JSON array block for actionable messages.

Each message entry has `ts`, `user`, `text`, `match_type`, `bot_id`, and `thread_ts`. Match types include:
- `direct` — you were @mentioned
- `broadcast` — @here/@channel/@everyone
- `name_match` — your name appeared in the text
- `thread_participant` — new reply in a thread you're part of (not explicitly @mentioned, but you're a participant — treat as actionable)

**If all arrays are empty** (`[]`), stop. Say nothing — do not report "no new messages." The cursor was already auto-advanced by `slack-poll`.

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
- Is this a greeting that warrants a brief reply? This includes `@here` introductions from new agents (e.g., "Hi everyone, I'm F3" or "@here I just came online") — these are team intros, not noise, and deserve a welcome.
- For broadcasts: is this relevant to your capabilities, or is another agent better suited?

**d) Decide whether to respond.** For direct mentions with a real request: always respond. For broadcasts, apply judgment:
- **Respond** if the request matches your capabilities, explicitly asks all agents to do something, or is a team introduction/greeting (welcome new agents!)
- **Stay silent** if another agent already handled it, or responding would just add noise
- **Coordinate** — if the broadcast asks for a single volunteer, react with `eyes` first; if no other agent picks it up, do it
- **Never silently skip a broadcast** — if you decide not to respond, explicitly note your reasoning (e.g., "Z490 already handled this"). Dropping a broadcast without evaluation is a bug.

When in doubt about whether a message is for you, err on the side of responding — a brief reply is better than dropping a request.

**e) Do the work.** Default to action, not questions. Do not ask "should I go ahead?" — the message is the instruction.

There are three kinds of work:

- **Quick tasks** (answering a question, sharing info, simple lookups): do the work, then respond with the answer in step (f). One message covers it.

- **Real work** (editing files, implementing feedback, making code changes, multi-step tasks): follow the **acknowledge-do-report** pattern:
  1. **Acknowledge** — react with `eyes` and send a brief reply: "Good feedback, on it" or "Working on that now". For sub-minute real work, skip the acknowledge and go straight to do-report — an `eyes` that arrives after the `white_check_mark` is confusing.
  2. **Do the work** — make the edits, run tests, fix issues. Do this now, in this cycle, before moving to the next message. Do not defer it.
  3. **Report back** — send a follow-up message with results: "Done — updated X and Y". React with `white_check_mark` when complete. If something fails partway through, report what was done and what failed — don't silently rollback. Example: "Updated X but hit an error on Y — [details]. Want me to retry or revert?"

  **Size check**: if the work touches more than 3 files, requires a test suite run, involves architectural decisions, or needs multiple sequential steps that could each fail — acknowledge with a scope estimate ("This is a bigger change — I'll need a few cycles") and check with your local user before starting. This prevents runaway edits. When in doubt, start the work and escalate if it grows beyond what you expected.

- **Blocked work** (the task requires information you don't have — credentials, config values, design decisions): follow the **acknowledge-ask-do-report** pattern:
  1. **Acknowledge** — react with `eyes`, confirm you understand the request
  2. **Ask** — reply stating what you need to proceed: "I can update the deploy config, but I need the new values — can you share them?"
  3. **Do the work** — once unblocked, follow steps 2-3 of real work above
  4. **Report back** — same as real work

- **Deferred work** (valid work that can't be done right now — non-blocking review feedback, improvement ideas, future enhancements noted in conversation): follow the **acknowledge-track** pattern:
  1. **Acknowledge** — reply in Slack confirming you've captured the item: "Good idea, tracking that for a future release"
  2. **Track** — create a Linear issue in the **Agents** team using the Linear MCP tool (`save_issue`). Include:
     - A clear title describing the work
     - Description with context: who raised it, why, and any relevant details (file paths, code snippets, links)
     - Priority: `4` (Low) for nice-to-haves, `3` (Normal) for real gaps, `2` (High) if it affects correctness
  3. **Mention the issue** — include the Linear issue identifier (e.g., AGT-42) in your Slack reply so the requester can find it

  This applies when: review feedback is marked "not a blocker" or "future pass", someone suggests an improvement you agree with but can't action now, or you discover a gap while doing other work. The goal is zero dropped items — if it's worth mentioning, it's worth tracking.

**Conflicting requests**: if multiple messages in the same batch ask for contradictory changes, process them chronologically and flag the conflict in your reply to the later requester: "Heads up — @Alice just asked for X which conflicts with this. Processing hers first since it came in earlier. Want to coordinate?"

**f) Honor your commitments before moving on.** If any reply you are about to send (or just sent) contains a commitment — "will RFC", "going to send", "I'll update", "plan to ask" — **execute that action now**, before processing the next message. Creating a ticket that says "RFC later" is not the same as sending the RFC. Writing "I'll update the skill" is not the same as updating the skill. The artifact that *describes* future work is not the work itself. If you cannot execute the commitment immediately, create a tracked task via `TaskCreate` so it is not lost. Do not advance the cursor until all commitments from this message batch are resolved.

**g) Respond.** Always respond **in the same context** where the message was received — same channel, and same thread if applicable. Never open a DM unless the sender explicitly asks for one — DMs fragment conversations and hide context from other agents and humans.

**For channel-level messages** (thread_ts is null):
```bash
"${SCRIPTS_DIR}/slack-send" "${CHANNEL}" "@SenderName your response here"
```

**For thread messages** (thread_ts is set — including thread_participant matches):
```bash
"${SCRIPTS_DIR}/slack-send" --thread "${THREAD_TS}" "${CHANNEL}" "@SenderName your response here"
```
Reply in the thread, not the channel. This keeps threaded conversations contained. Only use `--broadcast` if the response is important enough for the whole channel to see.

The script auto-resolves `@Name` to proper Slack mentions using the resolve cache. When you need to look up who's in the conversation, resolve users from the channel context — the people you're talking to are the people in that channel.

Keep responses concise — summary and key details, not a wall of text.

**h) Scan for commitments.** After sending a reply, re-read the text you just sent and identify any commitments — statements where you promised to do something in the future. Use your judgment to detect the **intent**, not just specific phrases. Examples of commitment language include "I'll update", "will RFC", "going to send", "plan to investigate", "let me create" — but any statement that a reasonable reader would interpret as "this agent is going to do X" counts.

For **each** detected commitment:
1. **Can you execute it right now?** Do it immediately — send the RFC, update the file, create the issue, whatever you promised. Then continue.
2. **Cannot execute now?** Create a tracked task via `TaskCreate` with the commitment text and context (who you promised, in which channel, what message). This ensures it is not lost.

Do **not** advance to the next message until all detected commitments are resolved (executed or tracked). This is the automated enforcement of step (f) — it catches commitments that slip through.

**i) Move to the next message.**

### Done

The cursor is auto-advanced by `slack-poll` (step 3) — you do NOT need to update it manually. `slack-poll` writes the newest fetched message timestamp to the cursor immediately after a successful API call. This prevents the race condition where agents accidentally advance the cursor to their reply's timestamp, skipping messages that arrived between fetch and reply.

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
