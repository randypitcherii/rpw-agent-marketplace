---
name: build
description: Full lifecycle build — thin Claude-Code host adapter over the harness-neutral `rpw build` graph executor
argument-hint: <request | #issue>
---

# /build — graph-driven lifecycle build

`/build` runs the full development lifecycle — **plan → dispatch workers → integrate → check → review → merge → finalize** — through the **harness-neutral runtime executor**: the LangGraph `build_graph`, invoked via `rpw build --live`. The lifecycle is owned by `libs/rpw_runtime`, **not** by this prompt.

**This command is the thin Claude-Code host adapter.** It does four things and nothing more: resolve scope, run the fleet-coordination preamble, create/enter the worktree, invoke the executor, and report. **Do NOT re-implement any build phase here — the graph does it.**

> Migration note (#146 / #202): this replaced the legacy 684-line markdown ritual. The runtime graph is the single source of truth for the build lifecycle and is evaluated independently of any plugin (`make runtime-test`, `rpw build`). To recover the old ritual: `git revert` the flip commit.

## Autonomy
Execute end-to-end without pausing for confirmation, and do the work yourself — never ask the user to run commands. The runtime drives the build; your job is the preamble + invocation + an honest report. The only legitimate stops: (1) the coordination preamble finds the issue **claimed by another workspace** (skip — don't double-pick), (2) a Phase-0 scan finds an **unavoidable open-PR conflict**, (3) **genuinely ambiguous scope** with no safe default, (4) the no-args issue pick (below).

## Step 1 — Resolve scope
From everything typed after `/build`:
- **Free text** (`/build add a retry to the client`) → that text is the build **request**; set the issue only if one is clearly named.
- **An issue ref** (`/build #142` or `/build 142`) → `gh issue view <N> --json title,body`; the request is the title + body; the issue id is `N`.
- **No arguments** → `gh issue list --state open` for ready work, present **2+ candidate issues** each with a one-line rationale, and let the user pick **one** (the executor builds one issue per run). This is the only pre-build pause in the no-args case.

Capture `ISSUE` (the number, or empty for an untracked free-text build) and `REQUEST` (the scope text).

## Step 2 — Coordination preamble (shared claim ledger)
Parallel workspaces (Superset, other Claude sessions, CI) coordinate through a shared GitHub-Issues claim ledger via the harness-neutral `rpw` surface — the lifecycle graph itself never coordinates. When `ISSUE` is a real GitHub issue:

1. **Honor-check** — `uv run --project libs/rpw_runtime python -m rpw_runtime.cli honor-check --issue <ISSUE>`. **Exit 3 = claimed by another workspace**: surface its branch/timestamp and **STOP**. `clear` / `own-claim` / `unsentineled` → proceed.
2. **Overlap scan** — `gh pr list --state open --base <default-branch> --json number,title,headRefName,files` (this repo's default is `production`). If the planned scope overlaps an open PR's files, surface it and let the user choose (merge that PR first / stack on it / proceed).
3. **Claim** — `uv run --project libs/rpw_runtime python -m rpw_runtime.cli claim --issue <ISSUE>` (best-effort; applies the `status: in-progress` label + posts the claim comment).

(Skip honor-check/claim for an untracked free-text build with no issue.)

## Step 3 — Worktree
- If you are **already inside a feature worktree** (e.g. a Superset workspace on a `feat/*` or `superset/*` branch), use it.
- Otherwise create one from the default branch: `git worktree add ../<short-slug>-<ISSUE> -b feat/<short-slug>-<ISSUE> <default-branch>` (or `EnterWorktree` if available). All build work happens in that worktree.

## Step 4 — Invoke the executor
Run the runtime build, rooted at the worktree. The Databricks workspace pool (429 resilience) comes from `RPW_DATABRICKS_POOL` — comma-separated, distinct-host `databricks` profiles (from `.env` or your shell); it falls back to the single default workspace if unset.

```bash
RPW_DATABRICKS_POOL="${RPW_DATABRICKS_POOL:-DEFAULT}" \
  uv run --project libs/rpw_runtime python -m rpw_runtime.cli \
  build --live --issue "<ISSUE>" --request "<REQUEST>" --worktree "<WORKTREE_PATH>"
```

(Omit `--issue` for an untracked free-text build.) This runs the **entire lifecycle**: plan → dispatch build workers (real red→green) → integrate → run the project gate → security / simplification / docs review → and, **on a clean review**, create + squash-merge the PR to the default branch, then finalize. It is a long-running autonomous subprocess — **run it in the background and wait for it to finish**; it prints the final `BuildState` as JSON on completion.

## Step 5 — Report + hand-off
Parse the printed final `BuildState` and report it plainly:
- `phase`, `finalized`, `merge_status`, `pr_url`
- `check_results.passed` (the project gate)
- the `security-review` receipt: `go` / `no-go`
- per-task `result.status` + `files_changed`

**If the review returned `no-go`** (`merge_status: blocked`): the merge was **deliberately skipped** (fail-closed). Surface the blocking findings and the `stall_recovery` note — the work is on the feature branch for follow-up; do **not** merge it by hand. Receipts are written under `<WORKTREE>/.rpw/build/receipts/`.

End with a one-line hand-off: **what** built, **where** (PR url / branch), and the **go/no-go**.
