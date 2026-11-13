# Unasked is not no

Companion to [SKILL.md](SKILL.md) Rule 0. This is the one statement of the rule;
code that implements it cites this file rather than another module (#1933).

**"The source said no" and "the source was never asked" must be distinguishable, and
the unasked case must never read as the negative answer.** Any check that reads a
source — an API, a file, a process table, a probe — keeps three outcomes apart:

1. **an answer arrived, and it is yes** (a lease, a file, a healthy reply);
2. **an answer arrived, and it is no** (no lease, a resolved 404, a private repo);
3. **no answer arrived** — the tool is missing, the network or auth failed, the
   output did not parse, or an exit-0 call printed nothing.

The third outcome is never folded into the second. A verdict is only ever deduced
from an answer that arrived; the unasked outcome gets its own value, is disclosed,
and **fails closed** — it never shares an exit code with the negative answer when
that answer authorizes an action. A checker that cannot reach its source says so
rather than guessing a verdict.

This is Rule 0 one level down: a probe that could not run is not a probe that
passed, exactly as a live process is not a serving one. Mode C's "no output and
never ran must not look alike" is the same rule for scheduled jobs.

## Value names are per-domain — on purpose

The invariant is the three-way distinction, **not the spelling**. Name the unasked
value for what it means where it is read. Do not "standardise" one module's name
into another's; a shared spelling would claim a shared meaning the verdicts do not have.

| Module | Answered | Unasked |
|---|---|---|
| `automation/bin/wave-liveness.py` (`gh` read) | `ok` | `empty` / `unreachable` → verdict `unknown` |
| `scripts/check_wave_pr_body.py` (URL, assignees) | `ok` / `missing` | `unknown` |
| `plugins/rpw-published/scripts/destination_preflight.py` | `allowed` / `refused` / `blocked-drift` | `unprovable` |
| `automation/bin/omnigent-host-staleness.py` (daemon records) | `ok` | `unreadable` → verdict `unknown` |

`unprovable` for a preflight, `unknown` for a liveness verdict and `unreachable` for a
probe are all correct.

## Why it has a home

It is the most-violated invariant here. `wave-liveness.py` once collapsed every `gh`
failure to `None`, so a 30-second GitHub blip read as `free` — exit 0, dispatchable —
the redispatch that burned seven workers on 2026-09-21 (#1910). The same wave found a
gate snippet that iterated zero times when its `gh issue list` failed and passed, and
an assignee check that could not tell "nobody assigned" from "API unreachable" (#1757).
Four modules then restated the rule in four vocabularies, pointing at each other, and
one of those pointers made a false "same tri-state" claim. New code cites this file.
