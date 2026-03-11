# Slack Plugin Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a Claude Code plugin for Slack messaging with 10 skills (setup, send, read, channels, react, upload, status, loop, stop, tidy) using `rockymadden/slack-cli`.

**Architecture:** Claude Code plugin following the same command-delegates-to-skill pattern as `claude-plugin-mail`. Commands are thin frontmatter+delegation files in `commands/`. Skills contain full implementation logic in `skills/<name>/SKILL.md`. Config stored in `~/.claude/slack.conf`, cursor state in `~/.claude/slack-cursors.conf`.

**Tech Stack:** `rockymadden/slack-cli` (bash, curl, jq), Slack Web API, Claude Code plugin system (commands, skills, CronCreate/CronDelete).

**Spec:** `docs/superpowers/specs/2026-03-10-slack-plugin-design.md`

---

## Chunk 1: Scaffold & Foundation

### Task 1: Plugin manifest and permissions

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.claude/settings.local.json`

- [x] **Step 1: Create plugin.json**

```json
{
  "name": "slack",
  "version": "0.1.0",
  "description": "Slack messaging plugin for Claude Code agents via rockymadden/slack-cli",
  "author": {
    "name": "SoftwareCats",
    "url": "https://github.com/softwarecatscom"
  }
}
```

- [x] **Step 2: Create settings.local.json**

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

- [x] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json .claude/settings.local.json
git commit -m "feat: add plugin manifest and permissions"
```

### Task 2: Setup command and skill

**Files:**
- Create: `commands/setup.md`
- Create: `skills/slack-setup/SKILL.md`

- [x] **Step 1: Create the setup command**

File: `commands/setup.md`
```markdown
---
name: setup
description: Install slack-cli and configure Slack credentials
---

Use the `slack-setup` skill to set up Slack integration.
```

- [x] **Step 2: Create the setup skill**

File: `skills/slack-setup/SKILL.md`
```markdown
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
```

- [x] **Step 3: Commit**

```bash
git add commands/setup.md skills/slack-setup/SKILL.md
git commit -m "feat: add slack:setup command and skill"
```

### Task 3: Send command and skill

**Files:**
- Create: `commands/send.md`
- Create: `skills/slack-send/SKILL.md`

- [x] **Step 1: Create the send command**

File: `commands/send.md`
```markdown
---
name: send
description: Send a Slack message to a channel or DM
args: "<channel> <message>"
---

Use the `slack-send` skill to send the message. Pass through all arguments.
```

- [x] **Step 2: Create the send skill**

File: `skills/slack-send/SKILL.md`
```markdown
---
name: send
description: Send a Slack message to a channel or DM. Use when the user says "send slack", "slack message", "post to slack", or wants to send a message to a Slack channel.
---

# Send Slack Message

Send a message to a Slack channel or DM.

## Arguments

- `channel` — channel name or ID (e.g., `general`, `C01ABC123`). Falls back to `DEFAULT_CHANNEL` from config.
- `message` — the message text to send

## Steps

1. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```
   If config is missing and `$SLACK_TOKEN` is not set, tell the user to run `/slack:setup` first.

2. If you already have the channel and message from conversation context (e.g., replying to a read message), send directly — skip to step 4.

3. Otherwise, ask the user for any missing fields (channel, message).

4. Send the message:
   ```bash
   slack chat send --text "<message>" --channel "<channel>"
   ```

5. Confirm delivery with the channel name.
```

- [x] **Step 3: Commit**

```bash
git add commands/send.md skills/slack-send/SKILL.md
git commit -m "feat: add slack:send command and skill"
```

### Task 4: Read command and skill

**Files:**
- Create: `commands/read.md`
- Create: `skills/slack-read/SKILL.md`

- [x] **Step 1: Create the read command**

File: `commands/read.md`
```markdown
---
name: read
description: Read new Slack messages from a channel
args: "[channel]"
---

Use the `slack-read` skill to read messages. Pass through all arguments.
```

- [x] **Step 2: Create the read skill**

File: `skills/slack-read/SKILL.md`
```markdown
---
name: read
description: Read new Slack messages from a channel. Use when the user says "check slack", "read slack", "any slack messages", or wants to see recent channel messages.
---

# Read Slack Messages

