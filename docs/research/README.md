# Research

Findings and exploratory work. Use when no agent-root metadata structure exists.

## Freshness Metadata

Each research file should include:

| Field | Required | Description |
|-------|----------|-------------|
| `date` | Yes | When the research was conducted |
| `status` | Yes | `draft`, `reviewed`, `superseded` |
| `review_by` | Optional | Date or milestone for review |
| `superseded_by` | Optional | Link to newer findings when outdated |

## Conventions

- Research findings are **not** binding instructions.
- Durable decisions belong in `docs/decisions/`.
- Instruction memory (AGENTS.md, CLAUDE.md, tool rules) remains separate.

## Linked Research Outside `docs/research`

Use this table for findings that remain in-place elsewhere in the repo.

| Topic | Source | date | status | Notes |
|-------|--------|------|--------|-------|
| Slack MCP via UC connection | `plugins/rpw-working/mcp-servers/slack-via-uc-connection/FINDINGS.md` | 2026-03-03 | draft | Linked in place to avoid moving server-local research notes. |
