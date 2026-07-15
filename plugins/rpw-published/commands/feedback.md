---
name: feedback
description: File well-formed feedback (bug / feature / docs / friction) against the rpw-agent-marketplace — resolves the repo, applies house labels, and drafts the issue in the standard shape.
allowed-tools: Bash, Skill, Read
user-invocable: true
---

# /feedback — file marketplace feedback

Entry point for reporting a bug, feature request, docs gap, or friction against **this marketplace** (its plugins, skills, commands, or MCP servers).

Run the **`marketplace-feedback`** skill and follow its pipeline:

1. **Classify** the report — bug / feature / docs / friction.
2. **Resolve** the target repo (`gh repo view`) and the specific component (plugin + skill/command/MCP server).
3. **Label** — exactly one `type:` (or `documentation`), exactly one `priority:` (default `priority: P2`), and `quick win` when the fix is small + high-value.
4. **Draft** the body in the house shape (Summary → Reproduction → Impact → Likely cause → Suggested fix → Scope → Related).
5. **File** it with `gh issue create` and report the URL + labels applied.

Anything after `/feedback` is the report to file. If it's too thin to produce a good issue, ask one clarifying question, then proceed. For analyzing plugin/project *health* rather than filing feedback, use `/plugin-feedback` or `/project-feedback` instead.
