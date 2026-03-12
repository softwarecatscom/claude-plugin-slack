---
name: update
description: Update the scc-slack plugin to the latest version and reload. Use when the user says "update slack plugin", "update plugin", "get latest version", or when a new release is announced.
---

# Update Slack Plugin

Update the scc-slack plugin to the latest published version and reload to apply changes.

## Steps

### Step 1: Update the plugin

```bash
claude plugin update scc-slack@scc-marketplace
```

This pulls the latest version from the scc-marketplace registry.

### Step 2: Clear caches

Remove stale cached data that may cause issues with the new version:

```bash
# Clear the user resolve cache (display names may have changed, entries may be corrupted)
rm -f ~/.claude/slack-cache/users

# Clear the channel resolve cache
rm -f ~/.claude/slack-cache/channels
```

The caches will be rebuilt automatically on next use.

### Step 3: Reload

Use the `scc-slack:reload` skill to stop polling, reload plugins with the new code, and restart polling.

### Step 4: Confirm

Report the result: which version was installed, that caches were cleared, and that polling has been restarted.
