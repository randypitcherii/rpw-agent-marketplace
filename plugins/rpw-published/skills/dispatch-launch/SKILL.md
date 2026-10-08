---
name: dispatch-launch
description: Use to file a GitHub issue and dispatch it to a fresh agent in its own git worktree as a durable omnigent session, dispatch an existing issue as the next task, or manage a dispatched session — rename, close, tear down the worktree, self-terminate. Trigger on "file a github issue and dispatch it", "spin up an agent to fix X", "dispatch the next task", "delegate this to a fresh agent", or "clean up my worktree". NOT a multi-issue wave (wave-supervisor) or a wave supervisor (wave-kickoff).
---

# Dispatch Launch Skill

Turn work into a GitHub issue plus a fresh isolated git worktree with an agent already
running in it as a **durable omnigent session** — one that outlives the window that
started it. Named for the function, not the substrate: the substrate moved once already
(Superset → omnigent, ADR-2026-08-14 (Omnigent dispatch)).

**This file is the decision surface; the mechanics live beside it** (#592) — open a
companion when you reach its step:

| Companion | Carries |
|---|---|
| [`dispatch-mechanics.md`](dispatch-mechanics.md) | the three launch paths, worktree, env provisioning, brief-file pattern, host/agent resolution |
| [`liveness-and-surfacing.md`](liveness-and-surfacing.md) | the wake call, the Step 5 gate, probes that lie, relaunch, surfacing |
| [`session-lifecycle.md`](session-lifecycle.md) | where you are, rename, close, teardown, self-termination |
| [`reference.md`](reference.md) | full REST/tool surface, measured behavior, Superset→omnigent mapping, parity gaps |
| [`hand-back-template.md`](hand-back-template.md) | for an orchestrator handing a "go dispatch this" ask back to this skill (#1802) |

## When to invoke

See the frontmatter triggers. Rename / close / clean-up → [`session-lifecycle.md`](session-lifecycle.md).
Already have an issue number → [Next-task fast path](#next-task-fast-path-dispatch-an-existing-issue).
Skip when the user just wants an issue (use `gh`) or the fix is quick inline.

**Scope boundary:** *single* dispatches (one issue, or a few sequentially) plus session
lifecycle. A **multi-issue wave** is **wave-supervisor**; launching a durable
supervisor for one is **wave-kickoff**.

## Step 1 — Pick a launch path

Three exist. Which one you have decides the brief's shape, so decide first
([`dispatch-mechanics.md`](dispatch-mechanics.md)):

| Path | Available when | Binds a worktree? |
|---|---|---|
| **A — `POST /v1/sessions` + wake** (default) | `api GET /v1/hosts` (omni-api.sh) answers | **yes** — `workspace` + `git.existing_worktree` |
| **B — `sys_session_create`** | you're inside an omnigent turn | no — child inherits the *parent's* cwd (#795) |
| **C — `omni <harness>` under tmux** | `omni --version` works | via `tmux -c` only |

Path A is the default: the only one that binds a pre-staged worktree *and* sets a
structured title at creation. **No online host ⇒ do not dispatch** — a session against
a dead runner looks created and never works; judge health only by `status: online`.
With no path at all, fall back to the Agent
tool or headless `claude -p` (`wave-supervisor` `dispatch-mechanics.md`) and say so.

## Step 2 — Scope + delivery mode

Defaults: repo = current project's (`gh repo view --json nameWithOwner`); title
prefixed with component; `priority: P2`; `type: bug|feature|task` + `app: <name>`
labels documented by the target repository. Decide **delivery mode** now (Gate vs Autonomous) — it shapes the brief's
last line.

## Step 3 — File the issue

Body must let the agent work with no back-channel context: **Scope**, **Target
file(s)** (paths + lines), **Recommended approach**, **Acceptance**, **Related**
(`#N`). `gh issue create` with a HEREDOC `--body`; capture the number from the URL.

## Step 4 — Worktree, brief, launch

Full commands for all three paths: [`dispatch-mechanics.md`](dispatch-mechanics.md).
Four decisions are yours before you run them:

- **Branch + base** — `fix/` for bugs, `feat/` for features, off the fetched upstream default branch. Nothing rewrites the name you pass.
- **The brief is a FILE, always.** Long prompts spawn-die, and a brief on disk
  survives a relaunch. Choose `<work-summary>` from the issue title or request,
  put it first in the one-line pointer, and repeat it in the creation title.
- **A Step 0 relocation block is needed only on path B.** Paths A and C bind cwd to
  the worktree (measured — [`reference.md`](reference.md)); path B has no `workspace`
  field, so its brief must carry the block or the child works in the parent's tree.
- **Env files** — a fresh worktree carries no gitignored `.env` / `dev.env`;
  provision them before the agent runs (#496).
- **Permissions, for an unattended launch** — supervisor-grade sessions take
  `terminal_launch_args: ["--permission-mode","bypassPermissions"]` (path A) or
  `--dangerously-skip-permissions` (path C). `acceptEdits` is not enough: it gates edit
  tools only, so the session still wedges on its first `mcp__omnigent__sys_*` call with
  nobody to answer (#1761). A managed-policy host makes every one of these flags a silent
  no-op — Step 1's host check and the write probe are what prove otherwise (#1777).

**On path A the launch is two calls, never one** — `POST /v1/sessions` then
`POST /v1/sessions/{id}/events`. A runner binds asynchronously, so at create time
`initial_items` is persisted as a *history-only seed* and **nothing executes**; the
session sits `idle` looking exactly like a healthy one. The seed and wake details
are in [`dispatch-mechanics.md`](dispatch-mechanics.md).

## Step 5 — Verify the agent is running (MANDATORY GATE)

A created session reports `status: "idle"`, which means **created, not working** (#974).
The gate is the session's own history: real `function_call` items, or it is not alive.
A history holding only the seed message is not liveness. Probe commands, the probes
that lie, and relaunch-in-place: [`liveness-and-surfacing.md`](liveness-and-surfacing.md).

**Never skip this** — "dispatched" is not "running".

## Step 6 — Surface the session

There is no pane to focus. The session lives in the omnigent rail addressed by
`conversation_id`; hand over that id **and** the structured title, plus
`omnigent attach <conversation_id>` for a TTY. Titles carry a **state-emoji prefix**
(⏳ at launch, flipped at close-out) — one table, in
the session-title convention (`docs/process/agent-session-titles.md`).

## Step 7 — Report back

Issue #+URL, worktree path, branch, `conversation_id` + title, **delivery mode**, Step
5 evidence (tool calls actually observed — not "dispatched ok"), claim state, and
teardown commands from [`session-lifecycle.md`](session-lifecycle.md). Open the report with the five-state status line ([`../communication/references/status-updates.md`](../communication/references/status-updates.md)).

## Next-task fast path (dispatch an existing issue)

Work that's **already an issue** skips the authoring ceremony — Steps 2–3 collapse;
goal/approach/test come from the issue body (`gh issue view $ISSUE`). **Reuse the
previous dispatch's choices as defaults** (launch path, host, agent, model, base
branch, delivery mode) — carry them forward silently, re-confirm only changes. Then run
Steps 4–7 as normal (**never skip the Step 5 gate**). Claim before each launch:

```bash
make build-honor-check ISSUE=$ISSUE   # MANDATORY — already claimed elsewhere?
make build-claim ISSUE=$ISSUE         # pre-claim: close the spawn→build-init window
```

Claim **from inside the new worktree**, not from yours — the sentinel records the
branch of the worktree it runs in, and a claim stamped with your branch makes the
worker's own honor-check say `claimed-by-other` (#568).

**Dispatch the next N from the backlog** (`gh issue list --label "priority: P1" -L <N>`):
run the honor-check **live, right before each launch, not once up front** — orientation
goes stale mid-batch, so **skip** any issue that comes back freshly claimed. Keep N
small and sequential; a parallel wave is **wave-supervisor**.

## Delivery mode (gate vs autonomous)

A dispatched headless agent runs with no human, so the brief is the **only** merge
gate — it self-certifies and (no branch protection) auto-merges unattended
(mechanism: [reference.md](reference.md)). **Gate (default):** brief ends "open a PR,
then STOP". **Autonomous:** "open a PR and merge". State the mode in Step 7.

The dispatched agent's `make build-init` also **auto-claims** once `/build` reaches
planning, so the pre-claim above only closes the spawn→init window (label is
`status: in-progress`, NOT bare `in-progress`). Local sibling-worktree work stays
invisible to `gh issue list` until pushed.

## Failure modes

Full catalog — nine of them, each earned: [`failure-modes.md`](failure-modes.md). Two
are decisions, not diagnoses, so they stay here: on path A the launch is **both calls,
always**, and a session that dies **twice ⇒ stop looping** and report.
