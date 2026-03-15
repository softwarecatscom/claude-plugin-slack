---
name: daemon-loop
description: Supervise the slack poller — launch if stopped, process messages when it wakes. Invoked by the /loop 1m cron every minute.
---

# Daemon Loop

```bash
source ~/.claude/slack.conf
```

## Check daemon

```bash
"${SCRIPTS_DIR}/slack-poll" --status
```

- **"running"**: Stop. Say nothing.
- **"stopped"**: Launch it:

```bash
Bash(command: "${SCRIPTS_DIR}/slack-poll", description: "slack-poll", run_in_background: true)
```

## When the background task completes

Read the output. Use the `scc-slack:read` skill to process the messages. The next cron tick will re-launch the poller.
