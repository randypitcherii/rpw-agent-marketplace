---
name: build
description: Build one request through plan, implementation, checks, fresh-context review, and pull request
argument-hint: <request | #issue>
---

# /build — standalone public workflow

Run **plan → claim → worktree → implement → check → review → pull request** using only the files shipped in `rpw-published` and the target repository's own tools. Never assume the target contains the RPW source monorepo or a private plugin.

## Autonomy

Execute end to end and never ask the user to run commands. Stop only when another workspace owns the issue, an unavoidable open-PR conflict exists, scope is genuinely ambiguous, or the user must choose an issue in the no-argument case.

## 1. Resolve scope

- Free text is the build request.
- For `#142` or `142`, read `gh issue view 142 --json title,body` and use its title and body.
- With no arguments, list open issues, present at least two good candidates, and let the user select one.

Capture `ISSUE` when present and a concise `REQUEST`.

## 2. Coordinate

For a real issue:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/build-claim.sh" honor-check "$ISSUE"
```

Exit 3 means another workspace owns it: report the owner and stop. Otherwise:

1. inspect open pull requests against the repository's actual default branch for overlap;
2. if overlap is unavoidable, let the user choose whether to stack, wait, or proceed;
3. claim best-effort with `${CLAUDE_PLUGIN_ROOT}/scripts/build-claim.sh claim "$ISSUE"`.

Skip claims for an untracked free-text request.

## 3. Create or reuse a worktree

Reuse the current feature worktree when already in one. Otherwise resolve and fetch the upstream default branch with the shipped helper:

```bash
BASE=$(source "${CLAUDE_PLUGIN_ROOT}/scripts/git-base-branch.sh" && base_ref)
git worktree add "../<short-slug>-${ISSUE:-work}" -b "feat/<short-slug>-${ISSUE:-work}" "$BASE"
```

Never branch from an unfetched local default or hard-code `main`/`production`. Create the branch and worktree in one step.

## 4. Build

1. Read the target repository's agent guidance and determine its real check command.
2. Write a short plan with file ownership and acceptance criteria.
3. Dispatch one `rpw-published:build-worker` with `isolation: "worktree"`, the absolute worktree path, request, issue, constraints, and check command. Use additional workers only for disjoint ownership.
4. Verify every claimed commit and ensure the worktree is clean, as required by the `subagent-dispatch` skill.
5. Run the target repository's check command yourself.
6. Dispatch `rpw-published:reviewer` against the complete diff. Its fail-closed `no-go` verdict blocks merge; do **not** merge by hand.
7. Fix valid findings, rerun checks and review, then push and open a PR with **What / Why / Verification**. Follow the target repository's merge policy; do not auto-merge unless that policy explicitly permits it.

If the Agent tool is unavailable in the current harness, perform the same steps directly instead of pretending a dispatch occurred.

## 5. Validate and report

Require the human path for a net-new user-facing surface unless the target repository explicitly defines another policy. For deterministic refactors, removals, docs, regression-tested bug fixes, or internal library / runtime code with no user-facing surface and full deterministic tests, green gates and review can be sufficient.

For a complete issue, use `Closes #N`. For partial work, use `Part of #N` or `Advances #N` and leave the issue open.

Report:

- request and issue;
- branch/worktree and commit;
- check command and result;
- reviewer PASS/FAIL and findings;
- PR URL or precise blocker;
- whether human validation remains.

Open the report with the five-state status line ([`../skills/communication/references/status-updates.md`](../skills/communication/references/status-updates.md)) — `DONE`, `FAILED`, or `STOPPED`, never a progress-shaped line.

End with one line: what was built, where it is, and the go/no-go verdict.
