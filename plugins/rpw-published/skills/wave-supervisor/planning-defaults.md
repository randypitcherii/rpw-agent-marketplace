# Planning defaults — modes, width, ordering, advance, needs-input

Companion to [SKILL.md](SKILL.md) step 1 (#531). Extracted from SKILL.md when the
#881/#827/#819/#825 liveness rules needed pointer room: these are plan-time
reference the supervisor reads once per wave, not per-step decisions.

## The two wave modes

Both share the plan → dispatch → supervise → merge-back → report machinery,
differing ONLY in work source and termination.

1. **Bounded:** the user picks a fixed set of N issues up front; terminates when
   the set is delivered.
2. **Unbounded (run the engineering backlog):** no fixed list — pull the next eligible issue
   as capacity frees, until the slice drains or a stop condition fires (count cap,
   token/time budget, the user halting). **Eligible** = open, unclaimed
   (`build-honor-check` clear), sharing no conflict surface with in-flight work,
   **and not already delivered** — an open issue whose PR already merged is the
   #1846 stale-open, and "open" alone does not rule it out:
   [`delivered-but-open.md`](delivered-but-open.md).

## Defaults

Set by the 2026-07-12 design review. **Override only when the user says so** — an
override is a user argument, never a supervisor judgment call.

- **Wave width: 5**, always `min(5, number of non-colliding conflict-surface
  groups)`. Bootability caps it further: a target that failed the preflight is not
  capacity ([`dispatch-mechanics.md`](dispatch-mechanics.md), #819/#825).
- **Unbounded ordering: supervisor judgment** over priority labels, impact,
  effort, and ordering benefits (land a prerequisite or repo-wide sweep before
  what builds on it). State the order and the one-line why in the wave plan.
- **Advance: auto, with exception stops.** Roll into the next pull without asking,
  posting a compact report as you go. Stop and ask ONLY on: repeated failures of
  one issue, a merge you can't serialize safely, caps reached, or a needs-input
  issue at the front with nothing else eligible.
- **Needs-input issues: queue + batch-ask.** Park them, keep dispatching, surface
  the bucket as ONE batched `AskUserQuestion` — at the next checkpoint if nothing
  else is eligible, and immediately whenever the user signals they are ready to
  answer. Each parked issue owes tool-ready options, not an open-ended prompt.
  Never silently skip; never idle the fleet for one ambiguous ticket. Timing and
  queue format: [`asking-the-user.md`](asking-the-user.md).

## Classifier-sensitive steps are supervisor-owned (#2421)

Decide at plan time who runs a step the worker's permission classifier will
likely deny. Three kinds:

- **live applies to a server**, even a dry run;
- **process kills**, including `WAVE_SWEEP_ARGS=--kill`. Even a plain
  `make wave-sweep` has been denied. The worker still runs its sweep, but a
  denial means the supervisor runs it;
- **sandbox-escape env flags**, such as `RPW_DIAGRAM_UNSAFE_NO_SANDBOX=1`.

Mark each one **supervisor-owned** in the brief's `## Task`. Use the same split as
[long runs (#495)](dispatch-mechanics.md#long-runs-are-supervisor-owned-495): the
worker delivers the code plus the exact command, and the supervisor runs it —
during the wave, without asking the human. Supervisor-owned is who runs it, not a
wait for approval: `docs/process/live-steps.md` (#2567). A
worker that tries the step anyway spends turns on a denial and then hands it back.
Evidence: wave #2406 had five such denials (PRs #2410, #2416, #2424).

## Cheap live smokes belong to the worker (#2652)

The #2421 split covers only steps the classifier will **deny**. A live smoke
that is cheap (seconds to a few minutes, in-session), that the worker's
classifier allows, and that is off the stop list in `docs/process/live-steps.md`
goes in the worker's `## Task`, not on the supervisor's list. The worker runs it
against the real API before it opens the PR and reports the result.

Supervisor-owned is still right for a #2421 kind, a run that outlives a worker
session (#495), and a step that must run from merged code. Anything else the
supervisor holds back moves defect discovery one dispatch later.

Evidence: in wave #2636 the supervisor owned every darkroom smoke. Each one
found a defect that the worker's lenient fake had passed (PRs #2641, #2644,
#2640), within seconds of a real call. That cost three follow-up dispatches
and about 90 minutes of serial work. The worker-side half of this rule is the
fake-fidelity rule in the brief's `## Gate & verification`.