Read new messages from a Slack channel. **These messages are for you, the agent.** Read them, understand them, and act on them autonomously. Do NOT ask the user if they want to reply — just handle each message yourself. Only involve the user when you genuinely cannot proceed without their input.

## Arguments

- `channel` — channel name or ID (optional, defaults to `DEFAULT_CHANNEL` from config)

## Steps

1. Load config and cursor state:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```

2. Determine the channel. If none specified, use `$DEFAULT_CHANNEL`.

3. Get the channel ID (needed for API calls):
   ```bash
   CHANNEL_ID=$(slack channels list 2>/dev/null | grep "<channel>" | awk '{print $1}')
   ```

4. Read the last cursor timestamp for this channel:
   ```bash
   CURSOR=$(grep "^$CHANNEL_ID=" ~/.claude/slack-cursors.conf 2>/dev/null | cut -d= -f2)
   ```

5. Fetch new messages since the cursor:
   ```bash
   curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
     "https://slack.com/api/conversations.history?channel=$CHANNEL_ID&oldest=$CURSOR&limit=20" | jq '.messages[] | "\(.user // .bot_id): \(.text)"'
   ```
   If no cursor exists, fetch the last 10 messages.

6. If messages were returned, store the newest timestamp as the new cursor:
   ```bash
   NEWEST=$(curl -s -H "Authorization: Bearer $SLACK_TOKEN" \
     "https://slack.com/api/conversations.history?channel=$CHANNEL_ID&oldest=$CURSOR&limit=20" | jq -r '.messages[0].ts')
   grep -v "^$CHANNEL_ID=" ~/.claude/slack-cursors.conf > /tmp/slack-cursors.tmp 2>/dev/null
   echo "$CHANNEL_ID=$NEWEST" >> /tmp/slack-cursors.tmp
   mv /tmp/slack-cursors.tmp ~/.claude/slack-cursors.conf
   ```

7. Update Slack's read marker:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
     -H "Content-type: application/json" \
     -d "{\"channel\":\"$CHANNEL_ID\",\"ts\":\"$NEWEST\"}" \
     https://slack.com/api/conversations.mark
   ```

8. **Act on each message:**
   - If it's a question you can answer, reply via slack-send
   - If it requires action (run a command, check something), do it and reply with the result
   - If it's informational, acknowledge it
   - If you need the user's input to proceed, summarize the message and ask them

9. If no new messages, say nothing (stay quiet to avoid noise).
```

- [x] **Step 3: Commit**

```bash
git add commands/read.md skills/slack-read/SKILL.md
git commit -m "feat: add slack:read command and skill"
```

## Chunk 2: Channel, React, Upload, Status Skills

### Task 5: Channels command and skill

**Files:**
- Create: `commands/channels.md`
- Create: `skills/slack-channels/SKILL.md`

- [x] **Step 1: Create the channels command**

File: `commands/channels.md`
```markdown
---
name: channels
description: List Slack channels the bot has access to
---

Use the `slack-channels` skill to list channels.
```

- [x] **Step 2: Create the channels skill**

File: `skills/slack-channels/SKILL.md`
```markdown
---
name: channels
description: List Slack channels the bot has access to. Use when the user says "list channels", "slack channels", "what channels", or wants to see available Slack channels.
---

# List Slack Channels

List all channels the bot is a member of.

## Steps

1. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```
   If config is missing and `$SLACK_TOKEN` is not set, tell the user to run `/slack:setup` first.

2. List channels:
   ```bash
   slack channels list
   ```

3. Present the results showing: channel name, ID, member count, and purpose/topic.

4. Note which channels are in `AUTONOMOUS_CHANNELS` (from config) for the user's reference.
```

- [x] **Step 3: Commit**

```bash
git add commands/channels.md skills/slack-channels/SKILL.md
git commit -m "feat: add slack:channels command and skill"
```

### Task 6: React command and skill

**Files:**
- Create: `commands/react.md`
- Create: `skills/slack-react/SKILL.md`

- [x] **Step 1: Create the react command**

File: `commands/react.md`
```markdown
---
name: react
description: React to the last read Slack message with an emoji
args: "<emoji>"
---

Use the `slack-react` skill to add the reaction. Pass through all arguments.
```

- [x] **Step 2: Create the react skill**

