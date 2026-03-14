---
name: lookup
description: Look up a Slack channel or user by name. Use when the user says "lookup channel", "find user", "who is @name", "what channel is #name", or when any other skill needs to resolve a channel or user.
---

# Slack Lookup

Resolve a channel name to its ID, or a user name to their ID. Results are cached — repeated lookups are instant.

## Arguments

- `query` — a channel name prefixed with `#` (e.g., `#general`) or a user name prefixed with `@` (e.g., `@christo`). The prefix can be omitted if the intent is clear from context.

## Scripts

Locate the plugin scripts once per session:
```bash
SCRIPTS_DIR=$(find ~/.claude/plugins/cache -path "*/scc-slack/*/scripts/slack-identity" 2>/dev/null | sort -V | tail -1 | xargs dirname)
```

**Prefer `ctx_execute` over Bash** when running these scripts. This keeps output in the sandbox and protects your context window.

## Steps

1. **If the query is a channel** (`#` prefix or channel context), run via `ctx_execute`:
   ```bash
   "${SCRIPTS_DIR}/slack-resolve" --channel "<channel_name>"
   ```
   Output: `CHANNEL_ID=channel_name`

2. **If the query is a user by name** (`@` prefix or user context):
   ```bash
   "${SCRIPTS_DIR}/slack-resolve" --name "<display_name>"
   ```
   Output: `USER_ID=display_name`

3. **If the query is a user ID** (e.g., `U0AKZ8QEQ66`):
   ```bash
   "${SCRIPTS_DIR}/slack-resolve" "<user_id>"
   ```
   Output: `USER_ID=display_name`

4. **Batch resolve** multiple IDs or names in one call:
   ```bash
   "${SCRIPTS_DIR}/slack-resolve" U0AKZ8QEQ66 U0AKE1L3YJ3
   "${SCRIPTS_DIR}/slack-resolve" --name Z490 Rogue1
   ```

5. If no match is found, report that and suggest checking the spelling or running `scc-slack:channels` to list available channels.
