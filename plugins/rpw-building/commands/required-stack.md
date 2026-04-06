# /required-stack - Enforce the Required Plugin Stack

Enable the single required plugin stack for this marketplace with no profiles and no customization flow.

Treat everything typed after `/required-stack` as optional context; the command behavior is fixed.

## Policy

- This repository supports one onboarding mode only: required stack.
- Do not offer persona-based variants, optional bundles, or profile selection.
- Prioritize reliability and repeatability for new users over flexibility.

## Required Plugins

The required plugin stack is:

- `superpowers`
- `beads`
- `code-context`
- `context-mode`
- `rpw-building`
- `rpw-working`
- `rpw-databricks`

## Execution Steps

1. Inspect current status:
   - Run `git status --short` and preserve unrelated local changes.
2. Apply required stack locally:
   - Run `uv run python scripts/enable_required_stack.py`.
3. Verify resulting local settings:
   - Run `uv run python scripts/enable_required_stack.py --dry-run`.
4. Confirm expected plugin keys are set to `true` under `enabledPlugins`.

## Scope and Safety

- This command writes to `.claude/settings.local.json` by default (local/transient for this repo).
- Do not modify global settings unless the user explicitly requests it.
- Do not remove existing enabled plugins; only ensure required plugins are enabled.
