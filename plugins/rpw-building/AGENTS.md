# rpw-building Agent Guidelines

For agent role definitions, naming conventions, and dispatch patterns, see:
- **Dispatch protocol**: `plugins/rpw-building/skills/subagent-dispatch/SKILL.md`
- **Auto-dispatch (outside /build)**: `plugins/rpw-building/skills/auto-dispatch/SKILL.md`
- **Build lifecycle**: `plugins/rpw-building/commands/build.md`

## Quick Reference

| Role | Model | ID Pattern | Worktree | Bead Level |
|------|-------|-----------|----------|------------|
| Build Lead | Opus | `build-{feature}` | build worktree | Feature |
| Build Worker | Opus/Sonnet | `bw-{task}` | task worktree (required) | Task |
| PR Security Guard | Opus | `guard-{feature}` | none | — |
| Simplifier | Opus | `simplify-{feature}` | none | — |
| Research Lead | Opus | `research-{topic}` | none | — |
| Research Worker | Sonnet | `rw-{topic}-{n}` | none | — |
| Debug Lead | Opus | `debug-{issue}` | none | — |
| Minion | Haiku | `minion-{action}` | none | — |
| Project Manager | Inherit | `pm-{scope}` | none | — |
| Privacy Reviewer | Opus | `guard-{scope}` | none | — |

## Key Rules

- **One agent, one role, one bead** — no multi-role agents
- **All Build Workers use TDD** via superpowers skills
- **Regular merge only** (`git merge --no-ff`) — never squash-merge. See `subagent-dispatch` skill (section 7) for rationale.
- **Max depth = 1** — subagents cannot spawn further subagents. See `subagent-dispatch` skill (section 5) for details.
- **Max fan-out** — 5 Build Workers, 3 Research Workers. See `subagent-dispatch` skill (section 5) for enforcement rules.

## Bead Hierarchy

Agents map to the **epic > feature > task** bead hierarchy:
- **Build Lead** owns the feature bead and creates task beads during planning
- **Build Workers** execute exactly one task bead each
- Other roles do not own beads

See `docs/beads-hierarchy-standard.md` for the full standard.
