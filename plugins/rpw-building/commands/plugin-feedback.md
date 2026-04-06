---
name: plugin-feedback
description: Analyze plugin structure — skill coverage, test coverage, component organization, and improvement suggestions
allowed-tools: Agent
user-invocable: true
---

Dispatch the `project-manager` agent with focus on **plugin structure analysis**.

Analyze all plugins under `plugins/`:
- Component inventory (agents, commands, skills, hooks, MCP servers per plugin)
- Test coverage — which components have tests, which don't
- Skill description quality — are triggers specific enough?
- Structural consistency across plugins
- Gaps between documentation and implementation
- Stale or deprecated components

Provide prioritized improvement suggestions.
