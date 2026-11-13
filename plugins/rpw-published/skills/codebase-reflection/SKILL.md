---
name: codebase-reflection
description: Whole-tree reflection on any codebase — what should be removed or simplified. Fans out parallel read-only lenses (dead code, frozen/superseded, duplication, docs/process sprawl), adversarially verifies every finding, and returns one ranked report split into delete-now, needs-a-decision, and simplify. Trigger on "what should we remove", "simplify this codebase", "reflect on this repo", "deletion audit", "what's dead here". NOT a merged-delta review (periodic-review).
---

# Codebase reflection — what should this repo stop carrying?

Codebases grow by addition and nobody owns subtraction. Dead scripts, one-shot migration helpers, frozen subsystems and docs that restate a skill all stay, and each one taxes every session that reads the tree. This skill audits the **whole tree** of **any** repo. It identifies and ranks; **it never deletes**. For "what did the last wave add?" use the `periodic-review` skill instead.

**Mode.** The default is report-only. "…and file issues" means one issue per accepted row, via the `issue-creation` skill. "…and do it" means waiting for the human to pick rows, then doing those as normal issue-first work.

## Procedure

1. **Orient** (you, ~5 calls). Size, last touch and 60-day activity per area. Look for declared state: frozen, deprecated or superseded subsystems, decision records, vendoring rules, length budgets. Flag areas that are **large and quiet**. Recipe: [references/orient.md](references/orient.md).
2. **Fan out four read-only lenses in one message**, as independent child sessions or subagents: **dead code & orphans**, **frozen & superseded**, **duplication & over-abstraction**, **docs/skills/process sprawl**. Every brief demands per-row evidence and a *Rejected candidates* list. Briefs: [references/lens-briefs.md](references/lens-briefs.md). On a repo under about 200 files, run the lenses yourself in sequence.
3. **Merge, then hunt conflicts.** Where one lens calls something dead and another rejects it, that disagreement is your first verification target. Where two lenses independently find the same live consumer, that is strong rejection evidence.
4. **Verify adversarially** yourself. Try to prove every high-payoff row wrong, and default to "refuted" when unsure. Re-run each zero-caller grep without `| head`. Check every row against [references/traps.md](references/traps.md): human-facing callers, name collisions, data coupling, fixture paths, governed removals.
5. **Sort and report** in three buckets: *delete now*, *needs a decision*, *simplify*. Order each by payoff × confidence. Also list what was refuted, the yes/no decisions, and the cheapest next command. Shape: [references/report.md](references/report.md). Follow the `communication` skill.

## Rules

- **Identify, don't delete.** Lenses are read-only, and so is this skill until the human picks rows.
- **No evidence, no row.** A row needs a grep result, a date, a hash match, or a decision-record citation.
- **Deliberate duplication isn't duplication.** Vendored copies with a sync check, generated mirrors and self-contained bundles are designs. Flag one only if its reason is gone.
- **Respect governance.** If a decision record governs a removal, the deliverable is the decision, not the deletion.
- **Lines aren't the only payoff.** Count repo weight (MB) and always-loaded context (agent guides, skill descriptions) separately. A misleading 45-line wrapper can outrank 5k quiet lines.
