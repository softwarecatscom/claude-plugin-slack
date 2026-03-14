---
name: rfc
description: Draft and send an RFC (Request for Comments) to the team via Slack. Use when the user says "rfc", "send an rfc", "ask the team", "get team feedback", or wants to propose a change and collect input before implementing.
---

# RFC (Request for Comments)

Draft a proposal, post it to the team in Slack with `@here`, and collect feedback. Use this when a change affects the team — new workflows, skill changes, architectural decisions, conventions — and you want input before committing to it.

## Arguments

- `topic` — what the RFC is about (required)
- `channel` — channel to post in (optional, defaults to `DEFAULT_CHANNEL` from config)

## When to use

- Proposing workflow changes that affect how other agents operate
- Adding or modifying skills that the team will use
- Architectural decisions with trade-offs that benefit from multiple perspectives
- Conventions or standards that need team buy-in
- Any change where "just do it" would be presumptuous

## When NOT to use

- Bug fixes with an obvious correct answer
- Changes scoped entirely to your own agent
- Work that's already been approved or assigned

**Prefer `ctx_execute` over Bash** when running scripts that produce output. This keeps raw output in the sandbox and protects your context window.

## Steps

### Step 1: Draft the proposal

Structure the RFC with these sections:

1. **Title** — short, descriptive name for the proposal
2. **Problem** — what gap, pain point, or opportunity this addresses (1-2 sentences)
3. **Proposal** — what you want to do, in concrete terms. Include specific changes (file paths, code snippets, workflow steps) so reviewers can evaluate the actual impact, not just the idea.
4. **Alternatives considered** — other approaches and why you're not recommending them (brief)
5. **Questions for the team** — specific things you want feedback on. Don't just say "thoughts?" — ask targeted questions: "Should X be opt-in or default?", "Does this conflict with how you handle Y?"

Keep the whole RFC concise. If it's longer than a Slack message can comfortably hold, the proposal is too big — break it into smaller RFCs.

### Step 2: Review with your local user

Show the draft to your local user before posting. They may have context the team doesn't, or may want to adjust the framing. Only post after they approve (or say to go ahead).

### Step 3: Post to Slack

Send the RFC to the channel with `@here` so all agents see it:

```bash
"${SCRIPTS_DIR}/slack-send" "${CHANNEL}" "@here RFC: [title]

**Problem:** [problem]

**Proposal:** [proposal]

**Alternatives:** [alternatives]

**Questions:**
1. [question 1]
2. [question 2]

Please reply with feedback, concerns, or +1 if you agree."
```

### Step 4: Collect feedback

Monitor responses via the read skill (or polling loop). For each response:

- Note whether it's an approval (+1, "looks good"), a concern, a suggestion, or a question
- If a response raises a valid point, acknowledge it: "Good point, I'll adjust X"
- If a response conflicts with another, flag it: "This conflicts with what @Name suggested — how should we reconcile?"

### Step 5: Summarize and decide

Once responses have come in (give it at least one polling cycle, or longer for bigger proposals):

- If **consensus**: summarize the outcome, note any adjustments, and proceed with implementation
- If **disagreement**: present the conflicting views to your local user and ask for a tiebreak
- If **silence**: after a reasonable wait, ping again or proceed with a note: "No objections received, moving forward"

Post the summary to Slack so the decision is visible:

```bash
"${SCRIPTS_DIR}/slack-send" "${CHANNEL}" "RFC resolved: [title]

**Decision:** [what we're doing]
**Adjustments from feedback:** [any changes made]
**Next:** [implementation plan]"
```

## Tips

- Tag specific agents when their domain is relevant: "@Z490 this touches the deploy workflow — your input especially"
- RFCs are for input, not permission. If the team approves, act on it. Don't ask again.
- Small RFCs get faster responses. A 3-line proposal gets feedback in minutes; a wall of text gets skimmed or ignored.
