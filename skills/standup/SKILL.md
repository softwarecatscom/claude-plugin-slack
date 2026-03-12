---
name: standup
description: Generate a status update or standup report. Use when the user says "standup", "status update", "give me a status", "what's the state", "session summary", or when posting a daily update to Slack.
---

# Standup / Status Update

Generate a structured status report by gathering context from git, Linear, and the current session. Supports two formats: a concise **standup** for team updates and a detailed **session status** for handoffs.

## Arguments

- `format` — `standup` (default) or `session`. Standup is the three-part Scrum update; session is a detailed snapshot.
- `post` — if `true`, post the result to the default Slack channel after displaying it. Defaults to `false`.

## Format: Standup

The classic daily standup from Scrum. Three sections:

### What I did
- Completed work since last update
- Gather from: `git log --oneline` (commits this session), Linear issues moved to Done, notable Slack conversations acted on

### What I plan to do
- Next priorities
- Gather from: Linear issues assigned to me in Backlog or In Progress, any pending requests from Slack

### Blockers
- Anything preventing progress
- Examples: waiting on credentials, machine offline, blocked by another agent's work, missing permissions
- If no blockers, say "None"

### Example output

```
**Standup — Rogue1**

**Done:**
- AGT-2: Word-boundary anchors for broadcast mentions (v0.10.4)
- AGT-3: Concrete size threshold in read skill (v0.10.5)

**Next:**
- Explore Linear skill for team workflow automation
- Follow up with F3 on Linear MCP access

**Blockers:**
- F3's machine offline — can't verify their plugin setup
```

## Format: Session

A detailed snapshot covering everything an agent (or human) needs to pick up where you left off.

Sections:

1. **This session** — bullet list of significant actions taken, in chronological order
2. **Current state** — branch, version, tag, uncommitted changes, running jobs (cron), Linear backlog status
3. **Pending** — items waiting on external input, deferred work, follow-ups needed
4. **Team** — last known status of each team member (online/offline, what they're working on, any outstanding requests to/from them)

## Steps

### Step 1: Gather context

Run these in parallel to collect data:

```bash
# Recent commits (this session — last ~2 hours or since session start)
git log --oneline --since="2 hours ago"

# Current branch and status
git status --short
git describe --tags --always
```

Check Linear for assigned issues:
- Use `list_issues` with team "Agents" to see backlog state
- Note which are In Progress, Done (recently), or Backlog

Review the conversation history for:
- Slack messages acted on
- Decisions made
- Errors encountered and resolved
- Pending requests

### Step 2: Format the report

Assemble the gathered data into the requested format (standup or session). Keep it concise — bullet points, not paragraphs.

### Step 3: Post (optional)

If `post` is `true`, send the formatted report to the default Slack channel:
```bash
"${SCRIPTS_DIR}/slack-send" "${CHANNEL}" "the formatted report"
```

Keep Slack posts compact. For session format, summarize rather than posting the full detail — link to Linear issues by identifier rather than repeating descriptions.

## When to use

- **Standup**: at the start or end of a session, when the team asks for updates, or on a recurring schedule
- **Session**: before going offline, at context compaction, or when handing off to another agent/session
