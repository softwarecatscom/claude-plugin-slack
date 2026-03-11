---
name: setup
description: Install slack-cli and configure Slack credentials. Use when the user says "setup slack", "configure slack", "install slack", or before first use of any slack command.
---

# Slack Setup

Install dependencies, create a Slack app, and configure credentials for Slack messaging.

## Step 1: Check dependencies

Verify `curl` and `jq` are installed:
```bash
which curl 2>/dev/null && which jq 2>/dev/null
```
If either is missing, install them:
- **Debian/Ubuntu:** `sudo apt-get install -y curl jq`
- **macOS:** `brew install curl jq`

## Step 2: Install slack-cli

Check if `slack` CLI is already installed:
```bash
which slack 2>/dev/null && slack version
```
If not installed:
```bash
curl -O https://raw.githubusercontent.com/rockymadden/slack-cli/master/src/slack && chmod +x slack && sudo mv slack /usr/local/bin/
```

## Step 3: Create a Slack App (if needed)

If the user doesn't already have a bot token, walk them through this:

1. Go to https://api.slack.com/apps and click **Create New App** → **From scratch**
2. Name the app (e.g., `claude-agent`) and pick the workspace
3. Go to **OAuth & Permissions** → **Scopes** → **Bot Token Scopes** and add:
   - `chat:write` — send messages
   - `channels:read` — list channels
   - `channels:history` — read messages
   - `reactions:write` — add emoji reactions
   - `files:write` — upload files
   - `users.profile:write` — set status
4. Click **Install to Workspace** and authorize
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

## Step 4: Configure

Check if `~/.claude/slack.conf` already exists:
```bash
cat ~/.claude/slack.conf 2>/dev/null
```

If no config exists, ask the user for:
- **Bot token** (`xoxb-...`)
- **Default channel** (e.g., `general`)
- **Autonomous channels** (comma-separated list of channels to monitor in polling mode)

Write the config file:
```bash
cat > ~/.claude/slack.conf << 'CONF'
SLACK_TOKEN=<token>
DEFAULT_CHANNEL=<channel>
AUTONOMOUS_CHANNELS=<channels>
CONF
```

## Step 5: Initialize and verify

```bash
slack init --token <token>
slack channels list 2>&1 | head -5
```

If verification succeeds, confirm setup is complete. If it fails, show the error and help troubleshoot.

## Fallback

If `~/.claude/slack.conf` is missing but `$SLACK_TOKEN` is set in the environment, use that. Prompt the user to run `/slack:setup` for full configuration.
