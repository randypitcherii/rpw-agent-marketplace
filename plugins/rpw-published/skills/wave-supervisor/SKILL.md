---
name: wave-supervisor
description: Supervise a multi-issue wave — batch-dispatch backlog issues to parallel workers in superset workspaces, monitor liveness, serialize merges through a wave branch, and report until the list or backlog is done. Trigger on "run a wave", "dispatch a wave of issues", "batch-dispatch these issues", "work the backlog in parallel", "run through the backlog", "supervise the wave", "merge the wave back". NOT for a single issue (superset-launch) or subagent fan-out in one task (subagent-dispatch).
---

# Wave Supervisor

Work an entire backlog slice in one session: dispatch a *wave* (one cohort of parallel workers, one per issue), supervise it, serialize the merges, and either terminate or pull the next cohort. Encodes the pattern proven across waves 1–3 (2026-06-14, 2026-07-05/06/07 — see #260 for retros) plus the 2026-07-12 design review.

This skill is prose guidance for the host agent; executable cross-workspace orchestration is a runtime/`rpw` concern (ADR-2026-05-27). Compose over the substrate — never invent parallel mechanisms:

| Concern | Owner |
|---|---|
| Spawn/rename/delete workspace mechanics, Gate vs Autonomous prompts, Step 6.5 liveness verify | `superset-launch` skill |
| Claim coordination | `make build-honor-check ISSUE=<n>` / `make build-claim ISSUE=<n>` (#245/#246) — the ONLY claim system |
| Worker branch topology | wave branch (below); inside `/build`, #183 |
| Version-bump race | #210 auto-bump Action — never hand-bump `plugin.json` |

## Two wave modes

Both share the same plan → dispatch → supervise → merge-back → report machinery; they differ ONLY in work source and termination.

1. **Bounded (pre-planned):** the user picks a fixed set of N issues up front. Terminates when the set is delivered.
2. **Unbounded (run the backlog):** no fixed list — continuously pull the next eligible issue as capacity frees, until the slice is drained or a stop condition fires (explicit issue/PR count cap, token/time budget, or the user halting). **Eligible** = open, unclaimed (`build-honor-check` clear), and sharing no conflict surface with in-flight work.

## Defaults (2026-07-12 design review — override only when the user says so)

- **Wave width: 5**, and always `min(5, number of non-colliding conflict-surface groups)`. A per-wave override is a user argument, not a judgment call.
- **Unbounded ordering: supervisor judgment**, weighing priority labels, impact, effort, complexity, and ordering benefits (e.g. land a prerequisite or repo-wide sweep before the features that build on it). State the chosen order and the one-line why in the wave plan.
- **Advance: auto, with exception stops.** Roll into the next pull/wave without asking, posting a compact report as you go. Stop and ask ONLY on: repeated worker failures on the same issue, a merge you cannot serialize safely, budget/count caps reached, or a needs-input issue reaching the front with nothing else eligible.
- **Needs-input issues (unbounded): queue + batch-ask.** Park them in a needs-input bucket, keep dispatching eligible work, and surface the bucket as ONE batched `AskUserQuestion` at the next report/checkpoint. Never silently skip; never idle the fleet for one ambiguous ticket.

## Pipeline

### 1. Plan the wave

- Bounded: take the user's list. Unbounded: pull the top slice by the ordering judgment above.
- **Group by conflict surface, not logical dependency** — "no logical dependency" ≠ "no shared file". Issues touching the same files/plugin manifest go to the same worker or run sequentially, never in parallel.
- Verify claims live at dispatch time (`make build-honor-check ISSUE=<n>` per issue — orientation data is stale by definition), then claim (`make build-claim ISSUE=<n>`).

### 2. Cut the wave branch (REQUIRED)

```bash
git fetch origin production
git checkout -b wave/<YYYY-MM-DD>-<slug> origin/production && git push -u origin HEAD
```

- Every worker worktree branches **off the wave branch** and PRs **into the wave branch**. Production never sees partial wave state; abandoning a failed wave = deleting one branch.
- Worker PRs into a non-default branch do NOT auto-close issues and do NOT trigger the per-PR auto-bump (#210) — zero mid-wave bumps by construction.
- If production moves mid-wave (hotfix), the supervisor merges production → wave branch ONCE, at a moment of its choosing. Workers never track production directly.

### 3. Dispatch — orchestrator-owned background workers (primary pattern)

Superset workspaces are the human-visibility layer (panes); the dispatch mechanism is a background `claude -p` process the supervisor owns, one per issue, in that issue's worktree:

```bash
( cd <worker-worktree> && env -u ANTHROPIC_BASE_URL -u ANTHROPIC_CUSTOM_HEADERS \
    claude -p "<prompt>" --model <pinned> --permission-mode acceptEdits \
    --allowedTools Bash --output-format stream-json ) &> worker-<issue>.log &
```

Headless gotchas (all hit live): scrub inherited `ANTHROPIC_BASE_URL`/`ANTHROPIC_CUSTOM_HEADERS` or child auth fails; pin `--model` explicitly; unattended workers need `--allowedTools`/acceptEdits or they permission-wedge.

Prompt = superset-launch's Step 6 shape, with the wave overrides: base branch is the **wave branch**, and delivery is **Gate**: *"open a PR into `wave/<...>` referencing #N, then STOP — do not merge; the supervisor serializes merges."* Gate is mandatory whenever ≥2 in-flight issues land in the same plugin; cross-plugin PRs can't collide and may merge into the wave branch on arrival.

Executor fallback rule: if the planned executor (e.g. `rpw build --live`) fights wave rules by construction (its pr-merge node hardcodes base=production + auto-merge until #346 lands), **fall back to headless `claude -p` rather than patching mid-wave**.

### 4. Supervise

Liveness signals, in reliability order (earned across waves 2–3: two monitor false-alarms came from layer 3):

1. **Harness task-completion notifications** — primary; never wrong across 10+ workers.
2. **Worktree progress** — dirty-file counts / commits; the mid-flight signal.
3. **Process inspection** — last resort only; NEVER pattern-match on prompt text (relaunched workers start "RESUME…", not "Implement…").

Plus one dumb backstop: a **60-minute "has each worker produced output yet" silence timer** — it covers the only gap notifications leave (a hung worker that never exits). Process existence alone is NOT liveness (#259 prompt-wedge).

**Salvage protocol** (validated 4/4 and 2/2 on live VPN drops): before relaunching, probe connectivity with a 1-token `claude -p "reply ok"` **with a timeout** (the probe can hang rather than error). Relaunch dead workers in the SAME worktree with a salvage header: *"Review `git status`/`git diff`/`git log` first; continue — don't start over; check for existing comments/PRs before posting."* Partial work survives into the final PRs.

Escalate stalls with a specific question; never silently stall.

### 5. Merge back (supervisor-serialized)

- Merge worker PRs into the wave branch **one same-plugin PR at a time**, rebasing/refreshing the next against the moved wave branch; intra-wave conflicts are cheap (shared base, no bot interference).
- **Review before merging — not a rubber stamp.** For skill-authoring PRs, the `description:` frontmatter is the model-routing mechanism (#268): check trigger phrases before merging.
- Rebase still-running workers onto the advancing wave branch as merges land.
- As issues complete: close-out happens via the final wave PR (next step); tear down finished workspaces (`superset workspaces delete <id>`, prune branches). A failed `git push --delete` on a remote branch usually means the repo auto-deleted it on merge — not an error.

### 6. Report + terminate

- Running tally at every checkpoint: merged / in-flight / blocked / needs-input, plus budget spent if capped.
- Wave ends with **ONE PR `wave/<...> → production`** through the normal CI gate (`make verify` + secret scan + auto-bump) exactly once. The wave PR body MUST carry the full `Closes #a, Closes #b, …` list (worker PRs into a non-default branch don't auto-close) and link every constituent worker PR — the per-worker reviews are the real review; the links keep history navigable after squash-merge.
- Unbounded mode: on backlog-drained or a stop condition, finish in-flight work, run the merge-back, deliver the final wave PR, then hand off: what merged, what's parked in needs-input (with the batched questions), what's left in the slice.

## Escalation triggers (pause and ask)

Repeated failure of the same issue after one salvage relaunch · a merge that can't be serialized without judgment the user reserved · needs-input bucket is the only work left · count/budget cap reached · anything that would touch production outside the single wave PR.
