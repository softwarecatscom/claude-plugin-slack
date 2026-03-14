---
name: setup
description: Install slack-cli and configure Slack credentials. Use when the user says "setup slack", "configure slack", "install slack", or before first use of any slack command.
---

# Slack Setup

Install dependencies, configure a Slack app, and verify connectivity.

## Scripts

Locate the plugin scripts once per session:
```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

**Prefer `ctx_execute` over Bash** when running scripts that produce output. This keeps raw output in the sandbox and protects your context window. Use Bash only for the `SCRIPTS_DIR` setup above and file mutation commands (`mkdir`, `cp`, `cat >`).

## Step 1: Check dependencies

Verify `curl` and `jq` are installed (via `ctx_execute`):
```bash
"${SCRIPTS_DIR}/slack-setup-verify" --deps
```
If either is missing, install them:
- **Debian/Ubuntu:** `sudo apt-get install -y curl jq`
- **macOS:** `brew install curl jq`

## Step 2: Install slack-cli shim

The plugin ships with a shim script (`scripts/slack-shim`) that loads the token and delegates to the latest vendored slack-cli. Find and install it in a single step:

```bash
PLUGIN_SHIM=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-shim" 2>/dev/null | sort -V | tail -1)
```

If `PLUGIN_SHIM` is empty, the plugin is not installed. Tell the user.

Otherwise, install it:
```bash
mkdir -p ~/.local/bin
cp "$PLUGIN_SHIM" ~/.local/bin/slack
chmod +x ~/.local/bin/slack
```

The `cp` overwrites any existing file (including stale symlinks).

**If `which slack` returns a path outside `~/.local/bin`** (e.g., `/usr/local/bin/slack`), warn the user that a system-installed copy exists and will shadow the shim. Remove or rename the system copy so `~/.local/bin/slack` takes precedence.

Verify the installed shim is correct (via `ctx_execute`):
```bash
"${SCRIPTS_DIR}/slack-setup-verify" --shim
```

The output must say "verified". If it warns about a non-shim file or wrong path, help the user resolve it.

If `~/.local/bin` is not on `$PATH`, tell the user to add it.

> **Note:** The shim reads `.slack` from its own directory (`~/.local/bin/.slack`), finds the latest vendored `scripts/slack` in the plugin cache, and delegates all commands. The `init` command is intercepted by the shim to write the token next to itself. Other operations (listing channels, reading history, reactions, marking read) use the Slack API via curl. The token is shared — `slack init` stores it and curl reads it from `~/.local/bin/.slack`.

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
   - `channels:mark` — mark channels as read (optional — polling works without it)
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
"${SCRIPTS_DIR}/slack-config-strip" SLACK_TOKEN
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

Test API connectivity (via `ctx_execute`):
```bash
"${SCRIPTS_DIR}/slack-setup-verify" --auth
```

If verification succeeds, confirm setup is complete. If it fails, show the error and help troubleshoot.
