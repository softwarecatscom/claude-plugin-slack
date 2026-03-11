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
