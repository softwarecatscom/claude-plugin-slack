---
name: reload
description: Reload the Slack plugin and restart polling. Use when the user says "reload slack", "restart polling", "reload plugin", or after updating the plugin to apply changes.
---

# Reload Slack Plugin

Stop the polling loop, reload plugins to pick up new code, and restart polling. Use after updating the plugin (`/plugin`) to apply changes without manual stop/start.

## Steps

### Step 1: Stop the current polling loop

Use the `scc-slack:stop` skill to cancel the active cron job. If no loop is running, skip this step.

### Step 2: Reload plugins

```
/reload-plugins
```

This picks up any new or updated skills, commands, hooks, and agents from the plugin cache.

### Step 3: Restart the polling loop

Use the `scc-slack:loop` skill to start a new 1-minute polling cycle.

### Step 4: Confirm

Report what happened: old job cancelled, plugins reloaded, new job started with its ID.
