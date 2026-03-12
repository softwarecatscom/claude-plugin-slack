---
description: Bump version (major/minor/patch), commit, tag, and push
argument-hint: major|minor|patch
---

Perform a release of the scc-slack plugin.

## Steps

1. Read the current version from `.claude-plugin/plugin.json`
2. Bump the **$ARGUMENTS** component of the semver version:
   - `patch`: 0.11.2 → 0.11.3
   - `minor`: 0.11.2 → 0.12.0
   - `major`: 0.11.2 → 1.0.0
3. If `$ARGUMENTS` is empty or not one of `major`, `minor`, `patch`, show usage and stop
4. Update the version in `.claude-plugin/plugin.json`
5. Stage all modified tracked files (`git add -u`)
6. Commit with message: `Bump version to <new-version>`
7. Tag with `v<new-version>`
8. Push commit and tag: `git push && git push origin v<new-version>`
9. Report the new version and tag
10. If the `scc-slack:announce` skill is available, use it to announce the release to the team on Slack
