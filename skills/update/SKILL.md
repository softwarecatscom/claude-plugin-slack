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

### Step 4: Verify

Before reporting success, complete all of these checks:

1. **Scripts on disk** — confirm the new version cache directory exists:
   ```bash
   ls ~/.claude/plugins/cache/scc-marketplace/scc-slack/
   ```
   The new version directory should be present.

2. **Test poll** — run a test poll with stderr visible to verify the scripts work:
   ```bash
   SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
   "${SCRIPTS_DIR}/slack-poll" 2>&1 | head -5
   ```
   Verify the output contains channel headers (`# channel=...`) and no errors.

3. **Polling version** — confirm the reload applied the new version path:
   ```bash
   find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1
   ```
   The path should reference the new version.

4. **Version confirmation** — only report "Updated to vX.Y.Z" after all checks pass.

If any check fails, diagnose the issue instead of reporting success. Common problems:
- Old version directory still being used → re-run reload
- `ok:false` from fetch → check token, check channel resolution
- Missing scripts directory → update may have failed silently, retry
