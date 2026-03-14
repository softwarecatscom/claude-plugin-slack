---
name: announce
description: Announce a new plugin release to the team via Slack. Use when the user says "announce", "announce release", "tell the team about the release", or after tagging and pushing a new version.
---

# Announce Release

Post a release announcement to the team in Slack after tagging and pushing a new version.

## Arguments

- `version` — version to announce (optional, defaults to latest git tag)
- `channel` — channel to post in (optional, defaults to `DEFAULT_CHANNEL` from config)

## Scripts

Locate the plugin scripts once per session:
```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

## Steps

**Prefer `ctx_execute` over Bash** when running commands that produce output. This keeps raw output in the sandbox and protects your context window.

### Step 1: Determine version and changelog

Get the latest tag and the commits since the previous tag (via `ctx_execute`):

```bash
# Latest tag (or use provided version)
LATEST_TAG=$(git describe --tags --abbrev=0)
# Previous tag
PREV_TAG=$(git describe --tags --abbrev=0 "${LATEST_TAG}^")
# Commits between tags
CHANGELOG=$(git log --oneline "${PREV_TAG}..${LATEST_TAG}")
```

### Step 2: Classify changes

Review the commits and categorize:

- **New features** — new skills, commands, or capabilities
- **Improvements** — enhancements to existing functionality
- **Fixes** — bug fixes
- **Breaking changes** — anything that changes existing behavior in a way that could affect agents

### Step 3: Compose the announcement

Format a concise Slack message:

```
@here scc-slack v[VERSION] released

[One-line summary of the release theme]

**New:**
- [feature 1]
- [feature 2]

**Improved:**
- [improvement 1]

**Fixed:**
- [fix 1]

**Breaking:** [only if applicable]
- [breaking change]

Update with: /scc-slack:update
```

Keep it scannable. One line per change. No commit hashes — the team doesn't need them.

If there are no breaking changes, omit that section entirely.

### Step 4: Post to Slack

```bash
"${SCRIPTS_DIR}/slack-send" "${CHANNEL}" "the announcement"
```

### Step 5: Update Linear (optional)

If the release closes Linear issues, they should already be marked Done. If any were missed, update them now.

## When to use

- After bumping version, committing, tagging, and pushing
- When batching multiple changes into a single release announcement
- When the user says "announce" or "tell the team"

## Tips

- Batch announcements when doing multiple quick releases — announcing v0.10.4, v0.10.5, and v0.11.0 separately is noise. Wait until a logical stopping point.
- If the release only has internal changes (no user-facing impact), skip the announcement.
- Tag breaking changes clearly — agents running the old version need to know what will change when they update.
