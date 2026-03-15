# Development Conventions

Conventions for developing and maintaining the scc-slack plugin.

## Dev Environment Setup

```bash
# Install dev dependencies (pre-commit, ruff, pytest)
uv sync --group dev

# Install pre-commit hooks
pre-commit install

# Verify hooks work
pre-commit run --all-files
```

Pre-commit runs automatically on `git commit`. Hooks include: shellcheck (bash), ruff check + format (Python), and standard file checks (trailing whitespace, line endings, JSON/TOML validation).

## Scripts

### Naming
- All scripts follow the `slack-<action>` pattern (e.g. `slack-send`, `slack-poll`, `slack-heartbeat`)
- Scripts are executable and live in `scripts/`

### Flag Parsing
- Flags are position-independent — all flags are collected left-to-right from any argv position, remaining args are positionals
- `slack-send agents "text" --thread TS` works the same as `slack-send --thread TS agents "text"`
- Use a `while/case` loop that collects `POSITIONALS` array for non-flag arguments

### Language Choice
- **New complex scripts**: Write in Python (`.py` extension) with a bash wrapper
- **Existing simple scripts**: Keep as bash; don't rewrite unless major changes are needed
- **Bash wrappers** are minimal: shebang, `set -euo pipefail`, `exec uv run script.py "$@"`

### JSON Construction
- Use `jq -n` for building JSON payloads (never string interpolation)
- In Python, use the `json` module directly

### Self-Bootstrapping
- Scripts that need config should auto-discover on first run and cache for subsequent runs
- Config files go in `~/.claude/` with descriptive names (e.g. `slack-heartbeat.conf`)
- If cached state becomes invalid (e.g. message deleted), clear cache and re-bootstrap on next run

### Token Loading
- Load the Slack bot token from `$(dirname "$(which slack)")/.slack`
- In Python: find the `slack` binary via `which`, then read `.slack` from its parent directory

## Heartbeat

### Algorithm
- Digit = `(current_minute // 6) + 1` — gives digits 1-10, cycling every 6 minutes within the hour
- Each digit window is 6 minutes wide; 10 windows per hour

### Format
- `:digit_emoji: vX.Y.Z` — digit emoji + scc-slack version only
- No extra info (no git branch, no activity state)
- Example: `:seven: v0.21.0`

### Location
- Each agent maintains exactly one reply in the pinned "Agent Status Check" thread
- Updated via `chat.update` (not new messages) — keeps thread clean
- Thread ts and own message ts cached in `~/.claude/slack-heartbeat.conf`

### Watchdog / Stale Detection
- After updating own heartbeat, check all peer bot messages in the thread
- Flag bots 2+ digits behind using modular arithmetic: `gap = (own - peer) % 10`
- Exclude humans from stale checks — filter by `bot_id` field presence (not hardcoded user IDs)
- Stale alerts resolve user IDs to display names via `slack-resolve` before posting
- Alert format: `@here Heartbeat check: possibly stale agents: Name (digit N, M behind)`

### Stale Response Protocol
1. Heartbeat script posts `@here` alert with stale agent list
2. First non-stale agent to respond claims the rescue (reacts with `:eyes:` or replies)
3. Claimed agent uses `/emt` skill to check on the stale agent
4. Agent reports back: recovered, down (needs human), or false alarm
5. No fixed buddy pairs — per-incident assignment based on who's available first

## API Constraints

- `xoxb-` (bot) tokens **cannot** call `users.profile.set` — status-based heartbeat is not possible
- `xoxb-` tokens **can** read user profiles via `users.info` — monitoring works, setting doesn't
- `chat.update` works for bot-posted messages — heartbeat via thread message editing is the viable approach
- Required scopes: `chat:write`, `channels:read`, `channels:history`, `reactions:write`, `files:write`, `users:read`, `pins:read`

## Releases

- Version source of truth: `.claude-plugin/plugin.json`
- Git tag must match: `v<version>`
- Update command: `/scc-slack:update` (never manual `claude plugin update`)
- Announcements end with: "Update with: /scc-slack:update"
- Reload cycle: stop cron -> update plugin -> verify scripts on disk -> test poll -> restart cron -> update MEMORY.md -> announce

### Update Verification (AGT-22)
1. Verify scripts exist on disk at new version path
2. Test poll with new version (`slack-poll-daemon --once` — verify no errors)
3. Confirm SCRIPTS_DIR in `~/.claude/slack.conf` points to new version
4. Only then report update as complete

## Linear Integration

- Label issues with `agent:<agentname>` when picking up work (e.g. `agent:macini`)
- Use team "Agents" (AGT prefix) for all plugin/agent issues
- RFC before implementing changes that affect other agents

## Plugin Structure

- **Commands**: `commands/<name>.md` — no `name:` in frontmatter, name comes from filename
- **Skills**: `skills/<name>/SKILL.md` — directory name must match `name:` field in SKILL.md frontmatter
- **Scripts**: `scripts/slack-<action>` — executable, no extension (or `.py` for Python with bash wrapper)

## Slack Interaction

- Act autonomously on messages addressed to you (direct mention or @here/@channel)
- Observe but don't act on messages between other agents
- Follow instructions exactly, don't improvise
- Self-correct: diagnose repeated failures instead of continuing blindly
- Use `slack-send` for messages, `slack-react` for reactions — never call the API directly with curl from agent code
