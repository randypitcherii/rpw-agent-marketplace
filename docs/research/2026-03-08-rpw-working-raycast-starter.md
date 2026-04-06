# Raycast Starter Proposal: `rpw-working` Tasks

## Context

`rpw-working` is the runtime workflow plugin in this repository. A lightweight Raycast entrypoint can reduce friction for capturing tasks before they are routed into the primary backlog system.

## Starter decision

Implement a minimal, standalone Raycast extension scaffold under:

- `plugins/rpw-working/raycast/rpw-working-tasks`

This keeps ownership with `rpw-working` and avoids introducing cross-plugin drift.

## Included now

1. Extension metadata and build/lint scripts (`package.json`)
2. TypeScript and lint configuration (`tsconfig.json`, `.eslintrc.cjs`)
3. One command (`draft-task`) that copies normalized markdown to clipboard
4. Extension README and parent Raycast README

## Intentionally deferred (low-priority boundaries)

- Direct integration with GitHub/Google Tasks/beads APIs
- Authentication/token management
- CI integration for Node/Raycast assets in top-level quality gates
- Packaging/release automation for Raycast extension distribution

## Why this is practical

- Usable immediately for structured task capture.
- No changes required to existing marketplace manifests or plugin contracts.
- Low blast radius: all assets are isolated under `plugins/rpw-working/raycast`.