File: `skills/slack-react/SKILL.md`
```markdown
---
name: react
description: React to a Slack message with an emoji. Use when the user says "react", "add emoji", "thumbs up that", or wants to add a reaction to a message.
---

# React to Slack Message

Add an emoji reaction to the most recently read message.

## Arguments

- `emoji` — emoji name without colons (e.g., `thumbsup`, `eyes`, `white_check_mark`)

## Steps

1. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```

2. Get the last-read message timestamp and channel from `~/.claude/slack-cursors.conf`. The most recently updated entry is the target.

3. Add the reaction:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
     -H "Content-type: application/json" \
     -d "{\"channel\":\"$CHANNEL_ID\",\"timestamp\":\"$MESSAGE_TS\",\"name\":\"$EMOJI\"}" \
     https://slack.com/api/reactions.add
   ```

4. Confirm the reaction was added.
```

- [x] **Step 3: Commit**

```bash
git add commands/react.md skills/slack-react/SKILL.md
git commit -m "feat: add slack:react command and skill"
```

### Task 7: Upload command and skill

**Files:**
- Create: `commands/upload.md`
- Create: `skills/slack-upload/SKILL.md`

- [x] **Step 1: Create the upload command**

File: `commands/upload.md`
```markdown
---
name: upload
description: Upload a file to a Slack channel
args: "<file> [channel]"
---

Use the `slack-upload` skill to upload the file. Pass through all arguments.
```

- [x] **Step 2: Create the upload skill**

File: `skills/slack-upload/SKILL.md`
```markdown
---
name: upload
description: Upload a file or snippet to a Slack channel. Use when the user says "upload to slack", "share file on slack", "post file", or wants to upload a file to Slack.
---

# Upload File to Slack

Upload a file or code snippet to a Slack channel.

## Arguments

- `file` — path to the file to upload
- `channel` — channel name or ID (optional, defaults to `DEFAULT_CHANNEL` from config)

## Steps

1. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```
   If config is missing and `$SLACK_TOKEN` is not set, tell the user to run `/slack:setup` first.

2. Verify the file exists:
   ```bash
   ls -la "<file>"
   ```

3. Upload the file:
   ```bash
   slack file upload --file "<file>" --channels "<channel>"
   ```

4. Confirm the upload with the filename and channel.
```

- [x] **Step 3: Commit**

```bash
git add commands/upload.md skills/slack-upload/SKILL.md
git commit -m "feat: add slack:upload command and skill"
```

### Task 8: Status command and skill

**Files:**
- Create: `commands/status.md`
- Create: `skills/slack-status/SKILL.md`

- [x] **Step 1: Create the status command**

File: `commands/status.md`
```markdown
---
name: status
description: Set your Slack status and emoji
args: "<text> [emoji]"
---

Use the `slack-status` skill to set the status. Pass through all arguments.
```

- [x] **Step 2: Create the status skill**

File: `skills/slack-status/SKILL.md`
```markdown
---
name: status
description: Set Slack status text and emoji. Use when the user says "set slack status", "update status", "change presence", or wants to update their Slack status.
---

# Set Slack Status

Set the bot's Slack profile status text and emoji.

## Arguments

- `text` — status text (e.g., "In a meeting", "Working on deploy")
- `emoji` — status emoji without colons (optional, defaults to `speech_balloon`)

## Steps

1. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```
   If config is missing and `$SLACK_TOKEN` is not set, tell the user to run `/slack:setup` first.

2. Set the status:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
     -H "Content-type: application/json" \
     -d "{\"profile\":{\"status_text\":\"$TEXT\",\"status_emoji\":\":$EMOJI:\"}}" \
     https://slack.com/api/users.profile.set
   ```

3. Confirm the status was updated.
```

- [x] **Step 3: Commit**

```bash
git add commands/status.md skills/slack-status/SKILL.md
git commit -m "feat: add slack:status command and skill"
```

## Chunk 3: Loop, Stop, Tidy & README

### Task 9: Loop command and skill

**Files:**
- Create: `commands/loop.md`
- Create: `skills/slack-loop/SKILL.md`

- [x] **Step 1: Create the loop command**

File: `commands/loop.md`
```markdown
---
name: loop
description: Start a /loop 1m polling cycle for Slack channels
---

Use the `slack-loop` skill to start the Slack polling loop.
```

- [x] **Step 2: Create the loop skill**

File: `skills/slack-loop/SKILL.md`
```markdown
---
name: loop
description: Start a /loop 1m polling cycle for Slack channels. Use when the user says "start slack polling", "slack loop", "monitor slack", or wants to watch Slack channels for new messages.
---

