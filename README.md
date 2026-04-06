# rpw-agent-marketplace

Marketplace repository for Randy's Claude Code plugins.

## Layout

- `.claude-plugin/marketplace.json` — marketplace manifest
- `plugins/rpw-building` — dev/tooling plugin (commands, skills)
- `plugins/rpw-working` — working plugin (skills, MCP config, mcp-servers/)
- `plugins/rpw-databricks` — Databricks-specific work activity plugin (commands, skills)
- `plugins/rpw-working/raycast` — starter Raycast assets for task capture workflows
- Manifests at `.claude-plugin/plugin.json` per plugin; skills, commands, MCP colocated in each plugin

## Getting Started

After installing, run `/doctor` (or `/getting-started` or `/start-here`) to validate your environment. It checks required tools, plugin versions, and MCP server configuration.

## Updating

Re-run the install command to pull the latest plugin versions:

```bash
claude plugin marketplace add rpw-agent-marketplace
```

The `/doctor` command includes a plugin freshness check that warns when installed versions are behind the marketplace.

## Architecture

- Plugin boundary contract: `docs/architecture/plugin-boundaries.md`
- Context-mode activity pattern (HN/GitHub style): `docs/process/context-mode-activity-pattern.md`
- Required dependency onboarding policy: `docs/process/required-plugin-stack.md`

## Validate

```bash
make verify
```

Prerequisite: install [`uv`](https://docs.astral.sh/uv/) so `make verify` can run `uv run ...`.

## Environment Preferences Pattern

For local runtime configuration, prefer environment-specific files:

- Commit `template.env` to document required variables and structure.
- Keep `dev.env`, `test.env`, and `prod.env` local-only (ignored by git).
- Select runtime env with `APP_ENV=dev|test|prod` (default: `dev`).

This pattern is implemented in MCP server startup wrappers (`run_mcp.py`) under `plugins/rpw-working/mcp-servers/`.

## Public publishing

Publish a filtered copy of this repo to a public GitHub repo:

```bash
make publish-setup      # First-time: create public repo + clone locally
make publish-dry-run    # Preview what would be published
make publish-public     # Publish (scan, filter, sync, push)
```

Exclusions are configured in `.public-publish.yml` (rpw-databricks, .beads, .env files, hooks, local settings). The publish script runs secret scanning on both source and output.

### Guardrails

- `make public-release-scan` checks for blocked file paths and secret patterns.
- `make marketplace-release` includes a confirmation gate via `make public-release-gate`.
- To run a marketplace release, set: `PUBLIC_REPO_RELEASE_CONFIRM=I_ACKNOWLEDGE_PUBLIC_REPO_RELEASE`

## Required Plugin Onboarding

This repo uses a single required plugin stack for onboarding (no personas/profiles):

- `superpowers`, `beads`, `code-context`, `context-mode`
- `rpw-building`, `rpw-working`, `rpw-databricks`

Run:

```bash
uv run python scripts/enable_required_stack.py
```

This writes to `.claude/settings.local.json` by default.

## Versioning

- Scheme: calendar-first `YYYY.MM.DDNN` (`NN` is zero-padded intra-day sequence).
- Source of truth for plugin versions: `.claude-plugin/marketplace.json`.
- Plugin-local manifests (`plugins/*/.claude-plugin/plugin.json`) must define a `version` field matching their marketplace.json entry.
- Production release bumps are handled by `scripts/bump_marketplace_versions.py` (see `make version-bump` and `make production-merge-helper`).
- Policy and rationale are defined in `docs/decisions/ADR-001-calendar-first-versioning.md`.
