# Adversarial Analysis: Subagent Dispatch & Worktree Isolation

**Date:** 2026-03-10
**Scope:** `plugins/rpw-building` — `/build` command, `subagent-dispatch` skill, `AGENTS.md`

---

## 1. Where We Align with Anthropic's Recommendations

**Worktree isolation for parallel agents.** Anthropic's docs explicitly recommend `isolation: "worktree"` for any agent that edits files. Our protocol mandates this and documents the exception for read-only agents. Direct alignment.

**Orchestrator-worker pattern.** Anthropic's multi-agent research system uses a lead agent that decomposes work and delegates to subagents with separate context windows. Our `/build` orchestrator does the same: plan in Phase 1, dispatch in Phase 2, synthesize in Phase 3-5. This matches the recommended architecture.

**Full context in each subagent prompt.** Our guardrail #3 ("Each agent prompt MUST include full task context — agents don't share conversation history") directly implements Anthropic's guidance that subagents need self-contained prompts since they have no shared memory.

**Squash-merge strategy.** Collapsing implementer work into clean commits on the feature branch is sound. It prevents polluting history with intermediate agent churn and simplifies conflict resolution.

**Fan-out limit of 5.** Reasonable constraint. Anthropic's research shows token usage explains 80% of performance variance — capping parallelism bounds cost while still capturing the parallelism benefit.

**Named agents with role-based patterns.** Using `impl-{bead-id}`, `review-{bead-id}`, etc. provides traceability. This aligns with Anthropic's guidance on descriptive agent naming.

---

## 2. Where We Diverge or Potentially Violate Best Practices

### 2a. Missing: Agent Teams consideration

**Issue:** Anthropic shipped Agent Teams (Opus 4.6) as a first-class feature specifically for multi-agent coordination. Agent Teams provide inter-agent communication, shared task tracking, and the ability to interact with individual teammates directly — none of which subagents support. Our architecture uses only subagents.

**Risk:** Subagents are fire-and-forget workers that report back to the orchestrator. If implementer A discovers that implementer B's interface contract needs to change, there is no mechanism for A to notify B. The orchestrator must manually detect this post-hoc during fan-in. Agent Teams would handle this natively.

**Recommendation:** Evaluate whether `/build` should use Agent Teams for cross-cutting work (e.g., frontend + backend + tests spanning the same feature). Keep subagents for truly independent, isolated tasks.

### 2b. No context engineering strategy for the orchestrator

**Issue:** Anthropic's context engineering guidance emphasizes that long-running orchestrators must actively manage their own context window — clearing stale tool results, summarizing completed phases, and keeping context "informative yet tight." Our `/build` command has 6 phases that accumulate tool results, subagent outputs, verification logs, and bead tracking data.

**Risk:** By Phase 5, the orchestrator's context window may be severely bloated with Phase 1 planning artifacts and Phase 2 subagent outputs that are no longer relevant. Anthropic's research shows context editing reduced token consumption by 84% in 100-turn evaluations. Without it, complex builds will degrade or fail.

**Recommendation:** Add explicit context hygiene instructions: summarize-and-discard completed phase artifacts, use pagination for large diffs, and leverage context editing if available.

### 2c. `bypassPermissions` mode is under-documented

**Issue:** The dispatch pattern example includes `mode: "bypassPermissions"` with no guardrails around when this is appropriate. The build.md command says "destructive git commands still require explicit yes/no confirmation" but doesn't address the permission bypass for file operations.

**Risk:** A subagent with `bypassPermissions` can overwrite, delete, or create any file without user confirmation. If the orchestrator's task decomposition is wrong (e.g., two agents assigned overlapping files), `bypassPermissions` removes the last safety net.

**Recommendation:** Document explicit criteria for when `bypassPermissions` is allowed vs. prohibited. Consider restricting it to worktree-isolated agents only (where blast radius is contained).

### 2d. No error budget or reliability math

**Issue:** Industry research shows reliability multiplies: 5 agents at 95% each = 77% system reliability. Our protocol dispatches up to 5 concurrent implementers, each of which must succeed AND squash-merge cleanly. We document a fallback ("fall back to sequential single-agent execution") but don't specify when to trigger it or how to recover partial progress.

**Risk:** A 5-agent parallel dispatch where agent 3 fails leaves the orchestrator in an ambiguous state. Do agents 1, 2, 4, 5's squash-merges still apply? What if agent 3's work was a dependency for verification in Phase 3?

**Recommendation:** Add explicit failure handling: (1) define which failures are retriable vs. fatal, (2) specify whether partial results are kept or rolled back, (3) add a circuit-breaker pattern — if N of M agents fail, abort and fall back to sequential.

### 2e. Merge conflict handling is absent

