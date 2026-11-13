---
name: upstream-contribution
description: Contribute to a third-party repo you have a fork of — file the issue in their shape, cut the branch from the fetched upstream default (never local HEAD or the fork's default), pass their DCO and pre-commit, capture a sandboxed demo, open the PR against upstream. Trigger on "contribute to <upstream repo>", "open a PR against omnigent", "file this upstream", "PR to a repo I forked". NOT for repos you own, or closing superseded work (oss-contribution-closeout).
---

# Contributing upstream from a fork

Scope starts where a fork exists. Filing shape and the owned/external fork belong to the `issue-creation` skill; this skill adds the fork/upstream topology, where the silent failures live. Recipes: [reference.md](reference.md). Worked example: [omnigent-ai/omnigent#4240](https://github.com/omnigent-ai/omnigent/issues/4240) → [#4242](https://github.com/omnigent-ai/omnigent/pull/4242).

## Consent first

Upstream is public and not yours, so every issue, comment, push and PR there is outward-facing. **The human names the destination; you never opt yourself in.** `destination_preflight.py` refuses a public target until the human sets `RPW_DESTINATION_OPT_IN=<owner/repo>` — an agent setting it re-creates the incident it guards (#797). No consent → draft locally and stop.

## Hard rule — branch from the fetched `upstream/<default>`

Never `git checkout -b` from HEAD or the fork's default. The fork's `main` is a snapshot of your last sync; your checkout is often parked on an unrelated branch. Either yields a PR carrying others' merged work, or conflicting on arrival — a wasted maintainer review.

```bash
S="$CLAUDE_PLUGIN_ROOT/scripts/git-base-branch.sh"
"$S" worktree ../<repo>-<slug> <branch>
cd ../<repo>-<slug> && git log --oneline "$("$S" ref --no-fetch)"..HEAD   # must print nothing
```

The helper detects the fork, resolves the **parent's** default branch, fetches, then `git worktree add -b` in one step — your current checkout is untouched. Exit 3 = no remote for the parent: run the `git remote add` it prints. By hand: `git fetch upstream && git worktree add <dir> -b <branch> upstream/<default>`.

## Issue

Run `issue-creation` (dedupe, binding forms, labels). The fork-specific deltas:

- **Dedupe against history.** `--state all`, twice, different vocabulary — then **read the code**: an open request, a closed-as-shipped opposite and a stale PR can all coexist. Comment on the prior issue to cross-reference; never file silently on top.
- **Forms are binding.** `blank_issues_enabled: false` + a `.yml` form → fill its fields as headings, in order.
- **Labels only from `gh label list`.** Forms declare labels the repo lacks; `gh issue create` hard-fails on them. Triage bot present → pass none.

## Commit and test

- **Their conventions.** DCO: `git commit -s`, then print the trailer and read the name. Match their message style.
- **Their pre-commit, made runnable.** A fresh worktree has no `.venv`/`node_modules`; absent tooling reads exactly like a real failure. Recipe in reference.md.
- **Baseline or mine?** Before reporting any failure, re-run the same file on a pristine upstream worktree. Same failure there → baseline: say so in the PR, never ship a workaround for *your* environment into *their* tree.

## Demo and PR

- **Demo honestly.** Run their app against a **sandboxed** data dir and seeded fixtures so no real data reaches a public PR; capture per the `demo-capture` skill.
- **Images from the CLI.** `gh` cannot attach files: push PNGs to an assets ref on your fork via the API, embed raw URLs (reference.md).
- **Their template, every section.** Run their checks, re-assert the base is fresh, `gh pr create --repo <upstream> --head <you>:<branch>`.
