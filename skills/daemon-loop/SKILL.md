---
name: daemon-loop
description: Supervise the Slack poll daemon — launch if stopped, process messages when it wakes. Invoked by the /loop 1m cron every minute.
---

# Daemon Loop

```bash
source ~/.claude/slack.conf
```

## Check daemon

```bash
"${SCRIPTS_DIR}/slack-poll-daemon" --status
```

- **"running"**: Stop. Say nothing.
- **"stopped"**: Launch it:

```bash
Bash(command: "${SCRIPTS_DIR}/slack-poll-daemon", description: "slack poll daemon", run_in_background: true)
```

## When the background task completes

Read the output. Use the `scc-slack:read` skill to process the messages. The next cron tick will re-launch the daemon.
