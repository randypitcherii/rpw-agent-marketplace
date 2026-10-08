# `WAVE-STATE.md` — the wave's state of record (#569)

Write this file into the **supervisor worktree root** at wave init, immediately
after cutting the wave branch and **before the first dispatch**. It is scratch
and untracked (`.git/info/exclude`), so replacement is always safe.

## This file is not the wave's record — the wave issue is (#849)

`WAVE-STATE.md` is the *live* state of one supervisor session. The
`wave`-labeled GitHub issue is the wave's durable artifact. Neither restates the
other:

| | `WAVE-STATE.md` | The wave issue |
|---|---|---|
| Lives | supervisor worktree, untracked | GitHub, permanent |
| Written | every event, high frequency | plan, checkpoints, close-out |
| Audience | the supervisor, this session | anyone, later |
| Survives the wave | no | yes |

Because it is the state of *one* session, writing it is a lease-guarded
mutation: append through `make wave-state-append SECTION='<heading>' LINE='<line>'`
(or `LINE_FILE=<path>` for multiline prose — both are byte-verbatim, #1104)
rather than editing `## Events` or `## Merge log` by hand. It revalidates the
lease first and refuses (exit 3, writing nothing) once another supervisor has
taken the wave — the 2026-08-05 failure was two sessions writing this file
(#823). Ownership model and takeover: [`wave-issue-template.md`](wave-issue-template.md).

The `- **Wave issue:** #<n>` line below is load-bearing for that guard: it is
where `wave-guard`, `wave-spawn` and `wave-land` learn which issue carries the
lease. A wave whose owner cannot be determined is refused, not assumed free.

The `- **Observability:**` line carries the wave page's resolved frontend URL so a
takeover supervisor (#886) inherits the view instead of re-deriving it — record
the URL you resolved from `~/.rpw/ports.json`, or `not running (<reason>)` when
the page would not start (a disclosure, never a blocker). Mechanics:
[`wave-observability.md`](wave-observability.md).

## `## Workers` is GENERATED — never hand-maintained (#1344)

The worker table is a **projection of `.wave/worker-*.meta.json`**, not a second
ledger. Wave `2026-08-24-raycast-supercmd` reached close-out with six worker
metadata files on disk and one row in the table; the observability page and the
close-out preflight both read the table, so the state of record omitted five of
six live workers.

- `make wave-state-append SECTION=Workers` is **refused** (exit 1), and the
  refusal names `make wave-record-status` (#1752). It used to exit 0 and print
  "appended" while the next render discarded the line, so a supervisor believed a
  note was on the record when it never was.
- `make wave-spawn` and `make wave-land` regenerate it for you. If either prints
  a `warn: … worker table could NOT be regenerated`, the table is behind the
  ledger — fix the cause and run `make wave-state-workers`.
- `make wave-state-workers` is the idempotent reconcile: re-rendering an
  unchanged wave writes nothing. It is lease-guarded and writes atomically, and
  every section other than `## Workers` is preserved byte-for-byte.
- `make wave-state-workers RENDER_ONLY=1` prints what the table would say and
  writes nothing — no lease needed, so a would-be takeover supervisor can look
  first.
- A **merge, park, abandonment or stall leaves no artifact**, so record it on the
  ledger instead of typing it into the table:
  `make wave-record-status ISSUE=<n> STATUS=merged|abandoned|parked|stalled [PR=<n>]`.
  `PR=` is how the `PR` column gets filled — pass it at merge time, because
  nothing else on the supervisor path ever populates it (#1748). `ISSUE=` accepts
  **any issue the worker owns**, not only the lead its meta file is named for, so a
  grouped worker's second issue is recordable too (#1749).
- Everything else is derived. Status precedence, most-decided first: recorded
  status → `PR open` (a `pr` on any record) → `reported` (a report in the log) →
  `relaunched` (more than one launch record) → `dispatched`.
- **A row with no `.wave/worker-<n>.meta.json` is dropped, not preserved** (#1747).
  The projection is authoritative: hand-adding a row is a no-op that lasts until
  the next spawn/land, and the render says on stderr which rows it dropped. If a
  worker really ran, the missing thing is its launch record — restore that, not the
  row.
- A malformed launch record makes the render **refuse** (exit 2, nothing
  written). Repair the ledger; do not hand-edit the table around it.

Per-event lines stay here. Checkpoint tallies and decisions go to the issue as
comments — see [`wave-issue-template.md`](wave-issue-template.md). Record the
wave issue number in the header below so the two are linked from both ends.

## Why it is initialized, not appended to

Wave 2026-07-29 ran to close-out with a `WAVE-STATE.md` that still described
`wave/2026-07-28-backlog` from its first line through its merge log — old branch,
old worktrees, issues #474/#457, PRs #494–#519, and none of the live wave's work.
The retro had to rebuild supervisor state from GitHub and opaque terminal
artifacts, and the stale close-out checklist was live instructions for a
*different wave*. A supervisor worktree is reused; the state file must not be.

## Branch preflight (fail-closed, run twice)

At **init** and again at **close-out**, before acting on anything the file says:

```bash
grep -m1 '^- \*\*Wave branch:\*\*' WAVE-STATE.md   # recorded branch
git rev-parse --abbrev-ref HEAD                    # active wave branch
```

If they differ: at init, **overwrite the file from this template** (a leftover
from the previous wave). At close-out, **STOP and report** — you are about to
mine and close out against another wave's state.

## Template

```markdown
# WAVE-STATE — wave/<YYYY-MM-DD>-<slug>

- **Wave branch:** `wave/<YYYY-MM-DD>-<slug>`
- **Wave issue:** #<n>
- **Lease:** `refs/wave-owner/<YYYY-MM-DD>-<slug>` held since `<ISO-8601 UTC>` (#886)
- **Base:** `production` @ `<fork-point-sha>`
- **Mode:** bounded (<#a, #b, …>) | unbounded (<stop conditions>)
- **Initialized:** <ISO-8601 UTC>
- **Artifacts:** `.wave/worker-<issue>.log` + `.wave/worker-<issue>.meta.json`
- **Observability:** <frontend URL from `~/.rpw/ports.json`, "waves" tab> | not running (<reason>)

## Workers

<!-- GENERATED from .wave/worker-*.meta.json by `make wave-state-workers` (#1344).
     Do not hand-edit: the next spawn/land re-renders this section. A row with no
     matching .wave/worker-<n>.meta.json is DROPPED on the next render (#1747), so
     this example stays inside the comment — a real row looks like:
       | #556 | `worker/556-triage-lane` | /wt/worker-556-triage-lane | `.wave/worker-556.log` | reported | #1740 | -->

| Issue | Branch | Worktree | Log | Status | PR |
|---|---|---|---|---|---|

## Events

Append one line per launch, relaunch, stall nudge, park, and unpark — with a UTC
timestamp. These are the close-out inputs the retro miner cannot reconstruct.

- `<ISO-8601 UTC>` — dispatched #<n> → `worker/<n>-<slug>`
- `<ISO-8601 UTC>` — relaunched #<n> (salvage: <reason>) → `.wave/worker-<n>.r1.log`
- `<ISO-8601 UTC>` — parked #<n> needs-input: <the question>

## Merge log

Worker PRs merged into the wave branch, in the order they were serialized.

- `<ISO-8601 UTC>` — PR #<x> (#<n>) merged
- Counterbalance passes: <marker sha> @ <merge count>

## Needs-input bucket

The close-out `AskUserQuestion` call reads this section **verbatim** (#806), so every
entry is written tool-ready when it is parked: a short header, the question, and
labeled options saying what each one unblocks. The option count, the per-call cap,
the qualifying test and the worked example live in
[`asking-the-user.md`](asking-the-user.md).

- #<n> — **<short header>.** <the question, with the context needed to answer it.>
  Options: (a) <option — what it unblocks>; (b) <option — …>; (c) <option — …>.
  **Answer:** <written back here when it lands, never left only in the session>

## Close-out checklist

- [ ] Branch preflight passes (recorded branch == active wave branch)
- [ ] Wave issue filed at plan time, `wave`-labeled, mentioning every cohort
      issue; checkpoint tallies posted to it as comments (#849)
- [ ] Wave lease held by this session for the whole wave, heartbeat at every
      checkpoint — never inferred from process existence (#886/#259)
- [ ] All worker PRs merged or explicitly abandoned
- [ ] Final `periodic-review` pass run (before the wave PR)
- [ ] Expected `.wave/worker-<issue>.log` present for every dispatched issue
- [ ] Retro mining run; finding issues filed and listed
- [ ] Wave digest delivered (or `--dry-run` output pasted into the report)
- [ ] Wave-shape diagram committed on the wave branch and embedded at the top of
      the wave PR body — artifact path, file set and embed rule are specified once
      in [`merge-and-closeout.md`](merge-and-closeout.md) (#789/#1755)
- [ ] ONE `wave/<...> → production` PR opened with the full `Closes` list
- [ ] Delivered-but-open sweep run **while that PR was still open** (a hit is a
      one-line `Closes`-list edit then, a hand-close afterwards) and re-run after
      the merge, before the wave issue is closed: no issue a worker PR `Refs`'d is
      missing from the `Closes` list (#1846) — command and fail-closed guard in
      [`delivered-but-open.md`](delivered-but-open.md)
- [ ] Needs-input bucket and every human-action item **asked** via
      `AskUserQuestion`, answers written back here (#806); never a closing
      paragraph. Per-call cap and the overflow rule:
      [`asking-the-user.md`](asking-the-user.md)
- [ ] Process sweep clean: no process references any wave worktree, no runaway
      CPU, load average back near idle (#644) — a survivor is a loud failure
- [ ] Wave issue closed, after the wave PR merged, with a final outcome comment
- [ ] Wave lease released (`make wave-release ISSUE=<n>`); no
      `refs/wave-owner/*` left behind (#886)
- [ ] Worker workspaces deleted, branches pruned
```
