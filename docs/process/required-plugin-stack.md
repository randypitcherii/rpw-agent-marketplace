# Required Plugin Stack

This repository uses a single onboarding model for plugin dependencies.

## Decision

- Use one required stack for all users.
- Do not provide profile selection or persona-specific dependency bundles.
- Optimize for reliable, predictable setup with minimal decision overhead.

## Required Plugins

- `superpowers`
- `beads`
- `code-context`
- `context-mode`
- `rpw-building`
- `rpw-working`
- `rpw-databricks`

## Onboarding Command

- Run `/required-stack` in Cursor/Claude command mode, or:
- Run `uv run python scripts/enable_required_stack.py`

Default target is `.claude/settings.local.json` so the setup is local to the repository.

## Guardrails

- No customization flow in the command itself.
- No optional plugin bundles.
- No global settings mutation unless explicitly requested by the user.
