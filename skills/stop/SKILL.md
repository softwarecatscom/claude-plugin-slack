---
name: stop
description: Stop the Slack polling loop. Use when the user says "stop slack", "stop slack polling", "cancel slack loop", or wants to end the recurring Slack check.
---

# Stop Slack Loop

Stop the recurring Slack polling loop and the slack poller.

## Steps

1. **Stop the poller:**
   ```bash
   source ~/.claude/slack.conf
   "${SCRIPTS_DIR}/slack-poll" --stop
   ```

2. **Stop the cron:** List active cron jobs using CronList to find the Slack polling job, then delete it with CronDelete using the job ID.

3. Confirm to the user that polling has stopped.