# Slack Loop

Start a 1-minute polling cycle that checks configured Slack channels for new messages. Stays silent when there are no new messages.

**Announce at start:** "Starting Slack polling loop (1m interval)."

## Setup

Use `/loop 1m` to schedule this prompt as a recurring cron job:

```
check slack — for each channel in AUTONOMOUS_CHANNELS from ~/.claude/slack.conf, fetch new messages since cursor
```

## When the loop fires

Each minute, the scheduled prompt runs. The agent should:

1. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```

2. For each channel in `$AUTONOMOUS_CHANNELS` (comma-separated):
   - Get the channel ID
   - Fetch messages newer than the stored cursor
   - If new messages exist: use the `slack-read` skill to read and act on them
   - If no new messages: produce no output (stay quiet)

## Stopping

Tell the user the CronDelete job ID so they can stop polling when done.
```

- [x] **Step 3: Commit**

```bash
git add commands/loop.md skills/slack-loop/SKILL.md
git commit -m "feat: add slack:loop command and skill"
```

### Task 10: Stop command and skill

**Files:**
- Create: `commands/stop.md`
- Create: `skills/slack-stop/SKILL.md`

- [x] **Step 1: Create the stop command**

File: `commands/stop.md`
```markdown
---
name: stop
description: Stop the Slack polling loop
---

Use the `slack-stop` skill to stop the polling loop.
```

- [x] **Step 2: Create the stop skill**

File: `skills/slack-stop/SKILL.md`
```markdown
---
name: stop
description: Stop the Slack polling loop. Use when the user says "stop slack", "stop slack polling", "cancel slack loop", or wants to end the recurring Slack check.
---

# Stop Slack Loop

Stop the recurring Slack polling loop started by the slack-loop skill.

## Steps

1. List active cron jobs using CronList to find the Slack polling job
   (look for jobs with "check slack" in the prompt).

2. Delete it with CronDelete using the job ID.

3. Confirm to the user that polling has stopped.
```

- [x] **Step 3: Commit**

```bash
git add commands/stop.md skills/slack-stop/SKILL.md
git commit -m "feat: add slack:stop command and skill"
```

### Task 11: Tidy command and skill

**Files:**
- Create: `commands/tidy.md`
- Create: `skills/slack-tidy/SKILL.md`

- [x] **Step 1: Create the tidy command**

File: `commands/tidy.md`
```markdown
---
name: tidy
description: Reset Slack cursor state and mark channels as read
---

Use the `slack-tidy` skill to tidy up Slack state.
```

- [x] **Step 2: Create the tidy skill**

File: `skills/slack-tidy/SKILL.md`
```markdown
---
name: tidy
description: Reset Slack cursor state and mark channels as read. Use when the user says "tidy slack", "reset slack cursors", "mark all read", or wants to clean up Slack tracking state.
---

# Tidy Slack State

Reset cursor tracking state and optionally mark all channels as read.

## Steps

1. Show current cursor state:
   ```bash
   echo "Tracked channels:"
   cat ~/.claude/slack-cursors.conf 2>/dev/null || echo "(none)"
   ```

2. Load config:
   ```bash
   source ~/.claude/slack.conf 2>/dev/null
   ```

3. For each tracked channel, mark as read in Slack:
   ```bash
   while IFS='=' read -r CHANNEL_ID TIMESTAMP; do
     curl -s -X POST -H "Authorization: Bearer $SLACK_TOKEN" \
       -H "Content-type: application/json" \
       -d "{\"channel\":\"$CHANNEL_ID\",\"ts\":\"$TIMESTAMP\"}" \
       https://slack.com/api/conversations.mark
   done < ~/.claude/slack-cursors.conf
   ```

4. Reset the cursor file:
   ```bash
   > ~/.claude/slack-cursors.conf
   ```

5. Report what was tidied (number of channels reset).
```

- [x] **Step 3: Commit**

```bash
git add commands/tidy.md skills/slack-tidy/SKILL.md
git commit -m "feat: add slack:tidy command and skill"
```

### Task 12: README

**Files:**
- Create: `README.md`

- [x] **Step 1: Create README.md**

```markdown
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
```

- [x] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and usage instructions"
```
