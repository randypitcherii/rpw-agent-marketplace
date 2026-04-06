# /build Naming Convention — Canonical Reference

**Date:** 2026-03-10
**Status:** Proposed
**Scope:** Definitive naming guide for bead hierarchy, agent roles, and build lifecycle terminology

---

## Naming Principles

1. **No overloaded terms.** Every name must mean exactly one thing in this system. If a term already has strong meaning in CI/CD, git, or project management, avoid it or qualify it.
2. **Role names describe function, not rank.** "Lead" implies authority over people. Agents don't have feelings. Use names that describe what the agent *does*.
3. **Bead levels match industry conventions where possible.** Developers already think in milestone > epic > story > task. Deviating without reason creates friction.
4. **Consistency between code references and conversation.** The name in a prompt template, the name in a bead label, and the name humans use in Slack must all be the same string.

---

## Recommended Changes from Original Proposal

| Original | Recommended | Reason |
|----------|-------------|--------|
| Build Manager | **Build Lead** | "Manager" implies a human PM role. "Lead" is the established Claude Code term (agent teams use "team lead"). Aligns with existing `subagent-dispatch.md` orchestrator pattern. |
| Task Lead | **Build Worker** | "Task lead" suggests authority over a team. These agents lead nothing — they implement one task in isolation. "Build Worker" aligns with the "Research Lead / Research Worker" naming pattern → "Build Lead / Build Worker". Uses TDD via superpowers skills by default. |
| Lead Researcher | **Research Lead** | Adjective-noun order is more natural in English and matches "Build Lead" pattern. |
| Junior Researcher | **Research Worker** | "Junior" implies skill level. These agents aren't less capable — they're scoped narrower. "Worker" describes the role without implying competence hierarchy. |
| TDD Subagent | *(Merged into Build Worker)* | Build Workers use TDD via superpowers skills directly — they are test-driven by default. No separate agent needed. |
| Code Simplifier | **Simplifier** | Drop "Code" — all agents work on code. Shorter names are better in prompts and logs. |
| PR Reviewer | **PR Security Guard** | Reviews code on the feature branch for security, regressions, and quality. "Guard" emphasizes the protective function. Iterates with Build Workers on fixes. |
| Runner | **Minion** | "Minion" is preferred. Direct, memorable, and clearly conveys a lightweight helper agent. |
| Feature (bead level) | **Feature** | Keep as-is. This is the right term. |
| Build branch | **Feature branch** | "Build branch" conflicts with CI/CD terminology where "build" means compilation/CI pipeline. Every developer already knows what a "feature branch" is. The existing `build.md` already uses "feature branch" in most places — make it universal. |
| Build run / build session | **Build cycle** | A single invocation of `/build` from start to close. "Run" conflicts with CI "runs". "Session" conflicts with Claude Code "sessions". "Cycle" is unique to this system and implies the phased nature (plan > implement > verify > deliver). |

---

## Bead Hierarchy

Three levels. Only Feature is mandatory.

```
Milestone (optional)
  └── Feature (required — one per build cycle)
        ├── Task (implementation unit)
        ├── Task
        └── Discovery (non-blocking: tech debt, bugs, TODOs)
```

### Definitions

| Level | Definition | Created By | Lifecycle |
|-------|-----------|------------|-----------|
| **Milestone** | A target with a deadline or external dependency. Groups features toward a goal. Examples: "MVP release", "demo day", "Q2 launch". | Human | Spans multiple build cycles. Closed when all child features are done. |
| **Feature** | One build cycle's worth of work. The unit of PR delivery. Must be completable in a single `/build` invocation. Examples: "Add OAuth2 flow", "Redesign settings page". | Human or Build Lead | Created in Phase 1 (Plan). Closed in Phase 6 (Retrospective). |
| **Task** | A discrete implementation unit within a feature. Assigned to exactly one Build Worker. Must be independently testable. Examples: "Create auth middleware", "Add token refresh logic", "Write integration tests". | Build Lead | Created in Phase 1. Closed when Build Worker completes and squash-merges. |
| **Discovery** | Non-blocking work found during implementation. Not part of the current build cycle's scope. Examples: "Tech debt: extract shared utility", "Bug: race condition in cache", "TODO: add rate limiting". | Any agent (via Minion) | Created during Phase 2. Rationalized by Build Lead in Phase 6. May become future Features. |

### Bead Naming Pattern

```
{level}-{slug}

milestone-q2-launch
feature-oauth2-flow
task-auth-middleware
task-token-refresh
discovery-cache-race-condition
```

---

## Agent Role Reference

### Tier 1: Orchestration

| Role | Model | Dispatched By | Purpose | Agent ID Pattern |
|------|-------|--------------|---------|-----------------|
| **Build Lead** | Opus | Human (via `/build`) | Owns one build cycle. Creates tasks, dispatches agents, reviews results, manages feature branch, rationalizes discoveries, dispatches delivery and retrospective. | `build-{feature-slug}` |

### Tier 2: Implementation

| Role | Model | Dispatched By | Purpose | Agent ID Pattern |
|------|-------|--------------|---------|-----------------|
| **Build Worker** | Sonnet (default) or Opus (complex tasks) | Build Lead | Picks up one task. Creates worktree off feature branch. Implements using TDD via superpowers skills, tests, squash-merges back, cleans up worktree, reports completion. Test-driven by default. | `bw-{task-slug}` |

### Tier 3: Review

| Role | Model | Dispatched By | Purpose | Agent ID Pattern |
|------|-------|--------------|---------|-----------------|
| **PR Security Guard** | Opus | Build Lead (Phase 3) | Reviews code on the feature branch for security, regressions, and quality. Produces findings with severity and fix suggestions. Iterates with Build Workers on fixes. | `guard-{feature-slug}` |
| **Simplifier** | Opus | Build Lead (Phase 3) | Refactoring pass. For major refactors, three Simplifiers run in parallel with distinct scopes: (1) structure, (2) naming, (3) logic. | `simplify-{feature-slug}[-scope]` |

