# Marketplace Feedback — reference

Supporting detail for [SKILL.md](SKILL.md): the full label taxonomy, per-type body skeletons, and the `.github/ISSUE_TEMPLATE/` mapping. Always confirm the live set with `gh label list` before applying — this table is the intent, the repo is the source of truth.

## Label taxonomy

**Type (exactly one):**

| Label | When |
|-------|------|
| `type: bug` | Something is broken or behaves incorrectly. |
| `type: feature` | New capability / enhancement — a PR-sized deliverable. |
| `type: task` | A single, self-contained unit of work (often part of a larger effort). |
| `type: epic` | Multi-session initiative spanning several issues/PRs. |
| `documentation` | Pure docs gap — missing/wrong/unclear docs, no code change. |

**Priority (exactly one):**

| Label | Meaning |
|-------|---------|
| `priority: P0` | Critical — broken core flow, drop everything. |
| `priority: P1` | High — important, schedule soon. |
| `priority: P2` | Medium — the default when unsignaled. |
| `priority: P3` | Low. |
| `priority: P4` | Backlog — someday/maybe. |

**Effort / status modifiers:**

| Label | When |
|-------|------|
| `quick win` | Small, well-scoped, high-value — low effort, clear payoff (e.g. a one-file bug with an obvious fix). Add alongside the type label. |
| `status: in-progress` | Applied by `make build-claim` when work starts — do NOT set at filing time. |
| `status: blocked` | Waiting on a dependency; add a comment naming the blocker. |

**Friction** has no dedicated label: decide whether the fix is behavioral (`type: bug`) or an ergonomics addition (`type: feature`), apply that, and lead the summary with `friction:`.

## Per-type body skeletons

### Bug
```
## Summary
<what's broken, one paragraph>
## Reproduction
<exact command/steps>  → observed: <...>  expected: <...>
## Impact
<who/what is blocked, how often, workaround if any>
## Likely cause
<file:line or subsystem, if known>
## Suggested fix
<concrete, minimal>
## Scope
<how contained — single file? one MCP server? note `quick win`>
## Related
- #N
```

### Feature
```
## Summary
<capability wanted + motivation>
## Desired shape
<what "good" looks like — behavior / API / UX>
## Why
<value, who benefits, what it unblocks>
## Sketch
<optional: approach, files, references>
## Acceptance
- [ ] <observable outcome>
## Related
- #N
```

### Docs
```
## Summary
<what doc is missing/wrong/unclear and where>
## Impact
<what a reader gets wrong without it>
## Suggested content
<what it should say>
## Related
- #N
```

### Friction
Use the bug or feature skeleton (whichever the fix is), and lead the Summary with `friction:` plus the pain: what the workflow makes you do, how often, and what it should do instead.

## `.github/ISSUE_TEMPLATE/` mapping

Manual filers on GitHub get the same shapes via the repo-root templates:

| Template | Type label | Body |
|----------|-----------|------|
| `bug.md` | `type: bug` | Bug skeleton |
| `feature.md` | `type: feature` | Feature skeleton |
| `friction.md` | `type: bug` (default) | Friction (bug/feature) skeleton |

`config.yml` keeps blank issues enabled (agents file structured issues directly via `gh`) and points humans at this flow. Keep the templates and these skeletons in sync — if one changes, change both.
