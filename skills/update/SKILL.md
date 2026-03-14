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
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
"${SCRIPTS_DIR}/slack-cache-clear"
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

2. **Test poll** — run a test poll to verify the scripts work:
   ```bash
   SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
   "${SCRIPTS_DIR}/slack-poll" > /tmp/slack-poll-test.json 2>/tmp/slack-poll-test-err.txt
   ```
   Read `/tmp/slack-poll-test.json` — verify the output contains channel headers (`# channel=...`) and a heartbeat line (`ok: :<digit>: v<version>`). Check `/tmp/slack-poll-test-err.txt` for errors.

3. **Polling version** — confirm the reload applied the new version path:
   ```bash
   find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1
   ```
   The path should reference the new version.

4. **Version confirmation** — only report "Updated to vX.Y.Z" after all checks pass.

### Step 5: Update MEMORY.md

Update the scc-slack version and script path in your project memory file so future sessions use the correct version:
- `scc-slack version`: v<new_version>
- `Script path`: the new version path from step 4

If any check fails, diagnose the issue instead of reporting success. Common problems:
- Old version directory still being used → re-run reload
- Errors in poll output → check token, check channel resolution
- Missing scripts directory → update may have failed silently, retry
