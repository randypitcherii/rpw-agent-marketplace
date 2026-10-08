---
name: wave-kickoff
description: Fresh waves default to current-session supervision via wave-supervisor. Launch a separate durable supervisor only when explicitly requested or invoked as /wave-kickoff. NOT for single-issue dispatch.
---

# Wave Kickoff

Fresh wave requests run `wave-supervisor` in the current session. This kickoff
flow is opt-in: only use it for an explicitly requested independent session or
`/wave-kickoff`. The supervisor still uses Omnigent child sessions for workers.

**Composition boundary:** this skill owns the brief and spawn/verify choreography;
wave planning and merge discipline belong to `wave-supervisor`. See
[reference.md](reference.md).

Single-issue dispatch and session lifecycle belong to **`dispatch-launch`**;
this skill launches a *supervisor only on explicit request*. Omnigent is the
substrate throughout (ADR-2026-08-14): plain `git worktree add`; liveness is
session history, not workspace APIs or `lsof`.

Run the whole flow with **no follow-up questions** beyond scope input (seeds,
ordering, caps) the user volunteers. That silence is about *kickoff*, not the
wave: the supervisor later drains its queued decisions through `AskUserQuestion`
(wave-supervisor's `asking-the-user.md`), which is why the brief tells it to queue
them tool-ready.

## Gate 0 — Is this work already leased? (MANDATORY — #1873)

`make wave-liveness ISSUE=<n>` for each `wave: owned` issue. To take over that
wave's issues, only `free`/`dead` may dispatch; `live`, `at-risk` and `unknown`
mean **STOP** (ask on `unknown`). Leases are **per wave**: a live one never
blocks a new wave with disjoint issues (#2029). Read the verdict word, not `make`'s exit. Mechanism:
`docs/process/wave-liveness.md`.

## Step 1 — Orient briefly

- `gh issue list --state open` for the backlog; note issues labeled
  `status: in-progress` — they become the brief's **skip-list** (claimed
  in-flight elsewhere).
- Mode: default is **unbounded** — the supervisor drains the backlog by its own
  judgment until only needs-input items remain. Issues, ordering, or a stop cap
  the user named become **explicit-seeds** input. Don't interrogate; take what
  was volunteered.
- Pick the slug and a short `<wave-summary>` now. The wave branch is
  `wave/<YYYY-MM-DD>-<slug>`; the summary goes in the session title and the
  initial pointer before the branch exists. Supervisor title: `⏳ 🌊`; preserve
  🌊 on state flips. See the convention (`docs/process/agent-session-titles.md`).

## Step 2 — Create the supervisor worktree (explicit fresh-session requests only)

```bash
cd <main-checkout> && make base-worktree \
  PATH_=<worktrees-root>/wave_supervisor-<YYYY-MM-DD>_<slug> \
  BRANCH=wave-supervisor/<YYYY-MM-DD>-<slug>
```

> **Base = the fetched upstream default branch (#1164)**, resolved by
> `plugins/rpw-published/scripts/git-base-branch.sh` (`make base-ref`) — never a
> local ref, never a hardcoded branch. On exit 3 run the `git remote add upstream …`
> command it prints; do not fall back to `origin`.

The supervisor cuts the *wave* branch itself (`wave-supervisor` Step 2), so this
worktree lands on a `wave-supervisor/…` branch. Provision gitignored env files
into it if the wave's issues need them (#496 recipe: `dispatch-launch`'s
`dispatch-mechanics.md`).

**Step 2b — no `sys_session_create`:** use `dispatch-launch`'s path A
(`POST /v1/sessions` in bind mode, then the wake event) — it binds this worktree
directly, so the relocation block below is unnecessary. This path is only for an
explicitly requested independent supervisor; ordinary fresh wave requests run
`wave-supervisor` in the current session.

## Step 3 — Write the brief as a FILE in the worktree

**Never a long `--prompt`** — long prompts spawn-die. Write `WAVE-BRIEF.md` into
the worktree root from the canonical template in [reference.md](reference.md).
Beyond the wave content — plus the **Step 0 relocation block** (below) on Step 4's
fallback path — it MUST contain:

1. **Invoke the `wave-supervisor` skill first** and follow it exactly.
2. **Read the #260 retros** (`gh issue view 260 --comments`) before dispatching.
3. **Mode block** — the unbounded directive, or the explicit seed list + ordering.
4. **Skip-list** of in-flight claims from Step 1, plus the standing rule: run
   `make build-honor-check ISSUE=<n>` **live before every claim** — orientation
   staleness is why the skip-list alone is not enough.
5. **Topology**: cut `wave/<date>-<slug>` off `origin/production`; workers PR
   into the wave branch in Gate mode; supervisor serializes merges; the wave ends
   with ONE `wave/... → production` PR carrying the full `Closes` list.
6. **State + artifacts (#569/#570)**: **before the first dispatch**, initialize
   `WAVE-STATE.md` fresh from `wave-state-template.md` and create `.wave/` for
   worker logs — an **overwrite**, since supervisor worktrees are reused.
7. **Worker execution rules**: env files into each worker worktree (#496); no
   backgrounded live run at turn end (#495); anything outliving a worker is
   supervisor-owned, watched with a log-growth stall timeout (#497).
8. **Hard boundary — public publishing is NEVER in a wave's scope.** No
   `make publish-promote`, no `published/<target>` PRs, and no public-target delivery PRs.
   A backlog issue that requires publishing gets parked needs-input.
9. **Retro**: post a retro comment on #260 when the wave ends.

### The Step 0 relocation block — fallback path only (#795)

**Path B inherits its parent session's cwd**, cannot be given one, and resets to it
after every Bash call, so one `cd` never sticks. Its brief must name the worktree's
absolute path and prefix every command with `cd <worktree> &&`
([reference.md](reference.md)); without it the wave runs in the *previous* wave's
worktree.

**Omit it on path A** — a bound workspace *is* the cwd, and persists (#739).

### Step 3b — Pre-dispatch write probe (MANDATORY — #1777)

Prove this host can write **before** you launch anything. `make host-preflight`
asserts the runner's `claude-home-unattended` override; then launch a throwaway
one-tool session that **Edits a scratch file** and require the matching
`tool_result` back. On a managed-policy host every permission flag is a silent
no-op and the prompt renders in an unattached pane (wave 2026-09-13). **A wedged probe means
refuse to dispatch the fleet.** Mechanics:
[reference.md](reference.md). Wedge signature: `dispatch-launch`'s
`liveness-and-surfacing.md`.

## Step 4 — Launch on path A: `POST /v1/sessions` bind mode + wake

**Path A is the default, and the only path that can pre-grant permissions (#1760):**
`host_id`, `workspace` (the Step 2 worktree), `git.existing_worktree: true`,
`terminal_launch_args: ["--permission-mode","bypassPermissions"]` — `acceptEdits` gates
edit tools only, wedging on the first `mcp__omnigent__sys_*` call (#1761). **Create, then
wake with `make session-wake`** (create only seeds history; it re-posts on the Settings
Error race, #2030). Payload and probe: [reference.md](reference.md).

Resolve the `claude-native` builtin's `agent_id`. Use [reference.md](reference.md)
to file a unique matching project before wake; path B cannot. Repeat the short
summary in the pointer, name `WAVE-BRIEF.md`, and instruct: read out-of-tree files
with Bash `cat`/`sed`, not `Read` (#1760).

### Fallback — no reachable REST port

`sys_session_create` takes no `workspace`, `git` or `terminal_launch_args`: no pre-grants,
no bound cwd, Step 0 mandatory, first out-of-scope call wedges it (#972).

```
sys_session_create(
  agent_id = <the claude-native builtin from sys_agent_list>,
  title    = "⏳ 🌊 <repo>::wave/<date>-<slug>::<date>::wave_supervisor — <wave-summary>",
  message  = "<wave-summary>. cd <worktree> first — that is your worktree, not the
              directory you start in. Then read WAVE-BRIEF.md in that worktree's
              root and execute it exactly.")
```

## Step 5 — Liveness gate (MANDATORY — no created-and-hope)

**Both paths return `status: "idle"`** — created, not working (#974). A never-started
session and one polled too early look identical; path A adds a third look-alike, un-woken
with only the seed message — **re-post the event, do not relaunch.**

1. `sys_session_get_info(session_id=…)` → `running`, then `idle`.
2. `sys_session_get_history(conversation_id=…)` → **the real gate.** Real `function_call`
   items doing the brief's work, or it is not alive. A seed-only history is not liveness.
3. First progress: `git ls-remote origin 'wave/*'`.

**Dead-spawn signature:** `status: failed`, or frozen at the user message with
`runner_online: false` — not the managed-policy stall (`running`, mid-`tool_use`, no
`tool_result`), which no relaunch fixes (#1777), nor the #2030 wake race (`failed`
on `Settings Error`: re-wake). Relaunch once on the same brief;
**twice-dead ⇒ stop looping**, flip the title's ⏳ to ❌ (or ‼️ if alive but parked on a
decision), keep 🌊, and report.

Note: a **path-B** child nulls its own `workspace`, `git_branch`, `model` and `host_id`;
read the **parent's** (path A carries a real bound one).

## Step 6 — Surface the session

No terminal to focus: the session lives in the omnigent rail under its
`conversation_id` and title — report both. Drive it with `sys_session_send`.

## Step 7 — Report

- Worktree path and **both** branches: the worktree's
  `wave-supervisor/<date>-<slug>` and the `wave/<date>-<slug>` the supervisor
  cuts.
- Session `conversation_id` + the structured title.
- Brief location (`<worktree>/WAVE-BRIEF.md`) and what the supervisor was seeded
  with (unbounded, or the seed list + skip-list).
- **Liveness evidence** — the actual history probe (tool calls observed), not
  "created ok".
- Cleanup: `sys_session_close(<conversation_id>)`, then
  `git worktree remove <path>` and branch pruning.

## Hard boundaries

- **Do not run the wave yourself** — this skill ends when the supervisor is
  verified alive. While it lives, supervising, merging worker PRs, and reaping
  are its job.
- **Never merge the wave PR — you did not open it.** The author owns the merge
  (root AGENTS.md, #1878). Supervisor dead with the PR open: relaunch it into
  the same worktree with a salvage brief so *it* finishes. Idle: wake it. Never
  hand a green PR to the human as "awaiting your merge".
- **Publishing to the public mirror is never in a wave's scope** — enforce it in
  every brief you write, and never "helpfully" add it to one.
