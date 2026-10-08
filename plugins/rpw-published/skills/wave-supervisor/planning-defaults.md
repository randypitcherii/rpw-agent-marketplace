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