**Issue:** Despite worktree isolation AND file-level separation (guardrail #4), merge conflicts can still occur when agents modify files that share structural dependencies (e.g., both add exports to an index file, both modify a shared config, both add entries to a manifest).

**Risk:** The squash-merge step silently assumes clean merges. If a conflict occurs, the protocol doesn't specify who resolves it — the orchestrator, the original subagent (which has already exited), or a new subagent.

**Recommendation:** Add a merge conflict protocol: (1) orchestrator detects conflicts during squash-merge, (2) spawns a dedicated `merge-resolver` agent with both branches in context, (3) runs verification after resolution.

---

## 3. Risks We Haven't Addressed

### 3a. Depth limit is stated but unenforced

The guardrail says "Subagents should NOT spawn their own implementation subagents. One level of delegation only." But this is a prompt-level instruction, not a technical enforcement. A subagent that receives a complex task may naturally try to delegate further, especially since the AGENTS.md and skills are available in each worktree.

**Recommendation:** Either technically prevent nested dispatch (e.g., strip the `subagent-dispatch` skill from implementer prompts) or add explicit "you are a leaf agent — do not dispatch subagents" instructions to every implementer prompt template.

### 3b. Cost runaway risk

Five parallel Opus agents each consuming their own context window is expensive. If an implementer hits a difficult problem and burns through extensive tool use cycles, there's no budget cap or watchdog.

**Recommendation:** Add token budget guidance per subagent role. Consider using Sonnet for straightforward implementation tasks and reserving Opus for complex ones (matching Anthropic's own pattern of Opus lead + Sonnet workers).

### 3c. Stale worktree / branch accumulation

If the orchestrator crashes, loses context, or the user abandons mid-build, implementer worktrees and branches persist as orphans. The protocol describes cleanup "immediately after squash-merge" and "on merge approval" but has no crash-recovery path.

**Recommendation:** Add a cleanup-on-startup check: before any `/build`, scan for orphaned worktrees from previous failed builds and offer to clean them up.

### 3d. No observability into subagent progress

Once dispatched with `run_in_background: true`, subagents are black boxes until completion. For a 30-minute build with 5 parallel agents, the user has no visibility into progress, blockers, or failures until everything finishes.

**Recommendation:** Consider periodic status checks or structured output from subagents at key milestones.

### 3e. Environment setup in worktrees

Anthropic's docs explicitly warn: "Remember to initialize your development environment in each new worktree." Our protocol doesn't mention dependency installation, virtual environment setup, or Makefile bootstrapping in implementer worktrees.

**Recommendation:** Add a worktree initialization step to the dispatch protocol: after entering the worktree, run `make install` or equivalent before starting implementation work.

---

## 4. Opportunities We're Missing

### 4a. Mixed-model dispatch

Anthropic's research system uses Opus as the lead and Sonnet as workers, achieving 90.2% improvement over single-agent Opus. Our protocol always uses "latest Opus" for normal work. Using Sonnet for straightforward implementations (simple file changes, test additions) would cut costs significantly while maintaining quality.

### 4b. Evaluator-optimizer pattern

Anthropic documents this as a core composable pattern: one agent generates, another evaluates, and results feed back iteratively. Our Phase 3 verification is a single pass. For critical code paths, a dedicated evaluator agent that challenges the implementation before merge would catch more issues.

### 4c. Structured output for fan-in

When subagents complete, their results come back as unstructured text. Requiring a structured completion report (files changed, tests added, risks identified, confidence level) would make the orchestrator's synthesis more reliable and enable automated quality gates.

### 4d. Context compression at subagent boundaries

Anthropic's research shows subagents provide natural compression points — they explore deeply within their own context window and return only the essential findings. Our protocol could explicitly leverage this by requiring subagents to return concise summaries rather than full logs.

### 4e. Leveraging Agent Teams for code review

Phase 3 (Verify and Review) is currently single-threaded. Using Agent Teams to run security review, test coverage review, and performance review as communicating teammates would be faster and more thorough than a single sequential pass.

---

## 5. Specific Recommendations (Priority-Ordered)

| Priority | Recommendation | Effort | Impact |
|----------|---------------|--------|--------|
| P0 | Add merge conflict handling protocol | Low | High — silent merge failures corrupt the build |
| P0 | Add explicit failure/retry semantics for subagent dispatch | Low | High — current failure state is undefined |
| P1 | Add context hygiene instructions for the orchestrator across phases | Low | High — prevents context exhaustion on complex builds |
| P1 | Add worktree environment initialization step | Low | Medium — prevents build failures from missing deps |
| P1 | Add orphan worktree cleanup on `/build` startup | Low | Medium — prevents branch/worktree accumulation |
| P1 | Document `bypassPermissions` criteria explicitly | Low | Medium — security hygiene |
| P2 | Evaluate Agent Teams for cross-cutting implementations | Medium | High — enables inter-agent coordination |
| P2 | Add mixed-model dispatch (Sonnet for simple tasks) | Medium | Medium — significant cost reduction |
| P2 | Require structured completion reports from subagents | Medium | Medium — improves fan-in reliability |
| P3 | Enforce depth limit technically, not just via prompt | Low | Low — edge case but could cause cascading costs |
| P3 | Add evaluator-optimizer pattern for critical paths | High | Medium — diminishing returns for most work |
| P3 | Add token budget guidance per subagent role | Low | Low — cost awareness |

---

## Summary

The implementation is architecturally sound and aligns well with Anthropic's orchestrator-worker pattern. The biggest gaps are operational: **undefined failure semantics**, **missing merge conflict handling**, **no context management strategy for the long-running orchestrator**, and **not leveraging Agent Teams for work that needs inter-agent coordination**. The P0 items (merge conflicts and failure handling) are the most likely to cause real problems in practice — they represent undefined behavior in scenarios that will inevitably occur.

---

## Sources

- [Create custom subagents - Claude Code Docs](https://docs.anthropic.com/en/docs/claude-code/sub-agents)
- [Orchestrate teams of Claude Code sessions](https://code.claude.com/docs/en/agent-teams)
- [How we built our multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system)
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents)
- [Multi-agent workflows often fail - GitHub Blog](https://github.blog/ai-and-ml/generative-ai/multi-agent-workflows-often-fail-heres-how-to-engineer-ones-that-dont/)
- [Why Your Multi-Agent System is Failing - Towards Data Science](https://towardsdatascience.com/why-your-multi-agent-system-is-failing-escaping-the-17x-error-trap-of-the-bag-of-agents/)
- [Agent Teams vs Subagents](https://charlesjones.dev/blog/claude-code-agent-teams-vs-subagents-parallel-development)
- [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Subagents in the SDK](https://docs.anthropic.com/en/docs/claude-code/sdk/subagents)
