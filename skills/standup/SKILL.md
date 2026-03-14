---
name: standup
description: Generate a status update or standup report. Use when the user says "standup", "status update", "give me a status", "what's the state", "session summary", or when posting a daily update to Slack.
---

# Standup / Status Update

Generate a full status report by gathering context from git, Linear, Slack, and the current session. Every standup includes both the Scrum update and session state — no separate formats.

## Scripts

Locate the plugin scripts once per session:
```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

## Arguments

- `post` — post the result to the default Slack channel after displaying it. Defaults to `true`. Pass `false` for local-only output.

## Sections

Every standup includes all of the following:

### Session
- Chronological narrative of significant actions taken in the current conversation
- What happened, what decisions were made, what problems were hit and resolved
- This is the story of the session — not a list of deliverables, but the flow of work
- Gather from: conversation history, Slack interactions, decisions, errors encountered

### Done
- Completed work since last update
- Gather from: `git log --oneline` (commits this session), Linear issues moved to Done, notable Slack conversations acted on

### Next
- Next priorities
- Gather from: Linear issues assigned to me in Backlog or In Progress, any pending requests from Slack

### Blockers
- Anything preventing progress
- Examples: waiting on credentials, machine offline, blocked by another agent's work, missing permissions
- If no blockers, say "None"

### Current state
- Branch, version/tag, uncommitted changes
- Running jobs (cron IDs, polling status)
- Linear backlog status (how many issues in each state)

### Tracked tasks (todos)
- Active tasks created via `TaskCreate` during this session
- Gather from: `TaskList` — include task ID, description, and status (in_progress, pending, completed)
- If no tracked tasks exist, say "None"

### Pending
- Items waiting on external input
- Deferred work, follow-ups needed

### Team
- Last known status of each team member (online/offline, what they're working on)
- Any outstanding requests to/from them

### Example output

```
**Standup — Rogue1**

**Session:**
- Started by RFC'ing the autonomous react skill to #agents
- Z490 responded: +1 with blocklist, single-message-per-invocation, dedup check
- Macini responded: +1 with confidence threshold suggestion
- Closed RFC with consensus, implemented all feedback into skills/react/SKILL.md
- Released v0.11.3 (react) and v0.11.4 (/release command)
- Announced both releases to Slack
- Reflected on standup skill — merged session format into default, changed post default to true

**Done:**
- AGT-6: Announce skill for release notifications (v0.11.2)
- Autonomous react skill — RFC'd, consensus, implemented (v0.11.3)
- /release command with auto-announce (v0.11.4)

**Next:**
- Follow up with F3 on Linear MCP access
- Identify new AGT backlog items

**Blockers:** None

**State:** master @ v0.11.4, clean working tree, Slack polling active (job 489f843a)

**Tracked tasks:** None

**Pending:**
- F3 Linear MCP access confirmation

**Team:**
- Z490: online, reviewed react RFC (+1)
- Macini: online, reviewed react RFC (+1), confirmed v0.11.2 update
- F3: offline since last session
```

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

Check tracked tasks:
- Use `TaskList` to get all tasks created in this session
- Include any that are in_progress or pending (not yet completed)

Review the conversation history for:
- Slack messages acted on
- Decisions made
- Errors encountered and resolved
- Pending requests
- Team member interactions and their last known status

### Step 2: Format the report

Assemble the gathered data into all eight sections. **Session** comes first. Keep it concise — bullet points, not paragraphs. The **State** section is a single line. **Pending** and **Team** can be omitted if truly empty.

### Step 3: Post (default)

Send the formatted report to the default Slack channel (unless `post` is `false`):
```bash
"${SCRIPTS_DIR}/slack-send" "${CHANNEL}" "the formatted report"
```

Keep Slack posts compact — link to Linear issues by identifier rather than repeating descriptions.

## When to use

- At the start or end of a session
- When the team or user asks for updates, status, or a standup
- On a recurring schedule
- Before going offline or at context compaction (for handoff context)
