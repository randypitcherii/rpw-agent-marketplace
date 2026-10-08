---
name: ship-it
description: One-command post-merge close-out for an approved PR. Trigger on "ship it", "land this PR", "close out PR #N", "merge and clean up", "land the plane". Ships unless a live wave CLAIMS the issue (file overlap never holds a PR), then squash-merges with the transient-retry loop, confirms the issue closed, cleans worktree/branches, verifies the auto-bump (repairing if not — #480), refreshes clones and plugins, plus the gated publish. NOT for prepping or reviewing a PR — that's code-review-and-pr.
---

# Ship It — post-merge close-out

`code-review-and-pr` stops at "ready to merge?". This skill is the tail after that: wave boundary → merge → confirm close → clean → version-check → clone refresh → plugin update → (optionally) publish. Steps 0–6 run **autonomously** for PRs whose base is the integration branch (`production`); step 7 runs **only on explicit request**.

## When NOT to run

- **Prepping or reviewing** a PR → `code-review-and-pr`.
- The PR closes an issue a **live wave has claimed**, or the merge would touch that wave's PRs, workers, or worktrees → hand it back to the supervisor (see `wave-supervisor` and step 0). A wave merely *editing the same files* is not this case: ship, and whoever lands last rebases.
- Base branch is a **release/publish branch** or the merge triggers a public release → confirm with the user first.

## Pipeline

Input: a PR number (or infer the current branch's open PR via `gh pr view --json number`).

### 0. Wave boundary — stay out of a wave's lane, not out of its files

**File overlap is explicitly NOT a reason to hold a PR, and there is no conflict-prediction check here.** `production` is the integration branch; a wave rebases onto it like everything else. **Whoever arrives last resolves the conflict** — that is the whole convention, it is cheap, and it is the wave's job when the wave is the one that lands second. Holding a finished, approved PR because a `wave/*` branch happens to edit the same file just converts a routine rebase into an indefinite block, and the wave still has to rebase either way.

What you must not do is **operate inside a wave's lane**. Never, for a wave that holds the issue:

- take, re-assign, comment-as-owner on, or close its **claimed issues** (`wave: owned`);
- merge, close, retarget, or push to its **PRs**;
- touch its **worker branches**, **worktrees**, or running **supervisor sessions**;
- pick up an issue the wave has claimed just because it looks idle — a `stale` lease is not a free issue. Lease liveness is a heartbeat, never process existence (#886), and a supervisor deep in a long task routinely lets the heartbeat lapse while merging steadily. Measured case: a lease read `stale` at 205m against a 45m TTL while its session had been active four minutes earlier.

So the check is about **ownership of the work**, not about the diff:

```bash
# Is the issue THIS PR closes claimed by a live wave?
gh issue list --label 'wave: owned' --state open --json number,title
gh issue view <issue-this-PR-closes> --json labels,assignees
```

Claimed by a wave → it is not yours to ship; hand it back and say so. Not claimed → ship it, conflicts and all.

### 1. Merge (with the transient-retry loop)

```bash
gh pr merge <N> --squash              # NOT --delete-branch (see below)
git push origin --delete <branch>     # delete the remote ref yourself
```

**Why not `--delete-branch` (#1231):** from a worktree it *always* fails its local half — gh tries to check out the base branch to delete the local ref, and the base is checked out in the main clone:

```
failed to run git: fatal: 'production' is already used by worktree at '/Users/<you>/projects/rpw-agent-marketplace'
```

The merge and the remote delete already succeeded, so the nonzero exit reads like a failed merge when nothing is wrong — and the local branch survives. Worktree development is the house standard, so this fires on **every** merge: the largest single source of the 74 orphaned branches #1231 measured. Delete the remote ref explicitly; the local ref is step 3's job.

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
git fetch --prune                       # the remote ref you deleted in step 1
git worktree list                       # find the feature worktree, if any
git worktree remove <path>              # --force only for disposable leftovers
git branch -D <branch>                  # -D, not -d: squash rewrote the SHA, so
                                        # -d refuses forever. Step 1's merge is
                                        # the proof that authorizes it.
```

**Can't tear down your own worktree? Point at the sweep, never at a manual command.** `ExitWorktree` no-ops on worktrees it did not create — most of them — so the agent that finishes the work routinely cannot clean up after it (#1231):

```bash
make branch-hygiene                     # dry run: what is provably dead + evidence
make branch-hygiene APPLY=1             # reap it
```

It is repo-wide and refuses a dirty tree, unpushed commits, no merged PR, or an active claim — so leaving a branch to it is safe, not sloppy.

Dispatched-session teardown (close the session, remove the worktree, prune the branch) is owned by the `dispatch-launch` skill — hand off there rather than reimplementing.

### 4. Version check + repair (the safety net — #480)

**Why:** since #480 the auto-bump runs post-merge on `production` (the old per-PR bump lost its race against `gh pr merge --squash` three times in two days — #450/#467/#477). The race is gone by construction, but this step stays as the safety net: confirm the post-merge workflow actually ran and bumped (workflow failure, skipped run, or a pre-#480 merge being closed out late all still ship unbumped, leaving `claude plugin update` reporting "already at latest").

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
make publish-promote TARGET=<slug> DESCRIPTION='<review summary>'
```

This opens a promotion PR to the protected private `published/<target>` branch. **Stop there.** The human reviews that complete artifact diff. After merge, trusted CI performs content-only delivery from a fresh public-target clone and merges the target-local PR after its required checks pass. Consider `make release-notes` / `make tag-release` alongside, per the release flow in AGENTS.md.

## Report shape

End with one tidy summary:

- **Wave boundary:** issue unclaimed — cleared to ship (file overlap with wave #W, if any, is the later merger's rebase)
- **Merged:** PR #N → `production` @ `<sha>` (retries needed: n)
- **Issue:** #M closed (auto / manual) — or left open (`Part of`)
- **Cleanup:** worktree removed, branches pruned
- **Version:** bump landed in squash (`old → new`) / catch-up PR #X merged / no plugin files touched
- **Clones:** refreshed (`--ff-only`)
- **Plugin update:** `old → new` — restart sessions to apply
- **Publish:** not run / mirror PR <link> awaiting the human's merge
