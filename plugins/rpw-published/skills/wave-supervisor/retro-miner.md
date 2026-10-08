# Retro Miner — wave close-out prompt

Run this at wave close-out (step 6), after the wave PR is opened, over the artifacts the wave already produced. It turns retro findings into GitHub issues so improvement suggestions arrive reactively instead of waiting for a human-driven retro. Design: 2026-07-20 research synthesis §9 (issue #462); the finding shapes are the ones that produced QW-1..QW-4 in §8.

## Inputs (all already on disk / in GitHub — no new instrumentation)

- **Worker logs:** the `.wave/worker-<issue>.log` files the dispatch step wrote, plus their `.meta.json` siblings (#570). Log shape follows the meta `"dispatch"` field per [`dispatch-mechanics.md`](dispatch-mechanics.md): `claude-p` logs are stream-json with cost/duration/token/cache and every tool call; `agent-tool` logs are the final report + one usage line, with cache metrics legitimately absent (#636).
- **`WAVE-STATE.md`:** the wave's state of record — issue→worker mapping, launch/relaunch/park events, merge log (#569).
- **Worker PRs + the wave branch:** scope drift, gate violations (`Closes` where `Refs` belongs, merges a worker performed itself), review friction.
- **Supervisor session state:** salvage relaunches, monitor false alarms, needs-input parking, claim conflicts.
- **Issue threads:** worker progress comments — where workers reported friction in their own words.

## Preflight — BEFORE mining (#570)

Both checks are reports, not gates: mine anyway (a nonzero exit from check 2 is a
finding to record, not a stop), but say what was missing so the next wave's
numbers aren't silently incomparable.

1. **Branch check** — the branch recorded in `WAVE-STATE.md` must equal the active
   wave branch. If it doesn't, STOP: you are about to mine another wave's state.
2. **Missing-artifact report** — reconcile *both* ledgers. `missing-logs` exits 2
   and prints one line per gap; list them in the close-out report and treat those
   workers' cost and duration figures as unavailable rather than zero.

```bash
uv run python scripts/wave_worker.py missing-logs   # exit 0 = clean, 2 = gaps printed
```

   | Line | Means |
   |---|---|
   | `MISSING: worker-<n>.log` | metadata expects that log; it is not on disk |
   | `MISSING-META: worker-<n>.meta.json` | `WAVE-STATE.md` records that worker, metadata is gone |
   | `CORRUPT-META` / `BAD-META` / `UNSAFE-META` | meta line is unparseable, has no `log`, or names a path outside `.wave` |
   | `VARIANT-WORKER-HEADING` (#1591) | a non-canonical `## Workers (…)` heading — its rows are invisible to the parser, so the state ledger reads as empty when it is not |
   | `NO-WORKER-SECTION` (#1591) | no canonical `## Workers` section at all; nothing can be reconciled against metadata |

   **Metadata names the logs; the state table proves metadata exists.** Never
   derive a log filename from the `WAVE-STATE.md` Issue column — a multi-issue
   row key (`#986+#1117`) is not an issue number, and stemming
   `worker-986+1117.log` from it false-alarms on the real, primary-issue-keyed
   `worker-986.log` (#1343). Each meta line's own `log` field already names the
   exact artifact, relaunch `.r<k>.log` files included. But metadata cannot
   vouch for its own absence — a wave that lost `.wave` with a populated state
   table must never read as complete, so the state table is checked for a meta
   ledger per worker. Silence means clean only when both ledgers are empty.

## Mining lenses (score each; most waves yield 2–5 findings, not 20)

1. **Provisioning friction** — a worker spent turns discovering something the dispatch brief or an AGENTS.md should have pre-paid (tool paths, make targets, permissions it had to ask for).
2. **Prompt/brief redundancy** — text repeated across ≥3 worker prompts that belongs in AGENTS.md or the skill.
3. **Cost/duration outliers** — a worker ≥2× the wave median without a correspondingly larger diff; name the phase that burned it.
4. **Process-rule violations** — gate mode, fencing, or claim rules broken (even harmlessly): the rule was unclear or unenforced.
5. **Salvage/liveness events** — every relaunch or monitor false alarm, with which signal layer lied.
6. **Repeated manual supervisor work** — anything the supervisor did by hand twice in one wave.

## Output contract

For each finding, file ONE GitHub issue:

- **Labels:** `retro-finding` always; add `quick-win` when the fix is ≤~1 hour and needs no design. Bootstrap labels idempotently first:
  ```bash
  gh label create retro-finding --color 8250DF --description "Mined from a wave retro" --force
  gh label create quick-win --color 2DA44E --description "Small, design-free improvement" --force
  ```
- **Title:** the improvement, imperative ("Pre-grant chrome-devtools permission in frontend worker briefs"), not the anecdote.
- **Body:** evidence (worker/issue numbers, log excerpts, cost figures) → proposed change → link to the wave branch (`wave/<date>-<slug>`) and the worker PRs involved.
- **`skill:` line** — see the section below. One per implicated skill, or omit it.
- **Dedupe:** before filing, `gh issue list --label retro-finding --state open --search "<keywords>"` — comment fresh evidence on an existing issue instead of filing a duplicate.

## The `skill:` line — attribute the friction (#1960)

A skill's load count measures how often it **triggers**, not whether it **helped**.
`communication` is required by the global CLAUDE.md and `issue-first-development` is a
gate, so both score high by obedience; `scrub-repo-history` is rare and high-stakes and
scores low. Friction is the cheapest correction to that: a skill that keeps producing
retro findings is a skill worth reading, whatever its session count says.

So when a finding implicates a specific house skill, name it on **its own body line**:

```
skill: wave-supervisor
skill: dispatch-launch
```

Rules, all of which the reader depends on:

- **A body line, never a label.** The label set is already 81 entries; one label per
  skill would double it. `retro-finding` stays the only label this adds.
- **The skill's directory name**, lowercase, exactly as it appears under
  `plugins/*/skills/` — not the title, not a slash command. A name that matches no skill
  is dropped by the reader and reported as an ignored line, so a typo is visible.
- **One line per skill.** Comma-separated names on one line are accepted; separate lines
  read better in the issue.
- **Omit it when the finding is not about a skill.** A missing dispatch permission, a
  flaky runner, or a Makefile gap has no skill to blame, and a guessed attribution is
  worse than none — it puts friction on a skill that did nothing wrong.

The weekly usage snapshot reads these into the rollup's outcome table
(`scripts/usage_report.py`, `friction_by_skill`); `make usage-report` prints the tagged
count. Counting is **forward-only** — the 179 findings filed before this convention were
deliberately not backfilled, so an empty column in the first weeks is expected.

To read the count for one skill by hand:

```bash
gh issue list --label retro-finding --state all --limit 800 --json number,state,body \
  --jq '[.[] | select(.body | test("(?im)^\\s*skill:.*\\bwave-supervisor\\b"))] | length'
```

Do NOT file: findings about a single worker's one-off mistake with no process fix, or anything already fixed mid-wave (fold-in rule). Report the filed issue numbers in the wave close-out summary.

## Optional digest delivery

If the target repository defines a digest command, run its documented dry-run first and use only a channel the user explicitly selected. Otherwise, keep the digest in the wave close-out report. Never assume a private app, environment variable, or Slack channel exists.
