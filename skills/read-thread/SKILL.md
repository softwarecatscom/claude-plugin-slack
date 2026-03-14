---
name: read-thread
description: Read a specific Slack thread by URL or reference. Use when the user shares a Slack thread link, says "read this thread", "check that conversation", or when you need to fetch a specific thread's contents on demand.
---

# Read Thread

Fetch and display the contents of a specific Slack thread given a URL, deep link, or channel+thread_ts reference.

## Arguments

- `url_or_ref` — a Slack thread URL, deep link, or `CHANNEL_ID THREAD_TS` pair

## Examples

```
/scc-slack:read-thread https://softwarecatsworkspace.slack.com/archives/C0AKTEMDP9C/p1773516874346219
/scc-slack:read-thread C0AKTEMDP9C 1773516874.346219
```

## Steps

### Step 1: Resolve SCRIPTS_DIR

```
SCRIPTS_DIR="$(find ~/.claude/plugins/cache/scc-marketplace/scc-slack -maxdepth 1 -type d | sort -V | tail -1)/scripts"
```

### Step 2: Fetch the thread

Run the script via `ctx_execute` to keep raw output in the sandbox:

```
ctx_execute(language: "shell", code: """
SCRIPTS_DIR="<resolved path>"
"${SCRIPTS_DIR}/slack-thread" <url_or_ref>
""")
```

The script accepts:
- A full Slack URL: `https://workspace.slack.com/archives/CHANNEL/pTIMESTAMP`
- A URL with thread_ts query param: `...?thread_ts=TS&cid=CHANNEL`
- Two arguments: `CHANNEL_ID THREAD_TS`

### Step 3: Display results

The script outputs a JSON array of messages with `ts`, `user`, `text`, and `thread_ts` fields. Present the thread contents to the user in a readable format.

If the thread is long, summarize key points. If the user needs specific details, quote relevant messages.

## URL Parsing

Slack URLs encode the timestamp without a dot:
- URL: `p1773516874346219`
- Actual ts: `1773516874.346219` (first 10 digits + dot + rest)

The script handles this parsing automatically.

## When to use

- When someone shares a Slack thread URL and asks you to read it
- When you need to catch up on a specific conversation
- When a thread reference is given and you need context
- When Christo or team links to a thread for you to review
