---
name: wave-supervisor
description: Supervise an ENGINEERING BACKLOG wave in the current session; dispatch Omnigent child workers in worktrees, monitor and merge. Fresh session only by explicit request or /wave-kickoff. NOT the task board, one issue, or subagent fan-out.
---

# Wave Supervisor

Supervise a repo's **engineering backlog** in the current session by default. Fresh wave requests make this agent the supervisor; use a separate session only by explicit request or `/wave-kickoff`.

**Backlog means engineering backlog, never the task board** (`human-todo`). See `docs/process/task-vocabulary.md`.

**This file is the decision surface; the mechanics live beside it** (#531) — open the companion at each step:

| Companion | Carries |
|---|---|
| [`planning-defaults.md`](planning-defaults.md) | modes, width, ordering, advance, needs-input |
| [`dispatch-mechanics.md`](dispatch-mechanics.md) | branch cut, bootability preflight, launch, worktree exclusivity, durable logs |
| [`supervision.md`](supervision.md) | liveness model, stall triage, salvage protocol |
| [`asking-the-user.md`](asking-the-user.md) | escalation triggers, queue-vs-ask timing, close-out asks |
| [`worker-brief-template.md`](worker-brief-template.md) | the canonical per-worker brief (#492) |
| [`wave-issue-template.md`](wave-issue-template.md) | the `wave`-labeled issue (#849); the ownership lease (#886/#823) |
| [`wave-state-template.md`](wave-state-template.md) | `WAVE-STATE.md`, the wave's state of record (#569) |
| [`wave-observability.md`](wave-observability.md) | the wave page: bring-up, port resolution, scope (#705/#1136) |
| [`merge-and-closeout.md`](merge-and-closeout.md) | rationale, teardown, process sweep, wave-PR contract |
| [`wave-pr-template.md`](wave-pr-template.md) | the one wave PR: body sections, metadata, status legend (#897) |
| [`retro-miner.md`](retro-miner.md) | close-out mining lenses, issue contract, Slack digest |

**Compose over the substrate — never invent parallel mechanisms** (claims, version bumps, branch topology each have one owner): [`dispatch-mechanics.md`](dispatch-mechanics.md).

## Modes + defaults (override only when the user says so)

**Bounded** (a fixed list of issues) and **unbounded** (pull the next eligible issue until the slice drains or a stop condition fires) share the whole machinery; **wave width 5**, capped by the bootability preflight; **advance auto**, with exception stops. Eligibility, ordering, needs-input, each stop condition: [`planning-defaults.md`](planning-defaults.md).

## Pipeline

### 1. Plan the wave

- **Tooling preflight FIRST (REQUIRED)** — `make wave-preflight`, or `wave-mechanics.sh preflight`. A wave without atomic claims must not run. Details: [`dispatch-mechanics.md`](dispatch-mechanics.md).
- **Bootability preflight before you size the wave (REQUIRED)** — binary presence is not readiness, and an under-strength roster is a plan-time disclosure: [`dispatch-mechanics.md`](dispatch-mechanics.md).
- **Group by conflict surface, not logical dependency** — "no logical dependency" ≠ "no shared file". Issues touching the same files (existing or predictably created, #689) or plugin manifest share a worker or run sequentially.
- **Three pre-dispatch questions, not one** — claimed? an open PR racing it? a **merged** PR that already delivered it? Open is not evidence of undone work, and a merged hit is a read, never an auto-skip (#1846): [`delivered-but-open.md`](delivered-but-open.md). Then claim from inside the worker's worktree, so the sentinel records its branch and not yours (#568): [`dispatch-mechanics.md`](dispatch-mechanics.md).
- **File the wave issue (REQUIRED), before cutting the branch** (#849) — one `wave`-labeled issue from [`wave-issue-template.md`](wave-issue-template.md), carrying the plan and a bare `#N` per cohort issue; `Closes` stays on the wave PR alone.
- **Own the wave (REQUIRED), immediately after filing it** (#886) — `make wave-own ISSUE=<n> WAVE=<name>`. **Exit 3 means a different live supervisor holds it: stop, dispatch nothing, report who** — the #823 P0. Re-run `make wave-guard` before every mutation; write state via `make wave-state-append`.
- **Gate 0 before taking over ANY existing lease (REQUIRED, #1873)** — `make wave-liveness ISSUE=<n>` must read `free` or `dead`. `wave-owner-check`'s `stale` is necessary, never sufficient: a busy supervisor goes stale exactly like a dead one. Read the verdict word, not `make`'s exit: [`wave-issue-template.md`](wave-issue-template.md).

### 2. Cut the wave branch + initialize state (REQUIRED)

- Cut the branch from `make base-ref` (fork-aware, fetched; #1164) and push it — snippet, and why the base is never hand-written: [`dispatch-mechanics.md`](dispatch-mechanics.md). Workers branch **off the wave branch** and PR **into it**, so those PRs do NOT auto-close issues. Topology and hotfix sync: [`merge-and-closeout.md`](merge-and-closeout.md).
- **Then initialize `WAVE-STATE.md` and `.wave/`, before the first dispatch** (#569) — fresh from [`wave-state-template.md`](wave-state-template.md), **overwrite** the previous wave's file, never edit it — supervisor worktrees get reused. Record the wave issue number there.
- **Then open the wave observability page and hand the user its URL (REQUIRED)** (#1136) — bring-up, resolving the URL from the port registry, the page's honest scope, and why a page that will not start is a disclosure rather than a wave blocker: [`wave-observability.md`](wave-observability.md).

### 3. Dispatch — Omnigent child-session workers (primary pattern)

Create workers as Omnigent child sessions (#1081), each on its exclusive worktree. Record `conversation_id` and issue-keyed logs; see [`dispatch-mechanics.md`](dispatch-mechanics.md). Children may die with the parent runner (#1085): commit early and reconcile before resuming.

Gate mode is mandatory when ≥2 in-flight issues land in one plugin.

### 4. Supervise

Liveness is **queried from the dispatch layer, never inferred from worktree state** — "no commits yet" is never death, and a result without a PR URL or a specific blocker is a STALL to nudge. Long runs need a **stall signal** too. States, backstop, nudge, salvage: [`supervision.md`](supervision.md). Long runs (#495) remain supervisor-owned; see [`dispatch-mechanics.md`](dispatch-mechanics.md).

**Keep this session title current:** set `⏳ 🌊 <repo>::<branch>::<date>::wave_supervisor — <summary>` at start; update at milestones, `‼️` when blocked on a human, terminal state at close-out. Rename with `sys_session_rename`.

Record every launch, relaunch, nudge, and park in `WAVE-STATE.md` as it happens. Escalate stalls tool-ready, never silently: [`asking-the-user.md`](asking-the-user.md).

### 5. Merge back (supervisor-serialized)

Merge worker PRs into the wave branch **one same-plugin PR at a time**, each refreshed against the moved branch; cross-plugin PRs merge on arrival. **Review, don't rubber-stamp** — on skill PRs the `description:` frontmatter is behavior (#268). Log every merge in `WAVE-STATE.md`. Rebase rules and rationale: [`merge-and-closeout.md`](merge-and-closeout.md).

### 6. Report + terminate

- Running tally at every checkpoint: merged / in-flight / blocked / needs-input, plus budget spent if capped — **posted as a comment on the wave issue**, not only to the session (#849), with `make wave-heartbeat ISSUE=<n>` (#886). Tally shape: [`status-updates.md`](../communication/references/status-updates.md).
- The wave ends with **ONE PR `wave/<...> → production`**, shaped by [`wave-pr-template.md`](wave-pr-template.md) (#897): the sole `Closes` list, worker-PR links, label and assignee.
- **Close-out is a numbered sequence and every step is REQUIRED** — retro mining ([`retro-miner.md`](retro-miner.md)), the final `periodic-review` pass (#374 — invoke the skill, never duplicate its procedure), the delivered-but-open sweep, the human items **asked** not narrated, the process sweep before *and* after teardown (#644 — deleting a worktree doesn't kill what runs in it), the wave issue closed only after the wave PR merges, then `make wave-release ISSUE=<n>` (#886). Walk it in order, then the `WAVE-STATE.md` close-out checklist: [`merge-and-closeout.md`](merge-and-closeout.md).

## Escalation triggers (pause and ask)

**The whole list** — every other setback is the supervisor's to absorb, and a nudge-clearable stall is not an escalation. An **undiagnosed** repeat failure of the same issue — park it, never implement it yourself (#1021) · an unserializable merge · needs-input is the only work left · cap reached · a `WAVE-STATE.md` branch mismatch at close-out · **a `wave-own` refusal (#886)** · anything touching production outside the wave PR. **How** to ask: [`asking-the-user.md`](asking-the-user.md).
