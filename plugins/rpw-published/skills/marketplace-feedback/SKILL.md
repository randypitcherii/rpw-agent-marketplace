---
name: marketplace-feedback
description: Use when filing a bug, feature request, docs gap, or friction report AGAINST the rpw-agent-marketplace itself — its plugins, skills, commands, or MCP servers (not the user's own projects). Trigger on "file a bug about this plugin / the marketplace", "report feedback on rpw", "this MCP tool is broken", or the /feedback command. Resolves the target repo, classifies the report, applies house labels, and drafts the issue in the standard body shape.
---

# Marketplace Feedback

Turn "this marketplace thing is broken / missing / annoying" into a **well-formed GitHub issue** — correct repo, house labels, consistent body — in one guided step. This is the standard reporting path for feedback about the marketplace and its components. Full label taxonomy, per-type body shapes, and the issue-template mapping: [reference.md](reference.md).

## When to invoke

Use when the target of the feedback is **this marketplace** — a plugin, skill, command, hook, or MCP server under `plugins/`, or the build/runtime tooling. Triggers: "file a bug about this plugin", "report feedback on rpw", "this MCP tool returns X", "we should add Y to the marketplace", "the /build skill misfires on Z", or the `/feedback` command.

**Skip when** the feedback is about the *user's own* project (file it there with `gh` directly), or the fix is fast enough to just do inline. For analyzing plugin/project *health* (not filing feedback), use `/plugin-feedback` or `/project-feedback` instead.

## Pipeline

### 1. Classify
Pick exactly one type from what the user describes:
- **bug** — something is broken or behaves wrong (`type: bug`).
- **feature** — new capability or enhancement (`type: feature`).
- **docs** — missing/wrong/unclear documentation (`documentation`).
- **friction** — the tool works but the workflow is painful, slow, or surprising. Friction is usually filed as a `type: bug` (behavior to fix) or `type: feature` (ergonomics to add) — decide which the fix is, and say "friction:" in the summary.

If it's ambiguous, ask ONE clarifying question, then proceed.

### 2. Resolve the target repo + component
- Default repo = this marketplace repo: `gh repo view --json nameWithOwner -q .nameWithOwner`.
- Identify the **component** the feedback is about — the plugin + the specific skill/command/MCP server (e.g. `rpw-published / google-drive MCP`, `rpw-published / build command`). Name it in the body so triage is instant.

### 3. Pick labels
Apply, from the real repo label set (see [reference.md](reference.md) for the full table + colors):
- **exactly one type**: `type: bug` | `type: feature` | `type: epic` | `type: task`, or `documentation` for pure docs.
- **exactly one priority**: `priority: P0`…`priority: P4` (P0 critical → P4 backlog). Default `priority: P2` unless the user signals urgency.
- **`quick win`** when the fix is small, well-scoped, and high-value (low effort, clear payoff) — e.g. a one-file bug with an obvious fix.
Do NOT invent labels; use only what `gh label list` returns.

### 4. Draft the body (house shape)
Every issue uses the same sections so they read consistently (drop sections that don't apply, but keep the order):

- **Summary** — one paragraph: what's wrong / wanted.
- **Reproduction** (bugs) — exact steps / command + observed vs expected.
- **Impact** — who/what is blocked, how often, the workaround if any.
- **Likely cause** (if known) — file:line or subsystem.
- **Suggested fix / desired shape** — concrete, minimal.
- **Scope** — how contained (single file? one MCP server? note `quick win`).
- **Related** — `#N` issues/PRs.

Per-type ready-made skeletons are in [reference.md](reference.md); the `.github/ISSUE_TEMPLATE/` files carry the same shape for manual filers.

### 5. File it
Use a HEREDOC so the markdown stays clean:

```bash
gh issue create \
  --title "<component>: <concise summary>" \
  --label "type: bug" --label "priority: P2" \
  --body "$(cat <<'EOF'
## Summary
...
## Reproduction
...
## Impact
...
## Suggested fix
...
## Scope
...
## Related
- #N
EOF
)"
```

Title convention: `<component>: <summary>` (e.g. `google-drive MCP: drive_file_get rejects valid fields`). Capture the returned issue number and report it back.

### 6. Confirm + report
Echo the issue URL, the type/priority/quick-win labels applied, and the component. If the user was mid-task, offer to keep going.

## Dogfooding

This skill should be able to produce the issues this marketplace files about itself — e.g. a `drive_file_get` bug or a "add Slides read support" feature — with no hand-authoring beyond the details the user gives. When you file marketplace feedback and did NOT use this flow, that's a signal the skill or its triggers need improvement (file *that* as friction).
