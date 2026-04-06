# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.
Required plugin stack: see `docs/process/required-plugin-stack.md`.

**Dolt backend:** When the Dolt server runs on a non-default port, `bd doctor` needs the port. Use:
`BEADS_DOLT_SERVER_PORT=$(cat .beads/dolt-server.port 2>/dev/null) bd doctor`

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Architecture Docs

- Plugin boundaries: `docs/architecture/plugin-boundaries.md`
- Plugin scope definitions: `CLAUDE.md`

## Landing the Plane (Session Completion)

When ending a work session, complete these steps:

1. **File issues** for remaining work
2. **Run quality gates** if code changed (`make verify`)
3. **Update issue status** — close finished work, update in-progress items
4. **Push to remote** only if a remote is configured; otherwise work is complete once committed locally
5. **Hand off** — provide context for next session

**HARD RULE:** Do not add a git remote or push unless the user explicitly asks in the current session.
