---
name: token
description: Load the Slack API token from slack-cli. Use when the user says "slack token", "show token", or when any other skill needs the token.
---

# Load Slack Token

Load the Slack API token stored by slack-cli.

## Steps

1. Read the token from the `.slack` file next to the `slack` binary:
   ```bash
   SLACK_TOKEN=$(cat "$(dirname "$(which slack)")/.slack" 2>/dev/null)
   ```

2. If the file is missing or empty, tell the user to run `/scc-slack:setup` first.

3. Return the token value. When invoked by another skill, make `SLACK_TOKEN` available for subsequent steps.
