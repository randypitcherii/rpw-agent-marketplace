---
date: 2026-03-08
status: reviewed
review_by: 2026-04-15
related_issue: rpw-agent-assets-nzl
---

# Subagent-Created-Subagent Feasibility

## Summary

Subagent-created-subagent orchestration is **feasible with constraints** for `/build`, and can improve throughput for independent, bounded subtasks. It should be treated as a controlled escalation pattern, not a default execution mode.

## Current Policy Baseline

- `plugins/rpw-building/commands/build.md` allows nested behavior only as: "Ensure task handlers can create their own subagents when supported."
- `plugins/rpw-building/commands/build.claude.md` tracks this topic as mandatory follow-up research but does not define operating guardrails.

Result: policy intent exists, but execution boundaries are underspecified.

## Feasibility Assessment

### What Works Well

- Fan-out for independent research or verification subtasks.
- Delegation from a feature-task subagent to domain-specific helpers.
- Parallel read-heavy analysis where context separation lowers interference risk.

### Main Risks

- **Runaway recursion**: uncontrolled depth or breadth can create agent storms.
- **Accountability blur**: unclear ownership of final decisions and outputs.
- **Context loss**: deeper nesting can drop key constraints from parent scope.
- **Conflicting edits**: multiple writing agents can collide in shared files.
- **Cost/latency variance**: unconstrained spawning can inflate runtime unpredictably.

## Recommendation

Adopt nested spawning as a **guardrailed capability**:

1. Allow only when tasks are independent and clearly scoped.
2. Keep ownership with the direct parent task handler.
3. Enforce explicit limits for depth, fan-out, and write access.
4. Require fallback to single-agent execution when guardrails are not met.

## Proposed Guardrails for `/build`

- **Depth limit:** maximum depth 2 (`parent -> subagent -> child subagent`), no further recursion.
- **Fan-out limit:** one spawning agent may create at most 3 child subagents per task phase.
- **Single writer rule:** only one agent may edit files per task unit; additional children should be read-only unless explicitly promoted.
- **Explicit spawn contract:** each spawn includes objective, scope boundaries, expected artifact, and completion signal.
- **Parent accountability:** spawned outputs are advisory until validated and integrated by the spawning parent.
- **Stop conditions:** abort nested spawning on conflicting file targets, ambiguous ownership, or repeated retries without progress.
- **Traceability:** log spawned-agent intent and outcome in task notes (or Beads notes when enabled) so handoff survives session changes.

## Default Decision Rule

If a subtask can be completed safely by the current agent without context overload, do **not** spawn. Spawn only when decomposition yields clear concurrency or specialization gains.

## Suggested Follow-Up

- Add concise policy references in both build command docs to this note.
- Revisit after 2-4 real `/build` executions that use nested spawning and update this note with observed outcomes.
