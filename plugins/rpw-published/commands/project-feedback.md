---
name: project-feedback
description: Analyze project health — open/blocked/stale issues, dependencies, velocity, and recommendations
allowed-tools: Agent
user-invocable: true
---

Dispatch the `project-manager` agent with focus on **project health analysis**.

Analyze:
- Issue counts by status (open, in-progress, blocked, closed)
- Blocked issues and what's blocking them
- Stale issues with no updates in 7+ days
- Dependency graph health
- Ready-to-work queue
- Recent velocity (issues closed in last 7 days)

Provide actionable recommendations for what to work on next.
