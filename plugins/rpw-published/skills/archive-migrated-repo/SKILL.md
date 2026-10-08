---
name: archive-migrated-repo
description: Retire a source repository whose content has moved elsewhere — verify the migration is genuinely complete, close and forward its open issues to their new homes, disable issues, then archive. Use when a repo has been merged into a monorepo or superseded, and when the user says "archive that repo", "retire the old repo", "we migrated this, shut it down", or asks for the disposition of a source repo after a subtree merge. NOT for deleting a repo, and not for one that has no verified new home.
---

# Archiving a migrated repo

Archiving is a one-way door in practice even though GitHub lets you reverse it: the moment the repo is read-only, anything still living there stops being maintainable, and open issues become invisible to the tracker that inherited the work. So the whole procedure is front-loaded with verification, and the destructive steps come last and in a fixed order.

**The rule: never archive on the strength of "we migrated it." Verify the new home holds the content, and verify nothing arrived since the last time anyone looked.**

## Phase 1 — mechanical preconditions

Cheap, scripted, deterministic. Run these first and stop on any failure; there is no reason to spend judgment on a repo that fails a mechanical check.

```bash
REPO=owner/name
gh repo view "$REPO" --json isArchived,hasIssuesEnabled,forkCount,pushedAt,visibility
echo "open issues: $(gh issue list --repo "$REPO" --state open  --limit 200 --json number -q 'length')"
echo "open PRs:    $(gh pr    list --repo "$REPO" --state open  --limit 100 --json number -q 'length')"
gh issue list --repo "$REPO" --state open --limit 200 --json number,title,updatedAt
gh release list --repo "$REPO" --limit 10
```

Read the results against these gates:

| Signal | Blocks archiving when |
|---|---|
| Open PRs | Any exist. Archiving strands unmerged work with no path to land it. |
| Forks | Any exist. Archiving is visible to forks and may strand collaborators — confirm with the owner first. |
| Pushes after the migration commit | Work landed in the source *after* the migration, so the new home is already behind. |
| Releases or tags consumers install from | Something depends on this repo as a distribution point. |
| Open issues | Not a blocker, but every one must be forwarded in Phase 3. |

**Freshness check.** Compare the source's last push against the migration date. A push after the migration means the two diverged, and the delta must be reconciled before anything is archived.

## Phase 2 — verify the content actually landed

Only if Phase 1 passes. This is the judgment step, and it is the one people skip.

- The new home contains the code, and its history is present in whatever form the migration intended (preserved, squashed, or subtree-flattened — the intent matters more than the shape).
- Nothing lives only in the source: CI config, issue templates, wiki, releases, branch protection, deploy keys, secrets, webhooks.
- Search the wider surface for references that will break: other repos, docs, bookmarks, scripts, LaunchAgents, and local checkouts that still point at the source path.

If the migration intent was recorded in an issue or ADR, read it and check the actual outcome against it rather than against your assumptions.

## Phase 3 — forward the open issues

Every open issue gets a home before the tracker goes read-only. For each one, decide:

- **Already covered** in the new home → close with a comment linking the covering issue.
- **Still wanted** → recreate it in the new home, then close the original with a link to the replacement. Cross-repo links must be fully qualified (`owner/repo#N`); bare `#N` silently resolves to an unrelated local issue.
- **No longer wanted** → close with a one-line reason. Say why, so a future reader does not have to reconstruct it.

Follow `issue-creation` for anything recreated in the new home.

Leave a short migration note as the final comment on each closed issue. The forwarding link is the entire point of this phase — an archived tracker full of issues that just say "closed" destroys the trail.

## Phase 4 — the irreversible steps, in order

Order matters. Disabling issues before archiving prevents a race where something new is filed against a repo that is about to go read-only.

```bash
# 1. Record where everything went, in the source README or a final commit.
# 2. Disable the issue tracker.
gh api -X PATCH "repos/$REPO" -F has_issues=false

# 3. Archive.
gh repo archive "$REPO" --yes
```

Before running these, state plainly what is about to happen and confirm with the owner. `gh repo archive` is reversible through `gh repo unarchive`, but everything Phase 3 closed stays closed.

## What to record

The disposition belongs somewhere durable in the *new* home — an ADR, a `docs/decisions/` note, or the migration issue. Record the source repo, the migration commit or PR, the date, where the issues went, and anything deliberately abandoned. A future audit that finds an archived repo with no recorded disposition will reopen the question you just closed.

## When not to archive

- The content has no verified new home. Archiving is the last step of a migration, never a substitute for finishing one.
- Ownership is unsettled — a work-owned repo being folded into a personal one, or the reverse, is a placement decision that must be made and recorded first.
- Anything still installs from, deploys from, or authenticates against the repo.
