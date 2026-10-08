# The wave issue — the wave's artifact of record (#849)

Companion to [SKILL.md](SKILL.md) step 1. Every wave files **one GitHub issue,
labeled `wave`, before the branch is cut.** It is the only wave artifact that
outlives the wave.

## Why a GitHub issue and not another file

Everything else a wave writes about itself is local and temporary.
`WAVE-STATE.md` lives in the supervisor worktree, is untracked, and is
overwritten by the next wave that reuses that worktree (#569). `.wave/` logs sit
beside it. The wave branch — the anchor every retro finding cites as its evidence
— is deleted at close-out.

So a wave that ends leaves a squashed commit and a scatter of `retro-finding`
issues pointing at a branch that no longer exists. Nothing answers "which wave
did #825 come from, and what else shipped alongside it?"

An issue answers it, is server-side, and is the one substrate every repo already
has — which matters for waves run outside this repo (#840, #842).

## Division of labour — neither file restates the other

| | `WAVE-STATE.md` | The wave issue |
|---|---|---|
| Lives | supervisor worktree, untracked | GitHub, permanent |
| Written | every event, high frequency | plan, checkpoints, close-out |
| Audience | the supervisor, this session | anyone, later |
| Survives the wave | no | yes |

Per-event launch/relaunch/stall/park lines stay in the file. Checkpoint tallies
and decisions go to the issue as comments. If you find yourself pasting the
event log into the issue, you have the split wrong.

## Naming — one token spans everything

The **wave name** is `<YYYY-MM-DD>-<slug>`, and it is identical across the
issue title, the branch, the worktrees, and the log keys:

```
issue title:  Wave 2026-08-06-foundations — <one line on what this wave is for>
branch:       wave/2026-08-06-foundations
```

One `grep` for the name finds every artifact. Pick the slug at plan time and do
not change it afterwards.

## Ordering — the issue comes first

File the wave issue **before** cutting the branch, so the branch is named after
the issue rather than reconciled with it, and so the issue number is available to
put in `WAVE-STATE.md` and in every worker brief. Workers cite it in progress
comments; that is what threads a worker's own words back to its wave.

## Mentions map the cohort. `Closes` stays on the wave PR.

The body names every constituent issue as a **bare `#N` mention**. GitHub then
writes a cross-reference into each mentioned issue's timeline, so any issue —
open, or closed a year ago — shows the wave that carried it. That is the reverse
map (issue → wave); the body is the forward map (wave → cohort).

> **Never write `Closes #N` in the wave issue.** The single
> `wave/<…> → production` PR holds the sole `Closes` list
> ([`merge-and-closeout.md`](merge-and-closeout.md)). A `Closes` in the wave
> issue closes nothing when the issue itself closes, but a `Closes` in a *PR*
> that references the wave issue will — and duplicating the list means issues
> close on the wrong event, before their work has merged.

Bare `#N` only. Same-repo references are never self-qualified
(`docs/process/issue-conventions.md`).

## Template

```markdown
# Wave <YYYY-MM-DD>-<slug>

- **Branch:** `wave/<YYYY-MM-DD>-<slug>`
- **Base:** `production` @ `<fork-point-sha>`
- **Mode:** bounded | unbounded (<stop conditions>)
- **Width:** <n> (default 5)
- **Opened:** <ISO-8601 UTC>
- **Owner:** claimed via `make wave-own` below (#886) — one live supervisor

## What this wave is for

<Two or three sentences. The theme, and why these issues are one cohort rather
than a batch. A reader a year from now starts here.>

## Cohort

Issues carried by this wave. Grouped by conflict surface — issues in one group
touch shared files and are worked by one worker or in sequence, never in
parallel.

| Group | Issues | Conflict surface | Worker |
|---|---|---|---|
| A | #<a>, #<b> | `plugins/rpw-published/skills/<x>/` | `worker/<a>-<slug>` |
| B | #<c> | `projects/<y>/` | `worker/<c>-<slug>` |

<Ordering note: one line on why this order, if the order matters — a
prerequisite or a repo-wide sweep landing before what builds on it.>

## Checkpoints

<Comments below carry the running tally. Nothing goes here at open.>
```

## Checkpoint comments

Post the checkpoint tally you already produce (SKILL.md step 6) as a comment,
rather than only to the session:

```markdown
**Checkpoint <ISO-8601 UTC>** — merged <n> · in-flight <n> · blocked <n> · needs-input <n>
- merged: #<a> (PR #<x>), #<b> (PR #<y>)
- in-flight: #<c>
- needs-input: #<d> — <the question>
- counterbalance: pass <k> @ <marker sha>, <n> findings folded
```

Also comment — not only in `WAVE-STATE.md` — on anything a later reader needs
and the file will not survive to tell them: a scope change, an abandoned issue
and why, an escalation and its answer.

## Close-out

The wave issue closes **after** the wave PR merges, never before — it is the
record of a wave that happened, so it stays open while the wave can still
change. At close:

- Final comment: what merged, what was abandoned, what carried to the next wave.
- Close with a comment, not a bare close. A closed wave issue with no closing
  comment loses the outcome.

Retro findings, and the wave-shape diagram (#789), land in this thread too —
those are part 2 of #849 and land with it, not before.

## Ownership — REQUIRED, immediately after filing (#886)

```bash
make wave-own ISSUE=<n> WAVE=<YYYY-MM-DD>-<slug>   # then dispatch nothing until it exits 0
```

A wave is owned by **exactly one live supervisor**. On 2026-08-05 two of them ran
the same wave: both dispatched the same issues, both wrote `WAVE-STATE.md`, and
one merged a PR the other had declared dead (#823, P0). Two serializers are not
a serializer, and the supervisor's whole safety property is serialized merges.

`wave-own` **exits 3 and dispatches nothing** when a different live supervisor
holds the wave, naming who. Treat that as final: do not retry it, and do not
work around it. Run it before the first claim, the first dispatch, and any merge.

Two layers, with different jobs:

| Layer | Job |
|---|---|
| `refs/wave-owner/<wave-name>` | the **mutex** — created create-only, so GitHub itself rejects the second supervisor |
| The owner comment on this issue | the **record** — who, on what, since when |

Labels and comments are not mutexes: GitHub applies both unconditionally, so two
supervisors would both "win". Only the ref can fail on contention.

The record carries what makes a conflict actionable — Omnigent session, runner
and server; harness family, version and session id; model; the **plugin versions
actually in force** (#820 is an installed plugin still running a retired path);
plus host, pid, branch, worktree. "Held by another supervisor" tells you nothing;
"held by session `88e03ec2…` on `<host>`, heartbeat 3m ago" tells you to wait,
take over, or go look at a terminal.

### Taking the lease once is not enough (#823 / #822)

**Every mutation revalidates.** A deliberate takeover can supersede you
mid-wave; from that moment your next claim, dispatch, state write or merge *is*
the incident, and it will look locally correct to you. So the lease is
re-checked before each one, not only at wave start:

```bash
make wave-guard                       # am I STILL the owner? exit 3 = stop
```

`wave-guard` and `wave-owner-check` answer different questions, and the
difference is the whole point:

| Target | Question | Passes on |
|---|---|---|
| `make wave-liveness ISSUE=<n>` | is a supervisor **actually working** this wave? | `free`, `dead` only (#1873) |
| `make wave-owner-check ISSUE=<n>` | may I **start**? | `free`, `own`, `stale` |
| `make wave-guard` | am I **still** the owner? | `own` only |

**`stale` from `wave-owner-check` is necessary but NOT sufficient (#1873).** It
reads `hb=`, which the supervisor's own turn loop writes, so a **busy** supervisor
mid-long-turn and a **dead** one both go stale — the ambiguity that redispatched 7
workers onto delivered work on 2026-09-21. `wave-liveness` reads a second
substrate the supervisor does not write by choosing to, and it refuses
(`live`/`at-risk`) exactly where `wave-owner-check` passes. Never act on `stale`
alone; see the takeover sequence below.

`free` and `stale` are refusals for a mutation: one means you hold no lease at
all, the other means the record names somebody else. Both were "fine" to the
losing supervisor on 2026-08-05.

Wired in already — you get this without asking:

| Mutation | Guarded by |
|---|---|
| Dispatch (`make wave-spawn`) | revalidates, **refuses to spawn** on a foreign lease |
| Landing a worker report (`make wave-land`) | revalidates; on refusal it prints the report it did not write so nothing is lost |
| Worker claims (`make build-claim`) | stamps the owning supervisor; honor-check separates the three cases below |
| `WAVE-STATE.md` writes | `make wave-state-append` (below) |

Both `wave-guard` and `wave-spawn` read the wave issue from `WAVE-STATE.md`'s
`Wave issue:` field, so record it at init. A wave whose owner **cannot be
determined** is refused rather than assumed free.

### Writing WAVE-STATE.md

Append through the guarded path, never by hand-editing the file:

```bash
make wave-state-append SECTION='Events' LINE='- 14:02Z — worker #900 landed'
make wave-state-append SECTION='Merge log' LINE='- #900 squashed into the wave branch'

# Long, multiline, or heavy on inline code spans → author it in a file:
printf '%s\n' '- 14:02Z — `git merge origin/production` ran during close-out' > /tmp/line.md
make wave-state-append SECTION='Events' LINE_FILE=/tmp/line.md
```

Both routes are **byte-verbatim**: the payload reaches the script through the
environment or a file, never through a recipe's argv, so backticks, `$VAR`,
`$(cmd)`, quotes and backslashes are appended as written instead of executed
(#1104 — a backticked span in a close-out line once ran a real `git merge`).
`LINE_FILE=` is the canonical route for arbitrary prose.

It revalidates the lease, then appends **one line** under that `##` heading — a
de-throned supervisor cannot clobber a section it never read. On refusal (exit
3) nothing is written and the line is echoed back so you can hand it to the real
owner. A missing section is exit **1**, a usage error, not a lease problem.

### Claims record which supervisor dispatched them (#822)

A claim sentinel records the worker *branch*, which answers "is this issue
taken?" but not "taken by whose wave?". `make build-claim` now also stamps
`supervisor=<token>`, so `make build-honor-check ISSUE=<n>` separates three
cases a branch alone cannot:

| Verdict line on stdout | Means | Exit through `make` |
|---|---|---|
| `own-claim branch=<b>` | stamped from this worktree — proceed | 0 |
| `claimed-by-other … relation=sibling-worker` | another worker of **my** wave; the inherited pre-claim a brief tells a worker to expect (#568) | non-zero |
| `claimed-by-other … relation=foreign-supervisor` | a **different** wave's live supervisor | non-zero |
| `claimed-by-other … relation=unknown` | a pre-#822 claim, or no wave context — treat as taken | non-zero |

**The machine-readable channel is the `relation=<r>` token, not the exit code
(#1100).** GNU make collapses any non-zero recipe status to its own **2**, so
through `make build-honor-check` the exit code is boolean — 0 dispatchable,
non-zero taken — and it cannot separate the three refusals. Key off the token:

```bash
verdict="$(make build-honor-check ISSUE=<n> 2>/dev/null | sed -n 's/.*honor-check #[0-9]*: //p')"
case "$verdict" in
  *relation=foreign-supervisor*) ;;  # report and SKIP — never overwrite (#822)
  *relation=sibling-worker*)     ;;  # expected for an inherited pre-claim (#568)
  own-claim*)                    ;;  # proceed
esac
```

`scripts/wave_worker.py:honor_relation` is the reference parser. Sourcing
`build_honor_check` from bash directly — no make in between — still exits 3, or
4 for `foreign-supervisor`.

**`foreign-supervisor` is report-and-skip.** Never overwrite another
supervisor's claim. Override the token with `SUPERVISOR=<t>` (or
`RPW_WAVE_SUPERVISOR`) when running a wave from a harness that exports no
session id.

### Takeover — a stale lease is takeable, deliberately

**Liveness is the heartbeat, never process existence (#259).** Run
`make wave-heartbeat ISSUE=<n>` at every checkpoint. A lease with no heartbeat
for 45 minutes is stale and takeable — deliberately, never automatically:

1. `make wave-owner-check ISSUE=<n>` — read the verdict. `stale` names the dead
   owner's session, host and heartbeat age. **`held` is not takeable:** stop and
   report who holds it.
2. **`make wave-liveness ISSUE=<n>` must also say `dead` or `free` (REQUIRED,
   #1873).** `stale` alone cannot separate a dead supervisor from a busy one, so
   it authorizes nothing on its own: `live` or `at-risk` means **STOP, a
   supervisor is working**, and `unknown` means **ask the user** — never take the
   lease on it. Read the printed verdict word, not `make`'s exit code, which
   collapses both refusals to 2. Mechanism: `docs/process/wave-liveness.md`.
3. Look before you take it. The recorded session, host and worktree are there so
   you can tell a crashed supervisor from one that is simply mid-thought; taking
   a live wave recreates #823 with extra steps.
4. Take it, recorded:

   ```bash
   make wave-own ISSUE=<n> WAVE=<name> TAKEOVER=1    # naming both owners
   ```

   The record moves to `state=takeover` and keeps `superseded=<old session>`, so
   the handover is auditable afterward instead of looking like the original
   claim.
5. From here the old supervisor is fenced out by the same guard you now pass: its
   `wave-guard`, `wave-state-append`, `wave-spawn`, `wave-land`, `heartbeat` and
   `release` all exit 3. It cannot release *your* lease.

Release at close-out, after the wave PR merges: `make wave-release ISSUE=<n>`.

The lease label is **`wave: owned`**, never `status: in-progress` — that exact
string is `build-claim`'s sentinel, so reusing it would drop wave issues into
worker honor-checks and wave skip-lists as if they were dispatchable work. A
wave issue is an artifact and is **not worked** (`docs/process/issue-conventions.md`).
