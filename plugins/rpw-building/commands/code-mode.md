---
name: code-mode
description: Lightweight implementation-first workflow with explicit safety and verification gates
argument-hint: <request>
---

# /code-mode - Lightweight Code-Mode Workflow

Treat everything after `/code-mode` as the task request.

Use this when work is bounded and implementation can start quickly without a heavyweight planning ceremony. For multi-task orchestration with worktree isolation, use `/build` instead.

## Safety Checks

All must be true for autonomous execution:

1. Scope is local and clear (small number of files).
2. Verification path is obvious (`make verify` or focused tests).
3. No destructive, secret-handling, or production-sensitive actions needed.

If any check fails, ask a focused clarifying question before coding.

## Makefile-First Execution

- Run `make list` to discover available commands.
- Prefer `make verify` for repo-wide invariants.

## Execution Steps

1. **Quick context** — Identify relevant files, commands, docs, tests. Confirm constraints.
2. **Micro-plan** — State 2-5 concrete steps. Call out assumptions explicitly.
3. **Implement** — Prefer minimal, reversible edits aligned with repo conventions. Apply TDD via superpowers skills when fixing bugs.
4. **Verify** — Use the smallest command set that proves the change. Prefer `make verify` for repo-wide invariants.
5. **Deliver** — Report: what changed, files touched, verification commands + outcomes, remaining risks/questions.

## Guardrails

- Never run destructive git commands unless explicitly requested.
- Never commit or push unless explicitly requested.
- If unexpected unrelated changes appear, stop and ask how to proceed.
- Preserve existing local changes outside your task scope.
