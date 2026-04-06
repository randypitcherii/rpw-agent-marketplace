# Raycast Starter for `rpw-working` Tasks

This directory contains a practical starter Raycast extension for lightweight task drafting tied to the `rpw-working` plugin's workflow focus.

## Why this exists

- `rpw-working` owns run-time execution workflows (day-to-day work tasks).
- Raycast is a fast entry point for capturing tasks before they are synced into the broader `work-backlog` process.
- This is intentionally low-priority starter scope, not a production-complete integration.

## Current starter scope

- A standalone Raycast extension scaffold at `./rpw-working-tasks`.
- One command (`draft-task`) that:
  - collects title, context, priority, and due date,
  - renders a normalized markdown task block,
  - copies it to clipboard for quick paste into the user's system of record.

## Local usage

1. `cd plugins/rpw-working/raycast/rpw-working-tasks`
2. `npm install`
3. `npm run lint`
4. Import the extension folder into Raycast (Developer > Import Extension).

## TODO boundaries (explicitly out of this bead)

### TODO: real task-system integration

- Add adapters for target systems (GitHub Issues, Google Tasks MCP, or beads/bd CLI).
- Add authenticated write-paths (create/update tasks directly).

### TODO: repository-level CI for Raycast assets

- Decide whether to add Node-based checks into top-level `make verify`.
- If adopted, add deterministic lockfile policy and Node version policy.

### TODO: UX hardening

- Add command history/templates, validation, and richer priority taxonomy.
- Add error telemetry/logging strategy.

### TODO: release strategy

- Decide whether this should remain a source-only asset or become a separately versioned extension package.

