# claude-plugin-slack

Slack messaging plugin for Claude Code agents via [rockymadden/slack-cli](https://github.com/rockymadden/slack-cli).

## Skills

- `slack:setup` — Install slack-cli and configure credentials
- `slack:send` — Send a message to a channel or DM
- `slack:read` — Read new messages from a channel
- `slack:channels` — List available channels
- `slack:react` — React to a message with an emoji
- `slack:upload` — Upload a file to a channel
- `slack:status` — Set Slack status text and emoji
- `slack:loop` — Start a 1-minute polling cycle for channels
- `slack:stop` — Stop the polling loop
- `slack:tidy` — Reset cursor state and mark channels as read

## Commands

| Command | Description |
|---------|-------------|
| `/slack:setup` | Install and configure Slack integration |
| `/slack:send <channel> <message>` | Send a message |
| `/slack:read [channel]` | Read new messages |
| `/slack:channels` | List channels |
| `/slack:react <emoji>` | React to last read message |
| `/slack:upload <file> [channel]` | Upload a file |
| `/slack:status <text> [emoji]` | Set status |
| `/slack:loop` | Start polling |
| `/slack:stop` | Stop polling |
| `/slack:tidy` | Reset tracking state |

## Prerequisites

- [rockymadden/slack-cli](https://github.com/rockymadden/slack-cli) (installed by `/slack:setup`)
- `curl` + `jq`
- A Slack Bot token (`xoxb-...`) with scopes: `chat:write`, `channels:read`, `channels:history`, `reactions:write`, `files:write`, `users.profile:write`

## Setup

Run `/slack:setup` to install dependencies and configure your token.

## Configuration

Config is stored in `~/.claude/slack.conf`:

```ini
SLACK_TOKEN=xoxb-your-bot-token
DEFAULT_CHANNEL=general
AUTONOMOUS_CHANNELS=general,alerts,deploys
```

Falls back to `$SLACK_TOKEN` environment variable if config file is missing.
