---
date: 2026-03-05
status: reviewed
review_by: 2026-04-05
---

# Build Command Upgrade Findings

## Summary

Research for upgrading `/build` to support autonomous execution while preserving safety and Cursor compatibility.

## Findings

### Execution Modes

- **Dual mode (recommended)**: Autonomous fast path for straightforward work; full planning mode for complex/risky work.
- Avoid full planning bypass (increases regression risk) and avoid always-on planning gate (too slow for async workflows).

### Git Policy

- Commits allowed without prior approval.
- Destructive git requires explicit yes/no confirmation.
- Squash merges for branch integration.

### Code Simplifier

- Normal work: single Opus code-simplifier.
- Major refactors: three parallel Opus code-simplifier subagents from distinct scopes, then reconcile.

### Beads Orchestration

- Parent bead per `/build` request; feature sub-beads for work units.
- Feature sub-beads = unit of worktree isolation.
- Haiku bead-admin subagents for discovered work; include source metadata.

### Makefile-First

- Discover and prioritize Makefile targets.
- Prefer `make` over ad hoc shell flows.

### Research vs Decisions

- Research in `docs/research/` with freshness metadata.
- Durable decisions in `docs/decisions/` (ADR-style).
- Do not conflate research with binding instructions.

## Recommendations

1. Implement dual-mode execution (autonomous fast path + full planning mode).
2. Add `build.claude.md` as Claude-first variant; keep `build.md` Cursor-safe.
3. Update Makefile for deterministic Cursor vs Claude command linking.
4. Encode Beads hierarchy and follow-up sub-bead policies in command docs.
