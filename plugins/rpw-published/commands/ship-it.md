---
name: ship-it
description: Post-merge close-out for an approved PR — merge, confirm issue close, clean up, version-check + repair (#210), refresh clones, plugin update; publish only on request.
allowed-tools: Bash, Skill, Read
user-invocable: true
---

# /ship-it — land an approved PR end-to-end

Run the **`ship-it`** skill and follow its pipeline:

1. **Merge** the PR (squash, with the transient not-mergeable retry loop).
2. **Confirm** the linked issue auto-closed; close it if not (`Part of` issues stay open).
3. **Clean** — remove the worktree, prune local + remote branches.
4. **Version check + repair** — detect an unbumped ship (the #210 auto-bump race) and land the catch-up bump via `make version-bump` (never hand-edit versions).
5. **Refresh** local production clones (`git pull --ff-only`).
6. **Plugin update** — `claude plugin marketplace update` + `claude plugin update <plugin>@<marketplace>` (full identifier required); report the version delta + restart note.
7. **Publish** — ONLY on explicit user request; stops at the reviewable mirror PR (the human's merge is the publish).

Anything after `/ship-it` is the PR number (or branch) to land; with no argument, infer the current branch's open PR. Steps 1–6 are autonomous for integration-branch merges; do not run this under a wave supervisor or orchestrator that serializes merges.
