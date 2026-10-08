# Coordinating a history rewrite

A rewrite is a social operation as much as a technical one. Every SHA on the affected branches
changes, so every clone, worktree, open PR, and CI cache disagrees with the remote the moment the
force-push lands.

## Before the force-push

- **Announce it.** Name the repo, the branches, the window, and what people must do. Nobody should
  push during the window; anything pushed after the mirror was taken is *not* in the rewrite and
  will be clobbered.
- **Inventory who is affected.** Teammates with clones, agent worktrees, CI runners with cached
  checkouts, deploy jobs pinned to a SHA, submodule consumers pinning a SHA, release automation.
- **Check branch protection.** A protected branch rejects a force-push. Do the rewrite on the
  integration branch and promote forward through the normal release path rather than unprotecting
  the release branch.
- **Freeze or land open PRs.** A PR whose base was rewritten shows a nonsensical diff. Either land
  it before the rewrite or accept that it needs a rebase after.
- **Confirm the backup mirror exists** and has a non-zero commit count. It is the only undo.

## After the force-push

Send this, verbatim, to everyone with a clone:

> `<repo>` history was rewritten on `<branch>` on `<date>`. Every commit SHA changed.
> **Re-clone.** Do not `git pull` — a pull will merge the old history back in and undo the scrub.
>
> ```bash
> # save any unpushed work first
> git -C <old-clone> format-patch origin/<branch> -o /tmp/my-unpushed
> # then
> git clone <url> <fresh-clone>
> # replay your patches onto the rewritten branch
> git -C <fresh-clone> am /tmp/my-unpushed/*.patch
> ```
>
> Delete the old clone once you have re-applied your work. Its objects still contain the scrubbed
> content.

`git pull` is the specific hazard: it merges pre-rewrite history back into the branch and a
subsequent push reintroduces every scrubbed blob. Say so explicitly — people will try it.

## Open PRs

- PRs from branches that were part of the rewrite: their base moved, so they need
  `git rebase --onto <new-base> <old-base> <branch>` from a fresh clone, or to be reopened from
  re-created branches.
- PRs whose head branch contained the scrubbed content: the content is still in the PR's own diff
  view and comments even after the branch is rewritten. Close the PR if that matters.
- Draft/stale branches nobody rebases will keep the old objects alive on the remote. Delete them, or
  the scrub is incomplete.

## Submodules and pinned SHAs

Anything that pins a commit SHA — submodules, lockfiles referencing a git URL, IaC modules, deploy
manifests, docs linking `/commit/<sha>` — breaks. Grep for the old SHAs and repoint them.

## Forks

A fork keeps its own objects. On GitHub, forks share an object store, so an old commit stays
reachable by SHA through the fork network even after the source repo is rewritten. Rewriting the
source does not clean the forks:

1. Ask each fork owner to re-fork or rewrite.
2. For genuinely sensitive content, ask GitHub Support to garbage-collect the repository network so
   the unreferenced objects stop resolving.
3. Assume, in the meantime, that the content is still retrievable.

## After the dust settles

- Re-run the preview against the rewritten remote from a *fresh* clone; a preview on a stale local
  copy proves nothing.
- Add a guard so it does not recur: a `.gitignore` entry, a pre-commit secret scan, or a CI check.
  A scrub without a guard is a scrub you will run again.
- Record what was scrubbed, when, and what was rotated. The one thing you must not record is the
  scrubbed value itself.
