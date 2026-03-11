---
name: setup
description: Install slack-cli and configure Slack credentials. Use when the user says "setup slack", "configure slack", "install slack", or before first use of any slack command.
---

# Slack Setup

Install dependencies, configure a Slack app, and verify connectivity.

## Step 1: Check dependencies

Verify `curl` and `jq` are installed:
```bash
which curl 2>/dev/null && which jq 2>/dev/null
```
If either is missing, install them:
- **Debian/Ubuntu:** `sudo apt-get install -y curl jq`
- **macOS:** `brew install curl jq`

## Step 2: Install slack-cli

The plugin ships with slack-cli vendored in `scripts/slack`. Find the plugin's installed copy and symlink it:

```bash
PLUGIN_SLACK=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack" 2>/dev/null | sort -V | tail -1)
```

If found, create the symlink:
```bash
mkdir -p ~/.local/bin
ln -sf "$PLUGIN_SLACK" ~/.local/bin/slack
```

**If `which slack` returns a path outside `~/.local/bin`** (e.g., `/usr/local/bin/slack`), warn the user that a system-installed copy exists and will shadow the vendored version. Remove or rename the system copy so `~/.local/bin/slack` takes precedence.

Verify it runs:
```bash
which slack 2>/dev/null && slack 2>&1 | head -1
```

Confirm the resolved path is `~/.local/bin/slack` (the vendored symlink), not a system copy.

If `~/.local/bin` is not on `$PATH`, tell the user to add it.

> **Note:** The CLI only covers chat, file, presence, reminder, snooze, and status commands. Other operations (listing channels, reading history, reactions, marking read) use the Slack API via curl. The token is shared — `slack init` stores it and curl reads it from the same file.

## Step 3: Create a Slack App (if needed)

Check if a token is already stored:
```bash
cat "$(dirname "$(which slack)")/.slack" 2>/dev/null
```

If no token exists, walk the user through creating one:

1. Go to https://api.slack.com/apps and click **Create New App** → **From scratch**
2. Name the app (e.g., `claude-agent`) and pick the workspace
3. Go to **OAuth & Permissions** → **Scopes** → **Bot Token Scopes** and add:
   - `chat:write` — send messages
   - `channels:read` — list public channels
   - `channels:history` — read messages
   - `groups:read` — list private channels (required — without this, API calls that request private channels fail entirely, even for public channel results)
   - `reactions:write` — add emoji reactions
   - `files:write` — upload files
   - `users:read` — resolve @mentions to user IDs
   - `users.profile:write` — set status
4. Click **Install to Workspace** and authorize
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

## Step 4: Initialize slack-cli

```bash
slack init --token <token>
```

This stores the token in a `.slack` file next to the binary. All skills (both CLI commands and curl calls) read from this file.

## Step 5: Configure plugin settings

Check if `~/.claude/slack.conf` already exists:
```bash
cat ~/.claude/slack.conf 2>/dev/null
```

If config exists but contains a `SLACK_TOKEN=` line, strip it — the token is managed by slack-cli, not the config file:
```bash
grep -v '^SLACK_TOKEN=' ~/.claude/slack.conf > /tmp/slack.conf.tmp && mv /tmp/slack.conf.tmp ~/.claude/slack.conf
```

If no config exists, ask the user for:
- **Default channel** (e.g., `general`)
- **Autonomous channels** (comma-separated list of channels to monitor in polling mode)

Write the config file (**no token** — that's managed by slack-cli):
```bash
cat > ~/.claude/slack.conf << 'CONF'
DEFAULT_CHANNEL=<channel>
AUTONOMOUS_CHANNELS=<channels>
CONF
```

## Step 6: Verify

Test connectivity with a curl call:
```bash
SLACK_TOKEN=$(cat "$(dirname "$(which slack)")/.slack")
curl -s -H "Authorization: Bearer $SLACK_TOKEN" https://slack.com/api/auth.test | jq '.ok, .team, .user'
```

If verification succeeds, confirm setup is complete. If it fails, show the error and help troubleshoot.
