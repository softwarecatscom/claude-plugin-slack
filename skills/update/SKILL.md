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

### Step 2: Update config and clear caches

Locate the new scripts directory:

```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

Update `SCRIPTS_DIR` in `slack.conf`:
```bash
sed -i '/^SCRIPTS_DIR=/d' ~/.claude/slack.conf
echo "SCRIPTS_DIR=\"${SCRIPTS_DIR}\"" >> ~/.claude/slack.conf
```

Check `SLACK_PROXY_URL` — if missing, ask the user:
```bash
grep SLACK_PROXY_URL ~/.claude/slack.conf
```
- If present: leave it (already configured)
- If missing: ask "Do you want to configure a caching proxy? (y/n, default: n)"
  - If yes: "Hostname? (default: z490.lionsden.gbr)" then "Port? (default: 8321)"
  - Add `SLACK_PROXY_URL="http://<hostname>:<port>"` to slack.conf
  - If no or "none": skip — poller falls back to direct Slack automatically

Clear stale cached data (via `ctx_execute`):
```bash
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

2. **Test poll** — verify the poller runs without errors:
   ```bash
   source ~/.claude/slack.conf
   "${SCRIPTS_DIR}/slack-poll" once --dry-run
   ```
   Dry run skips heartbeat and mention tracker. Verify it completes without errors.

3. **SCRIPTS_DIR** — confirm `slack.conf` points to the new version:
   ```bash
   grep SCRIPTS_DIR ~/.claude/slack.conf
   ```
   The path should reference the new version directory.

4. **Version confirmation** — only report "Updated to vX.Y.Z" after all checks pass.

### Step 5: Read the polling guide

After updating, read `docs/polling-guide.md` in the plugin repo to refresh your understanding of the polling architecture. The guide covers how the poller works, message format, processing rules, and troubleshooting.

```bash
source ~/.claude/slack.conf
cat "$(dirname "${SCRIPTS_DIR}")/docs/polling-guide.md"
```

### Step 6: Update MEMORY.md

Update the scc-slack version and script path in your project memory file so future sessions use the correct version:
- `scc-slack version`: v<new_version>
- `Script path`: the new version path from step 4

If any check fails, diagnose the issue instead of reporting success. Common problems:
- Old version directory still being used → re-run reload
- Errors in poll output → check token, check channel resolution
- Missing scripts directory → update may have failed silently, retry
