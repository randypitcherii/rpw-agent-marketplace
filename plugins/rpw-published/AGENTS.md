# rpw-published Agent Guidelines

For agent role definitions, naming conventions, and dispatch patterns, see:
- **Dispatch protocol** (in-/build coordination *and* out-of-/build auto-dispatch): `plugins/rpw-published/skills/subagent-dispatch/SKILL.md`
- **Build lifecycle**: `plugins/rpw-published/commands/build.md`
- **Code review + PR prep conventions**: `plugins/rpw-published/skills/code-review-and-pr/SKILL.md`

## Vendored copies — two things here are sync sources (#1901)

Editing one of these leaves a generated copy stale, and the equality check runs in the **root gate**, which a fenced wave worker does not run. Nothing in the edited directory hints at the copy, so it is stated here, where every brief already sends you.

| You edited | Now stale | Regenerate / verify |
|---|---|---|
| `skills/<name>/` that an Omnigent bundle vendors (see each bundle's `agents/omnigent/<bundle>/vendored-skills.txt`) | `agents/omnigent/<bundle>/skills/<name>/` | `make sync-agents` / `make sync-agents-check` |
| `skills/communication/references/core-rules.md` | `agents/omnigent/house-standard.md` + each custom bundle's embedded core | `make sync-communication-core` / `make sync-communication-core-check` |

The reverse also holds: **`mcp-servers/lib/` here is a generated copy**, not a source — edit `libs/rpw_mcp_lib/lib/` and run `make sync-mcp-lib`.

**MCP servers register in `mcp-servers/rpw/servers.json`, not `.mcp.json`.** The plugin's `.mcp.json` holds one entry, the `rpw` aggregator (`lib/aggregator.py`, #2215), which fronts every backend listed there.

If a stale copy is outside your fence, report it rather than regenerating it — see `## Sync-coupled fencing` in `skills/wave-supervisor/worker-brief-template.md`.

## Quick Reference

| Role | Model | ID Pattern | Worktree | Issue Level |
|------|-------|-----------|----------|-------------|
| Build Lead | Opus | `build-{feature}` | build worktree | Feature |
| Build Worker | Opus/Sonnet | `bw-{task}` | task worktree (required) | Task |
| Reviewer | Opus | `review-{feature}` | none | — |
| Research Lead | Opus | `research-{topic}` | none | — |
| Research Worker | Sonnet | `rw-{topic}-{n}` | none | — |
| Debug Lead | Opus | `debug-{issue}` | none | — |
| Minion | Haiku | `minion-{action}` | none | — |
| Project Manager | Inherit | `pm-{scope}` | none | — |
| Privacy Reviewer | Opus | `guard-{scope}` | none | — |

## Key Rules

- **One agent, one role, one task** — no multi-role agents
- **All Build Workers use TDD** via superpowers skills
- **Regular merge only** (`git merge --no-ff`) — never squash-merge. See `subagent-dispatch` skill (section 7) for rationale.
- **Max depth = 1** — subagents cannot spawn further subagents. See `subagent-dispatch` skill (section 5) for details.
- **Max fan-out** — 5 Build Workers, 3 Research Workers. See `subagent-dispatch` skill (section 5) for enforcement rules.

## Issue Hierarchy

Agents map to the **epic > feature > task** issue hierarchy:
- **Build Lead** owns the feature issue and creates task breakdowns during planning
- **Build Workers** execute exactly one task each
- Other roles do not own issues
