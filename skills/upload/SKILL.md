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
