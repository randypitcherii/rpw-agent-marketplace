# Cloudflare "Code Mode" Pattern Adaptation (rpw-agent-marketplace)

date: 2026-03-08  
status: draft  
review_by: 2026-03-22

## Goal

Adopt a practical version of Cloudflare's "code mode" pattern for this repo:

- Keep the model in an implementation-first posture.
- Use explicit phases so behavior is predictable.
- Require lightweight verification before claiming completion.
- Preserve repo guardrails (no destructive git, no commit/push unless requested).

## Repo-Scoped Adaptation

This repository already has a full-lifecycle `/build` command. The adaptation here adds a narrower, lightweight command:

- `plugins/rpw-building/commands/code-mode.md` (Cursor-safe)
- `plugins/rpw-building/commands/code-mode.claude.md` (Claude-first)

`/code-mode` is intentionally small:

1. **Discover quickly** (files/tests/constraints)
2. **Implement directly** in small increments
3. **Verify with focused commands** (`make verify` when appropriate)
4. **Deliver with evidence** (files changed, commands run, risks)

## Why This Fits This Repo

- Complements `/build` instead of replacing it.
- Useful for bounded, tactical tasks (docs + command + focused code updates).
- Keeps existing marketplace/plugin boundaries intact.
- Reuses existing verification primitives (`make verify`, unittest targets).

## Non-Goals

- No new runtime components.
- No workflow engine changes.
- No changes to plugin boundaries or marketplace manifest structure.

## Risks / Follow-up

- Prompt-only patterns can drift over time if not reviewed.
- Follow-up option: add a validation test that asserts `/code-mode` includes verification and safety sections.
