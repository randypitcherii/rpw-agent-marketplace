# Skill attribution — the `skill:` body line on a finding (#1960)

A skill's usage count measures how often it **triggers**, not whether it **helped**, and
the gap is not academic. `communication` is required by the global CLAUDE.md;
`issue-first-development` is a gate. Both score high by obedience. `scrub-repo-history`
is rare and high-stakes, and scores low. Optimizing a load count rewards the first group
and retires the third.

Friction is the cheapest correction available: a skill that keeps producing review
findings is worth reading, whatever its session count says. This file is the convention
that makes that joinable. Same convention as `wave-supervisor/retro-miner.md` and the
chief-of-staff friction harvest — all three write the same line so one reader counts all
three streams.

## The line

When a finding implicates a specific house skill, add the `retro-finding` label and name
the skill on its own body line:

```
skill: periodic-review
skill: subagent-dispatch
```

## Rules

- **A body line, never a label.** The label set is already 81 entries; one label per
  skill would double it. `retro-finding` stays the only label this adds.
- **The skill's directory name**, lowercase, exactly as it appears under
  `plugins/*/skills/`. Not the title, not a slash command, not a plugin-qualified name.
  A name matching no skill is dropped by the reader and reported as an ignored line, so
  a typo is visible rather than silent.
- **One line per skill**, or comma-separated on one line. Separate lines read better.
- **`retro-finding` is additive**, not a replacement: keep the `type:`/priority labels
  the procedure already assigns. A security finding is still `type: bug` + P1.

## When to omit it

Most findings have no skill to blame, and a guessed attribution is worse than none — it
puts friction on a skill that did nothing wrong, which is the one failure mode that would
discredit the whole signal. Omit the line when the finding is about:

- **product or library code** — the usual case for this skill's three lenses;
- **infrastructure** — a flaky runner, a missing permission, a Makefile or CI gap;
- **a brief or an AGENTS.md** — those are not skills, even when an agent followed them;
- **a skill you are guessing at.** If you cannot name the file whose guidance produced
  the finding, there is no attribution to make.

Attribute it when the finding is that a skill's *guidance* was wrong, missing,
misleading, stale, or ignored because it was unreadable.

## How it is read

`scripts/usage_report.py` (`friction_by_skill`) makes one `gh issue list` call for every
`retro-finding` ever filed, parses the `skill:` lines locally, and puts open/closed
counts in the weekly rollup's outcome table beside each skill's session count.
`make usage-report` prints the tagged count on its `friction:` line.

Counting is **forward-only**. The 179 findings filed before this convention landed were
deliberately not backfilled, so an empty column in the first weeks is the expected
reading, not a broken join.

By hand, for one skill:

```bash
gh issue list --label retro-finding --state all --limit 800 --json number,state,body \
  --jq '[.[] | select(.body | test("(?im)^\\s*skill:.*\\bperiodic-review\\b"))] | length'
```

## What this signal is not

It is **not a score and not a threshold**. High friction plus high usage is a skill worth
reading; high usage alone is not a result; zero friction on a rarely-loaded skill means
nothing was reported, not that nothing is wrong. Nothing reads these counts and edits a
skill — every edit still lands through an issue a human approves, which is the same rule
that governs every finding this skill files.
