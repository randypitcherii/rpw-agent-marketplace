---
date: 2026-03-08
status: reviewed
review_by: 2026-04-08
---

# Build Custom Subagents Investigation

## Scope

Evaluate whether `/build` should adopt custom subagents named `researcher`, `investigator`, and `task-assistant` now.

## Evidence Reviewed

- `plugins/rpw-building/commands/build.claude.md`
- `plugins/rpw-building/commands/build.md`
- `plugins/rpw-building/.claude-plugin/plugin.json`
- Current runtime subagent tool options available to this environment

## Findings

1. The `/build` docs currently list custom subagent definitions as a follow-up research item, not an implemented policy.
2. The `rpw-building` plugin has no `agents` directory and its plugin manifest declares only `skills` and `commands`.
3. The currently available subagent types in this environment do not include `researcher`, `investigator`, or `task-assistant` as valid registered types.
4. Existing built-in subagent types already cover the intended responsibilities:
   - research/discovery -> `explore` or `generalPurpose`
   - investigation/review -> `code-reviewer` or `generalPurpose`
   - execution support -> `task-agent` or targeted built-ins

## Recommendation

**Adopt later (not now).**

Keep using built-in subagent types in `/build` until there is a validated plugin-level custom agent registration path and compatibility proof in both Claude and Cursor execution surfaces.

## Rationale

- Adopting now would require undocumented assumptions about agent registration and invocation semantics.
- Current behavior is already covered by built-in subagent types with lower operational risk.
- Deferring preserves reliability of `/build` while still allowing future enhancement when platform support is explicit.

## Risks

### If adopted now

- Command/runtime mismatch: references to non-registered agent types can fail at execution time.
- Compatibility drift between Claude-first and Cursor-safe command variants.
- Increased maintenance burden for little immediate capability gain.

### If deferred

- Slightly less semantic clarity in task routing language.
- Mitigation: codify preferred built-in mappings in future `/build` refinements.

## Exit Criteria For Future Adoption

- Documented custom-agent registration contract for this plugin stack.
- At least one working example in-repo with tests/validation checks.
- Verified behavior in both command variants and release validation flow.
