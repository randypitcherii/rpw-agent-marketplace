# Beads Hierarchy Standard

Reference document for the 3-level beads hierarchy pattern used in `/build` sessions.

## Three-Level Hierarchy

| Level | Type | Scope | Created By |
|-------|------|-------|------------|
| Epic | `--type=epic` | Multi-session initiative spanning multiple builds | Human or backlog grooming |
| Feature | `--type=feature` | Single `/build` scope — one PR, one feature branch | Build Lead (Phase 1) |
| Task | `--type=task` | Single Build Worker unit — one worktree, one focused change | Build Lead (Phase 1) |

### Examples

| Type | Example Titles |
|------|----------------|
| Epic | "Migrate authentication to OAuth2", "V2 API rollout" |
| Feature | "Add OAuth provider support", "Standardize beads hierarchy" |
| Task | "Update build.md with hierarchy steps", "Add hierarchy tests" |

## Hierarchy Rules

- Every task bead **MUST** have a feature parent during a `/build` session
- Feature beads **MAY** have an epic parent (linked at build start, if an epic exists)
- Epics are **optional** — standalone features are fine for ad-hoc work
- **Max depth**: epic → feature → task (no deeper nesting)
- Tasks **cannot** be parents of other tasks — use a feature for grouping

## Naming Conventions

All titles use imperative mood:

- **Epic**: Broad scope — "Migrate authentication to OAuth2"
- **Feature**: PR-sized scope — "Add OAuth provider support"
- **Task**: Worker-sized scope — "Update build.md with hierarchy steps"

## Command Workflow

```bash
# During /build Phase 1 — Build Lead creates hierarchy:

# 1. Link feature to existing epic (if applicable)
bd dep add <feature-bead> <epic-bead> --type=parent-child

# 2. Create task beads as children of the feature
bd create --title="Implement X" --type=task --priority=2
bd dep add <task-bead> <feature-bead> --type=parent-child

# 3. Verify hierarchy
bd epic status
```

## Lifecycle

| Type | Opens | Closes |
|------|-------|--------|
| Epic | Human creates manually | `bd epic close-eligible` after all feature children done |
| Feature | Build Lead in Phase 1 | Build Lead in Phase 5, after PR merged |
| Task | Build Lead in Phase 1 | Build Lead after worker's branch merged |

## When NOT to Use Hierarchy

| Situation | Approach |
|-----------|----------|
| Quick one-off fix (outside `/build`) | Single task bead, no feature wrapper |
| Bug report | Standalone bug bead; link to epic if part of larger effort |
| Research spike | Standalone task bead |
