---
name: periodic-review
description: Standing counterbalance review over recently-merged work — dispatch independent security, simplification, and bug-catching subagents across the merged delta, adversarially verify findings, and file severity-ranked GitHub issues (never direct fixes). Trigger on "run a periodic review", "counterbalance review", "review the last wave", "review the wave branch", "run the review subagents", or as wave-supervisor's mid-wave/post-wave step. NOT for one open diff/PR (use /code-review).
---

# Periodic Review — the counterbalance to agentic waves

Waves (`wave-supervisor`, #260) optimize for throughput: many workers, per-PR review that shares the wave's context, orchestrator-serialized merges. That is a velocity machine, and velocity machines accrete what velocity misses — the cross-PR defects catalogued under "Cross-PR is the edge" below.

This skill is the standing counterweight: independent review subagents on a cadence, whose findings become **issues, not commits**. The wave delivers; the counterbalance identifies. Separation is the point — a reviewer that also fixes inherits the builder's incentives.

## When it runs

- **Mid-wave** — `wave-supervisor` invokes this over the wave branch's incremental delta on a merge-count cadence (defaults in that skill's counterbalance section).
- **After each wave** — `wave-supervisor`'s report step, over the merged delta, before the final wave PR.
- **Periodically** — for any repo taking direct-to-production work between waves, scheduled or manual.

## The three lenses (dispatch in parallel, one message)

| Lens | Dispatch as | Hunts |
|---|---|---|
| **Security** | `debug-lead`, or a general-purpose agent carrying this row's hunt-list as its lens prompt | secrets in logs/DBs/error bodies, injection surfaces (subprocess argv, shell), auth/guard/scope regressions, SSRF/path traversal, PII leakage |
| **Bug-catching** | `debug-lead` (Opus) | correctness errors, races/concurrency, idempotency/state inconsistency, contract violations, resource leaks — **especially cross-PR interactions per-PR gates couldn't see** |
| **Simplification** | general-purpose agent with this row's hunt-list as its lens prompt, identify-only | duplication and divergence across PRs built by separate workers, dead code bypassed by a later PR, over-abstraction, inconsistent patterns solving the same shape two ways |

(#332 retired the standing `security-guard`/`simplifier` roles: these lenses are prompts, not named agents.)

All three are **read-only**: they return findings; they do not edit, push, or file issues themselves. The simplification lens runs identify-only (no refactor) here.

## Procedure

1. **Fix the scope to the delta, not the tree.** Review only what's new since the last marker:
   ```bash
   git diff <last-review-marker>..HEAD          # marker = tag review/<date>, or the last counterbalance issue's recorded HEAD
   git log --oneline <last-review-marker>..HEAD  # the PRs under review
   ```
   Reviewing the whole tree every cadence re-surfaces known-accepted code as noise. If no marker exists, use the wave's base (the wave branch's fork point) or the last N merges the user names.

2. **Dispatch the three lenses in parallel** (one message, `run_in_background: true`), each scoped to the exact `git diff` range and told: read changed files in full, adversarially REFUTE each candidate before reporting, rank survivors by severity, return `file:line + concrete failure/exploit scenario + one-line fix`. Give each lens its hunt-list (table above) and the specific new modules to focus on.

3. **Adversarially verify before filing.** Do NOT file a reviewer's raw output. For every candidate that isn't obviously real, spawn a skeptic (or verify inline) that tries to prove the finding CANNOT happen against the actual code — default to "refuted" on uncertainty. An unverified counterbalance is worse than none: it fills the engineering backlog with plausible-but-wrong findings and trains the team to ignore it. (Composes with `subagent-dispatch`'s adversarial-verify pattern.)

4. **Dedupe against the open engineering backlog** (this repo's issues, never the task board — `docs/process/task-vocabulary.md`), then **file severity-ranked issues** — one per finding (or one grouped issue per lens for a batch of small same-kind items), labeled by type (`type: bug` / `type: task`) and priority (P1 for security/correctness that reaches a sink, down to P3 for simplification). Each issue: the scenario, the `file:line`, the proposed fix, and a back-link to this review pass. Never open a PR from this skill.

   **Name the skill a finding implicates** — the `retro-finding` label plus a `skill: <directory-name>` body line — so the weekly usage snapshot can tell a skill that *triggers* from one that *helps* (#1960). Rules: [references/skill-attribution.md](references/skill-attribution.md).

5. **Report**: a compact tally — findings per lens, how many survived verification, how many were already-open dups, the issue numbers filed — and set the next review marker (`git tag review/<date> HEAD` or record HEAD in the summary). If a finding warrants immediate work, recommend dispatching it (single-issue `dispatch-launch`, or fold into the next wave) — that dispatch is a separate, deliberate step, not this skill's job.

## Rules of the counterbalance

- **Findings are issues, never direct pushes.** Trust-before-automation: a human decides what gets fixed.
- **Verified, not raw.** An adversarial refute pass gates every finding. Volume is not the metric; a short list of real findings beats a long list of maybes.
- **Delta-scoped.** Review the new work, not the accumulated tree.
- **Independent.** Reviewers are not the builders and do not share the wave's context or its merge; that independence is the entire value.
- **Cross-PR is the edge.** The findings that justify this skill are the ones no single worker could see: two PRs duplicating a seam, a guard added in one and skirted by an endpoint added in another, a race between concurrently-built features. Point the lenses there.
