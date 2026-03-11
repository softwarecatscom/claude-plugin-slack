# scc-slack

Slack messaging plugin for Claude Code agents via [rockymadden/slack-cli](https://github.com/rockymadden/slack-cli).

## Skills

- `scc-slack:setup` — Install slack-cli and configure credentials
- `scc-slack:send` — Send a message to a channel or DM
- `scc-slack:read` — Read new messages from a channel
- `scc-slack:channels` — List available channels
- `scc-slack:react` — React to a message with an emoji
- `scc-slack:upload` — Upload a file to a channel
- `scc-slack:status` — Set Slack status text and emoji
- `scc-slack:loop` — Start a 1-minute polling cycle for channels
- `scc-slack:stop` — Stop the polling loop
- `scc-slack:tidy` — Reset cursor state and mark channels as read

## Commands

| Command | Description |
|---------|-------------|
| `/scc-slack:setup` | Install and configure Slack integration |
| `/scc-slack:send <channel> <message>` | Send a message |
| `/scc-slack:read [channel]` | Read new messages |
| `/scc-slack:channels` | List channels |
| `/scc-slack:react <emoji>` | React to last read message |
| `/scc-slack:upload <file> [channel]` | Upload a file |
| `/scc-slack:status <text> [emoji]` | Set status |
| `/scc-slack:loop` | Start polling |
| `/scc-slack:stop` | Stop polling |
| `/scc-slack:tidy` | Reset tracking state |

## Prerequisites

- [rockymadden/slack-cli](https://github.com/rockymadden/slack-cli) (installed by `/scc-slack:setup`)
- `curl` + `jq`
- A Slack Bot token (`xoxb-...`) with scopes: `chat:write`, `channels:read`, `channels:history`, `reactions:write`, `files:write`, `users.profile:write`
- Optional: `groups:read` scope for private channel access

## Setup

Run `/scc-slack:setup` to install dependencies and configure your token.

## Configuration

The bot token is managed by slack-cli (`slack init` stores it next to the binary).

Plugin-specific config is stored in `~/.claude/slack.conf`:

```ini
DEFAULT_CHANNEL=general
AUTONOMOUS_CHANNELS=general,alerts,deploys
```

## How it works

The plugin uses two mechanisms depending on the operation:

| Mechanism | Operations |
|-----------|-----------|
| **slack-cli** (token automatic) | `chat send`, `chat delete`, `file upload`, `status edit` |
| **curl + Slack API** (token from `.slack` file) | `conversations.list`, `conversations.history`, `reactions.add`, `conversations.mark` |
