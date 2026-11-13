---
name: marketplace-feedback
description: Use when filing a bug, feature request, docs gap, or friction report AGAINST the rpw-agent-marketplace itself — its plugins, skills, commands, or MCP servers (not the user's own projects). Trigger on "file a bug about this plugin / the marketplace", "report feedback on rpw", "this MCP tool is broken", or the /feedback command. Resolves the target repo, classifies the report, applies house labels, and drafts the issue in the standard body shape.
---

# Marketplace Feedback

Turn "this marketplace thing is broken / missing / annoying" into a **well-formed GitHub issue** — correct repo, house labels, consistent body — in one guided step. This is the standard reporting path for feedback about the marketplace and its components. Full label taxonomy, per-type body shapes, and the issue-template mapping: [reference.md](reference.md).

## When to invoke

Use when the target of the feedback is **this marketplace** — a plugin, skill, command, hook, or MCP server under `plugins/`, or the build/runtime tooling. Triggers: "file a bug about this plugin", "report feedback on rpw", "this MCP tool returns X", "we should add Y to the marketplace", "the /build skill misfires on Z", or the `/feedback` command.

**Skip when** the feedback is about the *user's own* project (file it there with `gh` directly), or the fix is fast enough to just do inline. For analyzing plugin/project *health* (not filing feedback), use `/plugin-feedback` or `/project-feedback` instead.

**Composition:** the `issue-creation` skill is the default issue-authoring path for any repo; this skill is its marketplace-scoped specialization. Everything generic — duplicate search, the real-label-set rule, HEREDOC filing, title convention, reporting the URL — comes from `issue-creation` and is not restated here. Within this scope, the three deltas below win.

## Deltas over `issue-creation`

### 1. Resolve the target repo + component
- Repo = this marketplace repo: `gh repo view --json nameWithOwner -q .nameWithOwner` (owned, so ownership detection is moot).
- Name the **component** — the plugin + the specific skill/command/MCP server (e.g. `rpw-published / google-drive MCP`). It leads the title (`<component>: <summary>`) and the body, so triage is instant.

### 2. House label taxonomy
Full table in [reference.md](reference.md):
- **exactly one type**: `type: bug` | `type: feature` | `type: epic` | `type: task`, or `documentation` for pure docs.
- **exactly one priority**: `priority: P0`…`priority: P4`; default `priority: P2` unless the user signals urgency.
- **`quick win`** when the fix is small, well-scoped, and high-value.
- **Friction** has no label: file it as `type: bug` or `type: feature` (whichever the fix is) and lead the summary with `friction:`.

If the type is ambiguous, ask ONE clarifying question, then proceed.

### 3. Body shape
Sections in this order (drop what doesn't apply): **Summary** · **Reproduction** (bugs: steps + observed vs expected) · **Impact** · **Likely cause** · **Suggested fix / desired shape** · **Scope** · **Related**. Per-type skeletons are in [reference.md](reference.md); `.github/ISSUE_TEMPLATE/` carries the same shape for manual filers.

Then file via `issue-creation` §6 and echo the URL, labels, and component. If the user was mid-task, offer to keep going.

## Dogfooding

This skill should be able to produce the issues this marketplace files about itself — e.g. a `drive_file_get` bug or a "add Slides read support" feature — with no hand-authoring beyond the details the user gives. When you file marketplace feedback and did NOT use this flow, that's a signal the skill or its triggers need improvement (file *that* as friction).
