# The usage snapshot in the rollup — rules vs evidence

`make usage-report` (`scripts/usage_report.py`) snapshots one row per `(week, kind, id)`
into `rpw_prod.custom_logging.log_events` and prints a `## Usage` section for the rollup
issue. The section has two halves and the sweep's verify discipline applies to only one of
them.

## Half one — the four decay rules (#1959). Proposals; verify them.

| Rule | Fires when | The false positive to watch for |
|---|---|---|
| `decay` | sessions down ≥50% from a prior mean of ≥5 | a quiet week, a holiday, one heavy user away |
| `dead` | 0 sessions across 60 days of snapshots | a skill that post-dates the telemetry — `agent.skill.load` only started emitting with #1969 |
| `bloat` | p90 result chars up ≥50% over the prior mean, **or** a green run at the harness cap | one unusually large legitimate result |
| `churn>use` | commits plus issue titles beat sessions over 30 days | a skill under deliberate active development |

Two guards are already built in, so do not re-derive them: `dead` reports
`needs_history` rather than firing when the record is shorter than 60 days, and a rule hit
on a skill the catalog does not know is marked `unknown_skill` in the finding's detail.

Everything else is your job. **A hit you cannot explain is refuted, not a deletion**, and
the refuted count belongs in the rollup — that number is how a reader calibrates the rest.

## Half two — the outcome signals (#1960). Evidence; carry them through.

**A load count measures how often a surface triggers, not whether it helped.** Some loads
are required rather than chosen: `communication` is required by the global CLAUDE.md, and
`issue-first-development` is a gate — its jump from 8 to 78 sessions is partly its own
launch, and a high count there proves the rule is obeyed. Others are rare and high-stakes
(`scrub-repo-history`) and will always look unused. A sweep that read session counts alone
would propose retiring exactly the wrong skills.

Two columns correct for that:

| Column | What it counts | Where it comes from |
|---|---|---|
| **Friction open/closed** | `retro-finding` issues whose body carries a `skill: <name>` line | `wave-supervisor/retro-miner.md`, `periodic-review`, the chief-of-staff friction harvest |
| **Outcome sessions / merged PR / green gate / corrected** | of the transcript sessions that used the surface, how many merged a PR, passed a gate, or drew a human correction | the transcript miner, all harnesses |

### The rules for reading them

- **Never refute a row and never turn one into a proposal.** These are not findings. Paste
  the table as printed.
- **Read them beside the rule hits, not instead of them.** High friction next to high usage
  is a skill worth *reading*; high usage alone is not a result; zero friction on a
  rarely-loaded skill means nobody reported anything, not that nothing is wrong.
- **A single correction is not a verdict.** The heuristic is deliberately loose — any human
  turn within 30 minutes of a load that opens with a refusal token — so "no, use the other
  file", a redirect rather than a judgement, counts. It is a pointer at a transcript to go
  read, nothing more.
- **Read the header's attributed/unattributed split before the column.** The window was 10
  minutes and attributed **1** of 21 real corrections, so the section printed "21 turn(s)"
  above a table of all-zero `Corrected` cells with nothing reconciling the two. At 30
  minutes 13 of the 21 are reachable; the rest are genuinely unattributable (8 were in
  sessions that had loaded no skill at all, and the remaining gaps run from 53 minutes to
  1d12h). The header now prints both numbers, so a low column is visibly a coverage limit
  rather than a finding. 30 is the cap on purpose: past it a correction gets attributed to
  whatever loaded earliest in the session, which is proximity, not cause.
- **Never sum the `Corrected` column.** Every surface tests the window independently, so
  one human "no" inside three surfaces' windows increments all three — at a 120-minute
  window, 21 real turns produced 30 attributed ones. The column answers "was this surface
  in play when a human pushed back", never "how many". The deduplicated total is the
  attributed number in the header.
- **Never let a signal drive an edit.** The standing constraint on this whole line of work:
  the report proposes, a human approves every skill edit. A loop that rewrote skill
  descriptions to trigger more often would be gaming its own metric.

### Two coverage limits worth restating in the issue

A reader who does not know these will misread a zero as a result:

1. **Friction accrues forward only.** The 179 `retro-finding` issues that predate the
   `skill:` convention were deliberately not backfilled, so the column starts empty and
   fills over weeks.
2. **Outcome coverage is bounded by transcript retention.** Claude Code keeps transcripts
   30 days (`cleanupPeriodDays`), so `outcome_sessions` is at or below the row's `sessions`
   whenever `log_events` also covers the surface. It is coverage, not a session count.

## The causal signal is not here

The only measurement that shows a skill *caused* a better outcome is a paired eval — the
task bank run with the skill suppressed and present
(`libs/rpw_evals/scripts/run_paired_skill_eval.py`, protocol in
`libs/rpw_evals/docs/paired-skill-eval.md`). It is live, costs money, and runs monthly by
hand. **The sweep never starts one.** If the rollup makes a case for one, say so in the
issue and let a human run it.
