# Retro template — one screen, written once

Companion to [SKILL.md](SKILL.md). Fill this in when the cycle closes. Written to the
`communication` budgets: one screen, verdict first, no logs inline.

The retro is not a diary. It exists so the *next* cycle costs fewer passes, which means two of its
sections are load-bearing — **escapes** and **process changes** — and the rest is context.

## The template

```markdown
## Verdict
<ship / not ship>, after <N> passes. <One sentence: what changed and what still stands.>

## Findings by pass
| Pass | Ship-blockers | Should-fix | Escaped from an earlier pass |
|---|---|---|---|
| 1 | <n> | <n> | — |
| 2 | <n> | <n> | <n> |
| 3 | <n> | <n> | <n> |

Ship-blockers, one line each, with the pass that found them:
- P<n> — <what a user could not do> → <how it was fixed> (<test path>)

## Escapes — findings a later pass had to catch
| Finding | Introduced in | Caught in | Why the earlier pass missed it |
|---|---|---|---|
| <summary> | P<n> | P<n> | <the checklist row that did not exist, or was not run> |

## Gate evidence
- `make check` → <result, counts>
- Browser verification → <viewports driven, what rendered, what did not overflow>
- `/security-review` → <verdict>
- Reproduction checks → <n> findings had a red→green test; <n> disputed and why

## Process changes for the next cycle
- <checklist row to add to pass-checklists.md, and which escape earned it>
- <input to pin earlier, and which pass was wasted without it>

## Decisions needed
<Anything a human must settle, with concrete options. "None" if none.>
```

## Rules for filling it in

- **An escape with no matching process change is an unfinished retro.** The escape table's last
  column is the diagnosis; the process-changes section is the fix. A cycle that escaped four
  findings and proposes nothing has learned nothing.
- **Counts, not narrative, in the findings table.** The detail is the ship-blocker list under it.
- **Gate evidence is your own run.** A quoted subagent summary is not evidence — step 5 of the loop
  exists precisely to produce these lines first-hand.
- **Never inline logs.** Link the run; paste the one verdict line.
- **Escapes trending up across cycles means the checklists are wrong**, not that the reviewers got
  better. Change [pass-checklists.md](pass-checklists.md), not the reviewer prompt.
