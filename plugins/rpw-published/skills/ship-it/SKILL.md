---
name: ship-it
description: One-command post-merge close-out for an approved PR. Trigger on "ship it", "land this PR", "close out PR #N", "merge and clean up", "land the plane". Squash-merges (with the transient not-mergeable retry), confirms the linked issue closed, cleans worktree/branches, detects and repairs an unbumped ship (the #210 bump race), refreshes clones, runs claude plugin update, and optionally the gated public publish. NOT for prepping or reviewing a PR — that's code-review-and-pr.
---

# Ship It — post-merge close-out

`code-review-and-pr` stops at "ready to merge?". This skill is the tail after that: merge → confirm close → clean → version-check → clone refresh → plugin update → (optionally) publish. Steps 1–6 run **autonomously** for PRs whose base is the integration branch (`production`); step 7 runs **only on explicit request**.

## When NOT to run

- **Prepping or reviewing** a PR → `code-review-and-pr`.
- **Under a wave supervisor / build orchestrator that serializes merges** → open the PR and stop; the supervisor drives the merge (see `wave-supervisor`). Never ship-it around an orchestrator.
- Base branch is a **release/publish branch** or the merge triggers a public release → confirm with the user first.

## Pipeline

Input: a PR number (or infer the current branch's open PR via `gh pr view --json number`).

### 1. Merge (with the transient-retry loop)

```bash
gh pr merge <N> --squash --delete-branch
```

GitHub's mergeability computation is eventually consistent: right after approval or a fresh push, the merge can fail with *"Pull Request is not mergeable"* even though nothing is wrong. That failure is usually **transient**:

- Wait ~10s, check `gh pr view <N> --json mergeable,mergeStateStatus`, retry. Up to 3 retries.
- `mergeable: CONFLICTING` is a **real** conflict — stop, report, don't loop.
- Any auth/permission error — stop and report.

### 2. Confirm the linked issue closed

```bash
gh pr view <N> --json closingIssuesReferences,body
```

- For each `Closes #M` linkage: `gh issue view <M> --json state`. If still open, close it with a comment linking the merged PR.
- If the trailer was `Part of` / `Advances #M` (multi-PR issue): the issue **stays open** — tick its completed checklist items instead. Do not close umbrella issues early.

### 3. Clean up worktree + branches

From the main clone (not inside the doomed worktree):

```bash
git worktree list                       # find the feature worktree, if any
git worktree remove <path>              # --force only for disposable leftovers
git branch -D <branch>                  # if the local branch persists
git fetch --prune                       # remote branch was deleted by --delete-branch
```

Superset workspace deletion is owned by the `superset-launch` skill — hand off there rather than reimplementing.

### 4. Version check + repair (the load-bearing step — #210)

**Why:** the per-PR auto-bump Action pushes its bump commit to the PR head branch *asynchronously* and can lose the race against `gh pr merge --squash` — the squash captures the pre-bump tree, the branch is deleted, and the plugin ships to `production` **unbumped**. Then `claude plugin update` reports "already at latest" and never delivers the fix to version-detecting consumers. This has happened for real (#198 shipped at the old version; #372 shipped unbumped at 2026.07.1203).

**Detect** — in the production clone after pulling the merge (for an older merge, substitute `<merge-sha>` for `HEAD`):

```bash
git diff --name-only HEAD^..HEAD -- plugins/          # which plugin dirs changed
git diff HEAD^..HEAD -- .claude-plugin/marketplace.json 'plugins/*/.claude-plugin/plugin.json'
```

If a plugin's files changed but its version fields did not → **unbumped ship**.

**Repair (catch-up bump):**

1. Branch off `production` HEAD.
2. Run `make version-bump` — for a merge that isn't HEAD, pass `MERGE_DIFF_RANGE=<merge-sha>^..<merge-sha>`. The script detects the changed plugins and writes **both** `marketplace.json` and each plugin's `plugin.json` **in sync** (a repo test enforces they match).
3. **Never hand-edit version fields** — the bump script is the single writer; hand edits drift the two manifests.
4. Commit `chore(<plugin>): version catch-up <old> -> <new>`, push, open a PR to `production`, squash-merge it (a catch-up bump is routine → autonomous). Then re-run this step's detect on the catch-up merge to confirm green.

If the bump landed inside the squash normally, report that and move on.

### 5. Clone refresh

In each local `production` clone the user works from:

```bash
git pull --ff-only
```

`--ff-only` always — never introduce merge/rebase commits into a tracking clone during close-out. If it refuses, the clone has local divergence: report it, don't force.

### 6. Plugin update

```bash
claude plugin marketplace update rpw-agent-marketplace
claude plugin update rpw-published@rpw-agent-marketplace   # repeat per affected plugin
```

- The **full `name@marketplace` identifier is required** — a bare `claude plugin update rpw-published` fails to resolve.
- Report the version delta (`old → new`). If it reports "already at latest" but step 4 said the version *did* bump, the marketplace cache didn't refresh — rerun the `marketplace update` first.
- Note to the user: **running Claude sessions need a restart** to pick up the updated plugin.

### 7. Publish (optional — gated on explicit go)

Never part of the autonomous tail. Only when the user explicitly asks to publish:

```bash
make publish-public
```

This filters the tree per `.public-publish.yml`, pushes a `publish-staging` branch to the public mirror, runs the sensitive-content check locally (CI can't — IP ACL), and opens a PR against the mirror's default branch. **Stop there.** The human reviews the actual public diff and **their merge IS the publish** — never auto-merge the mirror PR. The `PUBLIC_REPO_RELEASE_CONFIRM` gate applies. Consider `make release-notes` / `make tag-release` alongside, per the release flow in AGENTS.md.

## Report shape

End with one tidy summary:

- **Merged:** PR #N → `production` @ `<sha>` (retries needed: n)
- **Issue:** #M closed (auto / manual) — or left open (`Part of`)
- **Cleanup:** worktree removed, branches pruned
- **Version:** bump landed in squash (`old → new`) / catch-up PR #X merged / no plugin files touched
- **Clones:** refreshed (`--ff-only`)
- **Plugin update:** `old → new` — restart sessions to apply
- **Publish:** not run / mirror PR <link> awaiting the human's merge
