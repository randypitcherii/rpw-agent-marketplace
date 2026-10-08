---
name: scrub-repo-history
description: Permanently remove content from a git repository's history — a leaked secret, a file that should never have been committed, an oversized blob — by rewriting every affected commit with git-filter-repo, behind a mandatory backup, dry-run preview, and force-push gate. Trigger on "scrub this from the repo", "remove a secret from git history", "purge a file from all commits", "rewrite history to delete X", "it's still in an old commit". NOT for ordinary file deletion (`git rm`).
---

# Scrub content from git history

Deleting a file in the working tree leaves it in every commit that ever held it. Scrubbing means
**rewriting history**: every affected commit gets a new SHA, and the shared branch has to be
force-pushed. That is irreversible, it invalidates every clone, and a careless force-push destroys
other people's work.

Use this skill only when the content must be unreachable from history. If the goal is "stop
shipping this file", `git rm` + a commit is the correct, non-destructive answer — stop here.

## Rotate first. Always.

**If the content is a credential, rotate it before you touch git.** Assume it is already
compromised: assume it has been cloned, mirrored, indexed, and scraped. A history rewrite is damage
limitation — it is never the remedy, and treating it as one leaves a live secret in the world.

Order of operations for a leak: **rotate → verify the old credential is dead → then (optionally) scrub.**

## What a rewrite does NOT fix

Say this out loud to the user before they approve anything:

| Survives the rewrite | Why |
|---|---|
| **Forks** | A fork keeps its own copy of the objects; on GitHub the old commit stays reachable across the fork network by SHA until GitHub GCs it (a support request, not a git command). |
| **Existing clones** | Every teammate, CI cache, and agent worktree still has the old objects. |
| **Cached web views** | GitHub PR diffs, issue/PR comments quoting the content, and `/commit/<old-sha>` URLs keep resolving for a while. |
| **CI logs and build artifacts** | Logs, test output, and published artifacts are outside git entirely. |
| **Package registries and mirrors** | Anything already published carries the content forever. |
| **Scrapers and secret-scanning corpora** | Public repos are continuously copied by third parties. |
| **Local reflogs and stashes** | Old objects linger in every developer's `.git` until GC. |

## The gate — never skip a step

1. **Backup.** `git clone --mirror <repo> <backup-dir>` to a dated path outside the working repo, and confirm it exists before anything else. This mirror is the only undo.
2. **Preview.** Run `scripts/scrub_preview.sh` and show the user exactly which commits, blobs, branches, and tags change.
3. **Confirm the rewrite.** The user must approve a statement naming the repo, the branch(es), and the exact paths/patterns. No implied approval, no "proceed" inherited from an earlier turn.
4. **Rewrite** on a fresh mirror clone (see `reference/filter-repo-recipes.md`).
5. **Verify** the content is gone from `--all` and that unaffected history is intact.
6. **Confirm the force-push separately.** It is a second, distinct approval. Use `scripts/scrub_force_push.sh`, which refuses without a typed confirmation and without a verified backup.
7. **Coordinate.** Tell every consumer to re-clone; rebase open PRs. See `reference/coordination.md`.

Steps 3 and 6 are separate on purpose: a rewritten local mirror is still recoverable, a force-push
to a shared branch is not.

## Tooling

`git-filter-repo` is the maintained tool. `git filter-branch` is discouraged by git itself
(slow and full of footguns) and BFG is a niche alternative for very large repos.

If `git filter-repo --version` fails, filter-repo is not installed. Do not fall back to
`filter-branch` — run it on demand instead:

```bash
uvx --from git-filter-repo git-filter-repo --version   # no install needed
```

Everywhere the recipes say `git filter-repo …`, the on-demand form is
`uvx --from git-filter-repo git-filter-repo …`. Persistent installs: `brew install git-filter-repo`
or `pipx install git-filter-repo`.

## Tags: rewrite them (the default)

Annotated and lightweight tags pointing at affected commits are **rewritten**, which filter-repo
does automatically for the refs it processes. Leaving a tag on a pre-rewrite commit keeps the
content reachable — the scrub would be theater.

The cost, which the user must accept up front: release tags move to new SHAs, external references
to the old SHAs break, and GitHub Releases built from those tags keep their original commit
metadata. If a tag is a published release, decide deliberately and record the decision. Deleting
the tag remotely (`git push origin :refs/tags/<tag>`) is required for the rewrite to stick — a
stale remote tag re-anchors the old history on the next fetch.

## Protected branches change the order

A protected release branch **rejects** the force-push. Scrub on the integration branch, verify
there, and promote forward through the normal release path. Trying to force-push a protected
branch first and unprotecting it "temporarily" is how a scrub turns into an outage.

## Resources

| File | Contents |
|---|---|
| `reference/filter-repo-recipes.md` | Path removal, content/pattern replacement, mirror-clone workflow, verification commands, common failure modes |
| `reference/coordination.md` | Force-push mechanics, re-clone instructions to send teammates, open-PR handling, post-push GC |
| `reference/leak-response.md` | Rotation checklist and blast-radius assessment for a real leak |
| `scripts/scrub_preview.sh` | Read-only preview: commits, blobs, branches, tags affected by a path or pattern |
| `scripts/scrub_force_push.sh` | The force-push gate — refuses without a verified backup mirror and a typed confirmation |
| `scripts/acceptance_test.sh` | Builds a disposable repo (multi-branch, tagged, local remote), runs the full flow, asserts the result |

## Verifying this skill

`scripts/acceptance_test.sh` creates its own throwaway repo in a temp directory — it never touches
the repo you are working in. It plants a secret across several commits on two branches, tags an
affected commit, then asserts the preview names exactly the right objects, the rewrite empties
`git log --all -- <path>`, unaffected history survives, tags are rewritten, and the push gate
refuses without explicit confirmation. Run it after changing anything in this skill.

## Examples

**"There's an API key in `config/prod.env` from six months ago — scrub it."**
Rotate the key first and confirm the old one is dead. Back up a mirror, preview the affected
commits, get explicit approval, rewrite with `--path config/prod.env --invert-paths`, verify, then
gate the force-push and tell the team to re-clone.

**"Purge `data/dump.sql` from all commits, the repo is 4 GB."**
Not a leak, so no rotation. Same gate: backup, preview (which shows the blob sizes), approval,
rewrite, force-push gate, re-clone. Add `--strip-blobs-bigger-than` if other large blobs turn up.

**"Delete the scratch file I committed yesterday."**
Ordinary deletion. `git rm` and commit — do not rewrite history for tidiness on a shared branch.
