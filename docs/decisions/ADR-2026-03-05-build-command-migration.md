# ADR-2026-03-05: Build Command Migration

**Status:** Accepted
**Date:** 2026-03-05
**Provenance:** Transformed from `docs/plans/2026-03-05-build-command-migration-design.md`

## Context

`/build` was interaction-heavy for straightforward work and optimized for synchronous human presence. The migration needed to preserve safety while improving autonomous throughput and preparing for marketplace-ready standards with reliable Cursor compatibility.

## Decision

Adopt a dual-mode model for `/build`:

- Use full planning mode for complex, risky, or ambiguous work.
- Use an autonomous fast path for safe, straightforward work without requiring approval at each gate.
- Escalate to humans only for destructive or dangerous actions, security-sensitive requests, or when no safe path exists.

Adopt supporting policies:

- Non-destructive git by default; destructive git actions require explicit human confirmation.
- Makefile-first execution for standardized build/test/run/deploy flows.
- Beads-first orchestration using parent beads and feature sub-beads with worktree isolation.
- Separate exploratory findings (`docs/research/`) from durable decisions (`docs/decisions/`) and instruction memory files.
- Route code-simplifier usage by change size, including parallel review for major refactors.

## Consequences

- `/build` retains safety guardrails while reducing unnecessary waiting for simple tasks.
- Planning discipline is preserved for higher-risk work.
- Operational expectations become clearer across Claude-first and Cursor-compatible workflows.
- Documentation hygiene improves by separating historical research from durable, decision-level policy.

## Alternatives Considered

- Keep fully interactive planning always on (safer, but too slow for async/simple work).
- Add a full planning bypass (faster, but weaker rigor and higher regression risk).