### Tier 4: Research

| Role | Model | Dispatched By | Purpose | Agent ID Pattern |
|------|-------|--------------|---------|-----------------|
| **Research Lead** | Opus | Build Lead or Build Worker | Deep research requiring preserved context. Can spawn Research Workers and Minions for parallel search. Synthesizes findings. | `research-{topic-slug}` |
| **Research Worker** | Sonnet | Research Lead | Parallelized search, summarization, web lookups. Reports back to Research Lead. | `rw-{topic-slug}-{n}` |

### Tier 5: Utility

| Role | Model | Dispatched By | Purpose | Agent ID Pattern |
|------|-------|--------------|---------|-----------------|
| **Minion** | Haiku | Any agent | Lightweight tasks: log searching, code search, running chatty commands, bead CRUD, PR creation/acceptance, discovery logging. Context-efficient by design. | `minion-{action-slug}` |

---

## Glossary

| Term | Definition |
|------|-----------|
| **Build cycle** | One complete invocation of `/build`, from Phase 1 (Plan) through Phase 6 (Retrospective). |
| **Feature branch** | The git branch created for this build cycle. Named from the feature slug. All task worktrees branch from this. |
| **Build worktree** | The git worktree where the Build Lead operates. Sits on the feature branch. All orchestration, bead tracking, and merge coordination happen here. |
| **Task worktree** | A git worktree created by a Build Worker, branching off the feature branch. Cleaned up after squash-merge. |
| **Squash-merge** | The only permitted merge strategy for task worktrees back to the feature branch. Non-negotiable. |
| **Fan-out** | The number of concurrent agents dispatched at one level. Max 5 Build Workers per Build Lead. Max 3 Research Workers per Research Lead. |
| **Depth** | Nesting level of agent spawning. Build Lead = depth 0. Build Worker = depth 1. Minion spawned by Build Worker = depth 2. Max depth = 2. |
| **Discovery** | Work item found during implementation that is out of scope for the current build cycle. Logged as a bead, rationalized at close. |
| **Rationalize** | The Build Lead's Phase 6 activity of reviewing all discoveries, deduplicating, tagging, and deciding which become future features vs. which are noise. |
| **Dispatch** | The act of creating and launching a subagent with a specific role, prompt, and (optionally) worktree isolation. |
| **Completion report** | Structured output every Build Worker must produce on finishing: status, files changed, test results, scope creep, merge readiness. |

---

## Naming Rules

### Agent IDs
- Lowercase, hyphen-separated: `bw-auth-middleware`, `guard-oauth2-flow`
- Always prefixed with role abbreviation: `bw-`, `guard-`, `simplify-`, `research-`, `rw-`, `minion-`
- Suffix is the slug of the bead or topic the agent is working on
- No version numbers, timestamps, or UUIDs in agent IDs — use bead IDs for traceability

### Bead Slugs
- Lowercase, hyphen-separated: `oauth2-flow`, `cache-race-condition`
- Max 40 characters
- Must be unique within a build cycle (features globally unique, tasks unique within feature)

### Branch Names
- Feature branch: `{feature-slug}` (e.g., `oauth2-flow`)
- Task worktree branch: `{feature-slug}/{task-slug}` (e.g., `oauth2-flow/auth-middleware`)

### Prompt Templates
- Stored in `plugins/rpw-building/skills/agent-prompts/`
- One file per role: `build-lead.md`, `build-worker.md`, `pr-security-guard.md`, `simplifier.md`, `research-lead.md`, `research-worker.md`, `minion.md`
- Use `{{variable}}` syntax for parameterized values

---

## Edge Cases

### When a Build Worker needs research
The Build Worker dispatches a Research Lead (or, for quick lookups, a Minion). The Build Worker does NOT become a researcher — role boundaries are strict. This prevents context contamination and keeps the Build Worker focused on its task worktree.

### Naming the retrospective researcher
It's just a Research Lead with a retrospective-scoped topic: `research-retro-{feature-slug}`. No special role needed.

### When a single agent plays multiple roles
It doesn't. If a task requires both implementation and deep research, the Build Lead should split it into a research task and an implementation task with a dependency. One agent, one role, one bead.

### What if a build cycle spans multiple features?
It shouldn't. One build cycle = one feature = one PR. If the work is bigger, decompose it into multiple features under a milestone and run multiple build cycles (potentially in parallel via agent teams or manual parallel sessions per the swarm research).

### Discovery vs. Task
If found work is blocking the current task, it's a new Task (created by Build Lead, not the Build Worker). If it's non-blocking, it's a Discovery. The Build Worker never creates Tasks — only the Build Lead does.

---

## Migration from Current Terminology

The existing `build.md` uses some terms that should be updated to match this convention:

| Current in build.md | Canonical term |
|---------------------|---------------|
| "implementer agents" | Build Worker |
| "build worktree" | Build worktree (no change needed) |
| "build worker worktrees" | Task worktree (the worktree belongs to the task, not the role) |
| "feature sub-beads" | Task (they're tasks within a feature) |
| "bead-admin subagents" | Minion (with bead-admin action) |
| "build's feature branch" | Feature branch (drop the possessive — there's only one per build cycle) |
| "code-simplifier subagents" | Simplifier |
| "impl-{bead-id}" | `bw-{task-slug}` (use slug not bead ID for readability) |
| "verify-{bead-id}" | `minion-verify-{task-slug}` (verification is a Minion action) |
