# Slack Plugin for Claude Code — Design Spec

## Overview

A Claude Code plugin for Slack messaging, mirroring the architecture of `claude-plugin-mail`. Uses `rockymadden/slack-cli` as the underlying tool, with a setup skill that handles installation and configuration. The agent operates autonomously on configured channels.

## Plugin Structure

```
claude-plugin-slack/
├── .claude-plugin/plugin.json
├── .claude/settings.local.json
├── README.md
├── commands/
│   ├── setup.md          # /slack:setup
│   ├── send.md           # /slack:send <channel> <message>
│   ├── read.md           # /slack:read [channel]
│   ├── channels.md       # /slack:channels
│   ├── react.md          # /slack:react <emoji>
│   ├── upload.md         # /slack:upload <file> [channel]
│   ├── status.md         # /slack:status <text> [emoji]
│   ├── loop.md           # /slack:loop [channel]
│   ├── stop.md           # /slack:stop
│   └── tidy.md           # /slack:tidy
└── skills/
    ├── slack-setup/SKILL.md
    ├── slack-send/SKILL.md
    ├── slack-read/SKILL.md
    ├── slack-channels/SKILL.md
    ├── slack-react/SKILL.md
    ├── slack-upload/SKILL.md
    ├── slack-status/SKILL.md
    ├── slack-loop/SKILL.md
    ├── slack-stop/SKILL.md
    └── slack-tidy/SKILL.md
```

## Configuration

### Token & Preferences (`~/.claude/slack.conf`)

```ini
SLACK_TOKEN=xoxb-your-bot-token
DEFAULT_CHANNEL=general
AUTONOMOUS_CHANNELS=general,alerts,deploys
```

### Cursor State (`~/.claude/slack-cursors.conf`)

```ini
# channel_id=last_message_timestamp
C01ABC123=1710000000.000100
C02DEF456=1710000000.000200
```

### Fallback Chain

`~/.claude/slack.conf` → `$SLACK_TOKEN` env var

## Setup Skill (`slack:setup`)

1. Check if `slack` CLI (`rockymadden/slack-cli`) is installed
2. If not, install via curl one-liner to `/usr/local/bin/`
3. Prompt user for bot token
4. Write `~/.claude/slack.conf`
5. Run `slack init` to configure the CLI tool
6. Verify connectivity with a test message to default channel

## Skills Behavior

### Send (`slack:send`)

- Args: `<channel> <message>` (channel can be name or ID)
- Uses `slack chat send --text "<message>" --channel "<channel>"`
- Falls back to `DEFAULT_CHANNEL` if no channel specified
- Supports piping context from conversation

### Read (`slack:read`)

- Args: `[channel]` (optional, defaults to `DEFAULT_CHANNEL`)
- Fetches messages newer than stored cursor via `conversations.history?oldest=<timestamp>`
- Updates both local cursor file and Slack's mark API (`conversations.mark`)
- Processes messages autonomously: responds, takes action, or escalates to user

### Channels (`slack:channels`)

- Lists channels the bot is in via `slack channels list`
- Shows name, ID, member count, purpose

### React (`slack:react`)

- Args: `<emoji>` — reacts to the most recently read message
- Tracks last-read message timestamp for targeting
- Uses `slack reactions add`

### Upload (`slack:upload`)

- Args: `<file> [channel]`
- Uses `slack file upload --file "<file>" --channels "<channel>"`

### Status (`slack:status`)

- Args: `<text> [emoji]`
- Uses `slack presence set` / `slack status edit`
- Emoji defaults to `:speech_balloon:` if not provided

### Loop (`slack:loop`)

- Uses `CronCreate` with `/loop 1m` like mail-loop
- Polls channels listed in `AUTONOMOUS_CHANNELS`
- Silent when no new messages
- Triggers `slack-read` when messages found
- Autonomous: reads and acts on messages without asking user

### Stop (`slack:stop`)

- Uses `CronList` + `CronDelete` to remove the polling job

### Tidy (`slack:tidy`)

- Resets cursor state for channels (clears `slack-cursors.conf`)
- Optionally marks all channels as read via the mark API

## Permissions (`.claude/settings.local.json`)

```json
{
  "permissions": {
    "allow": [
      "Bash(slack *)",
      "Bash(curl -s -H * https://slack.com/api/*)",
      "Bash(cat ~/.claude/slack.conf)",
      "Bash(cat ~/.claude/slack-cursors.conf)"
    ]
  }
}
```

## Dependencies

- `rockymadden/slack-cli` (installed by `slack:setup`)
- `curl` + `jq` (for mark API and polling where slack-cli falls short)
- Slack Bot token with scopes: `chat:write`, `channels:read`, `channels:history`, `reactions:write`, `files:write`, `users.profile:write`

## Auth Mechanism

Bot/User API token (xoxb/xoxp) — requires creating a Slack app in the workspace. Full API access for all operations.

## Autonomous Behavior

When polling finds new messages, the agent reads and responds/acts on them without asking the user, matching the mail plugin's autonomous pattern. All channels in `AUTONOMOUS_CHANNELS` are monitored.
