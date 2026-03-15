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

Pre-commit runs automatically on `git commit` and in CI (`pre-commit run --all-files` is the single source of truth for both local and GitHub Actions).

## Code Quality

### Linting and Formatting

- **Python**: ruff check + ruff format (config in `ruff.toml`, adapted from selfpub-wizard)
- **Bash**: shellcheck (vendored `scripts/slack` excluded — we don't own it)
- **Pre-commit hooks**: check-json, check-yaml, check-toml, end-of-file-fixer, trailing-whitespace, check-case-conflict, check-merge-conflict, mixed-line-ending
- **CI**: GitHub Actions runs `pre-commit run --all-files` on push to master and PRs

### Python Style Rules

- `from __future__ import annotations` at the top of every Python file
- Native Python types everywhere: `list[dict]`, `int | None`, `dict[str, str]` — never import from `typing`
- **Exception: Typer command signatures.** Typer does not support `type | None` for optional args in `@app.command()` functions. Use `Optional[type]` there only, with `# noqa: UP045`:

```python
from typing import Optional

@app.command()
def run(
    interval: Optional[int] = POLL_OPTIONS["interval"],  # noqa: UP045
) -> None: ...
```

## Scripts

### Naming
- All scripts follow the `slack-<action>` pattern (e.g. `slack-send`, `slack-poll`, `slack-heartbeat`)
- Scripts are executable and live in `scripts/`

### Language Choice
- **New scripts**: Write in Python (`.py` extension) with a bash wrapper
- **Existing simple scripts**: Keep as bash; don't rewrite unless major changes are needed
- **Bash wrappers** are minimal: shebang, `set -euo pipefail`, `exec uv run --no-project script.py "$@"`

### PEP 723 Inline Script Metadata

All Python scripts use [PEP 723](https://peps.python.org/pep-0723/) inline metadata for dependency declaration. This lets `uv run --no-project` install deps automatically without a virtualenv.

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "typer"]
# ///
```

### Typer CLI Standard

Python scripts with CLI arguments use [Typer](https://typer.tiangolo.com/) for argument parsing. All scripts must support these standard flags:

| Flag | Description | Env Var |
|------|-------------|---------|
| `--debug` | Enable debug output to stderr | `DEBUG` |
| `--verbose`, `-v` | Increase verbosity (repeatable: `-v`, `-vv`, `-vvv`) | `VERBOSE` |
| `--dry-run` | Run without side effects (skip writes, API mutations) | `DRY_RUN` |

**Shared options** are defined in `scripts/slack_cli_options.py` and imported by all scripts. This avoids repeating `typer.Option(...)` specs and ensures consistent flag names, help text, and env var bindings:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from slack_cli_options import COMMON_OPTIONS
# COMMON_OPTIONS has: "verbose", "debug", "dry_run" — all with envvar support
```

**Script-specific options** go in a local dict (e.g. `POLL_OPTIONS`, `HEARTBEAT_OPTIONS`). Same DRY pattern — define once, reference by key:

```python
POLL_OPTIONS = {
    "interval": typer.Option(None, "--interval", "-i", help="Poll interval in seconds"),
}
```

**Output conventions:**
- `typer.echo(msg, err=True)` for diagnostic output (stderr)
- `typer.echo(msg)` for program output (stdout)
- `raise typer.Exit(code=1)` instead of `sys.exit(1)`

Example structure:

```python
import typer
from slack_cli_options import COMMON_OPTIONS

EXAMPLE_OPTIONS = {
    "limit": typer.Option(10, "--limit", "-n", help="Max items"),
}

app = typer.Typer(name="slack-example", add_completion=False)

@app.command()
def run(
    verbose: int = COMMON_OPTIONS["verbose"],
    debug: bool = COMMON_OPTIONS["debug"],
    dry_run: bool = COMMON_OPTIONS["dry_run"],
    limit: int = EXAMPLE_OPTIONS["limit"],
) -> None:
    """Run the thing."""

if __name__ == "__main__":
    app()
```

### Bash Flag Parsing
- Flags are position-independent — all flags are collected left-to-right from any argv position, remaining args are positionals
- `slack-send agents "text" --thread TS` works the same as `slack-send --thread TS agents "text"`
- Use a `while/case` loop that collects `POSITIONALS` array for non-flag arguments

### JSON Construction
- Use `jq -n` for building JSON payloads in bash (never string interpolation)
- In Python, use the `json` module directly

### Self-Bootstrapping
- Scripts that need config should auto-discover on first run and cache for subsequent runs
- Config files go in `~/.claude/` with descriptive names (e.g. `slack-heartbeat.conf`)
- If cached state becomes invalid (e.g. message deleted), clear cache and re-bootstrap on next run

### Token Loading
- Load the Slack bot token from `$(dirname "$(which slack)")/.slack`
- In Python: find the `slack` binary via `which`, then read `.slack` from its parent directory

## Daemon Architecture

The slack poller (`scripts/slack-poll.py`) is the **only** mechanism for agents to receive Slack events. There is no cron-based `slack-poll` alternative.

### How it works
1. `/loop 1m` cron fires → invokes `daemon-loop` skill
2. Skill checks daemon status (singleton via PID file) → launches if stopped via `Bash(run_in_background: true)`
3. Daemon polls Slack every 60s internally — zero token cost while idle
4. When actionable messages found: outputs enriched JSON and exits
5. Agent processes messages via `read` skill → next cron tick re-launches daemon

### Enriched Output
The daemon pre-processes everything so the AI only handles judgment calls:
- **Sender names** pre-resolved (no API calls needed by agent)
- **Thread context** pre-fetched for thread replies
- **Mention tracking** auto-cleared for thread replies
- **Cursors** managed internally (channel + thread)
- **Heartbeat** runs every cycle
- **Mention tracker tick** runs every cycle

### Token Efficiency
- **Idle cycle**: ~170 tokens (daemon-loop skill only — checks status, does nothing)
- **Active cycle**: ~727 tokens (daemon-loop + read skill)
- Push ALL algorithmic work into the Python daemon. The AI skill should contain ONLY judgment calls and response composition.
- When adding features, ask: "Can this run in the daemon instead of the skill?"

### Config
All skills use `source ~/.claude/slack.conf` for SCRIPTS_DIR and channel config. Only the `setup` and `update` skills write SCRIPTS_DIR — all others read it.

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
2. Test poll with new version (`slack-poll --once` — verify no errors)
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
