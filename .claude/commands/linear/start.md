---
description: Assign a Linear issue to yourself, set it In Progress, and start working on it
argument-hint: AGT-10
---

Start working on a Linear issue.

## Steps

1. If `$ARGUMENTS` is empty, list open issues assigned to you (or unassigned) in the **Agents** team using `list_issues` and ask which one to work on. Otherwise, use `$ARGUMENTS` as the issue identifier.

2. Fetch the full issue using `get_issue` to understand the scope, description, and acceptance criteria.

3. Assign the issue to yourself (`"me"`) and set the state to `"In Progress"` using `save_issue`.

4. Summarize the issue to the user: title, priority, description, and what needs to be done.

5. Begin working on the issue — read relevant files, make changes, and follow the issue description as your spec. Apply normal development practices (read before editing, keep changes focused, test if applicable).
