---
name: setup
description: Install slack-cli and configure Slack credentials. Use when the user says "setup slack", "configure slack", "install slack", or before first use of any slack command.
---

# Slack Setup

Install `rockymadden/slack-cli` and configure credentials for Slack messaging.

## Steps

1. Check if `slack` CLI is already installed:
   ```bash
   which slack 2>/dev/null && slack version
   ```

2. If not installed, install it:
   ```bash
   curl -O https://raw.githubusercontent.com/rockymadden/slack-cli/master/src/slack && chmod +x slack && sudo mv slack /usr/local/bin/
   ```

3. Check if `~/.claude/slack.conf` already exists:
   ```bash
   cat ~/.claude/slack.conf 2>/dev/null
   ```

4. If no config exists, ask the user for:
   - **Bot token** (starts with `xoxb-`)
   - **Default channel** (e.g., `general`)
   - **Autonomous channels** (comma-separated list of channels to monitor)

5. Write the config file:
   ```bash
   cat > ~/.claude/slack.conf << 'CONF'
   SLACK_TOKEN=<token>
   DEFAULT_CHANNEL=<channel>
   AUTONOMOUS_CHANNELS=<channels>
   CONF
   ```

6. Initialize slack-cli with the token:
   ```bash
   slack init --token <token>
   ```

7. Verify connectivity:
   ```bash
   slack channels list 2>&1 | head -5
   ```

8. If verification succeeds, confirm setup is complete. If it fails, show the error and help the user troubleshoot.

## Fallback

If `~/.claude/slack.conf` is missing but `$SLACK_TOKEN` is set in the environment, use that. Prompt the user to run `/slack:setup` for full configuration.
