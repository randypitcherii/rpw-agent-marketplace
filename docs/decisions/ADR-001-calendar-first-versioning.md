# ADR-001: Calendar-first versioning source and release cadence

**Status:** Accepted
**Date:** 2026-03-07

## Context

This repository packages multiple plugins through a single marketplace file. Versions were previously duplicated across individual plugin manifests and marketplace metadata, which creates drift risk and unclear release ownership.

Production releases also need deterministic bump timing and merge behavior so version history is auditable and easy to reason about.

## Decision

- Use calendar-first version format `YYYY.MM.DDNN`.
  - `YYYY.MM.DD` is the production release date.
  - `NN` is a zero-padded intra-day sequence (`01`, `02`, ...).
- Treat `.claude-plugin/marketplace.json` as the single source of truth for plugin versions.
- Do not define `version` in plugin-local manifests (`plugins/*/.claude-plugin/plugin.json`).
- Bump versions only when changes are merged to production.
- Allow only squash merges into production to keep one release-intent commit per change set.

## Consequences

- Version ownership is centralized and easier to validate in CI.
- Plugin manifests become simpler and cannot silently diverge from marketplace versioning.
- Release operators must bump versions during production merge preparation, not during feature branch development.
- Production history remains linear and easier to map to release log entries.
