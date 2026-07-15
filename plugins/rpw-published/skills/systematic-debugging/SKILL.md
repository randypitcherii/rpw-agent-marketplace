---
name: systematic-debugging
description: Use when debugging a failure, diagnosing a bug, or when the user says "debug this", "why is X failing", "this is broken", "it errors", or reports something not working. Hypothesis-driven loop whose hard rule is to reproduce the failure locally BEFORE asking the user to retest. Pairs with tdd for locking the fix in with a regression test.
---

# Systematic Debugging (house version)

Distilled house debugging method. Harness-neutral. For deeper technique and worked repros, read `reference.md` in this skill directory.

**The hard rule: reproduce the failure locally before asking the user to retest.** "Push a fix, ask the user to try in the UI, get a new error, push another fix" is the worst loop. Most bugs are reproducible from a shell in seconds in your own context — do that first.

## The loop

1. **Reproduce** — Get the failure to happen on demand, locally, in the smallest invocation that still fails. This is step one, not step three.
2. **Hypothesize** — From the actual error/logs, form ONE specific, falsifiable guess about the cause.
3. **Test the hypothesis** — Change one thing, re-run the repro, observe. Confirm or kill the guess.
4. **Fix** — Apply the minimal change. Re-run the repro: failure gone.
5. **Lock it in** — Add a regression test (use the `tdd` skill) so this exact failure turns red if it returns.

If a hypothesis-driven fix doesn't work the first time, **reproduce the new failure locally** before pinging the user again. Vary the input, strip the env, read the logs — don't ping-pong.

## Reproduce-locally toolkit

- **Direct invocation** — call the failing CLI/function/endpoint yourself from the shell. The user-facing tool (Raycast, a browser, a UI) is rarely needed to reproduce.
- **Stripped-env repro** — when "works for me, not for them" smells like environment, reproduce under a minimal env:
  ```bash
  env -i PATH=/usr/bin:/bin <command>
  ```
  If it fails clean here, the bug is a missing/assumed env var, not the code.
- **Read the subprocess logs** — the user-facing tool almost always captured stdout/stderr/exit code of the thing that failed. Read that before guessing.
- **Bisect by layer** — walk the path: direct call → stripped env → full user path. The layer where the failure first appears is where the bug lives.

## When you genuinely need the user's environment

Only escalate to a user-retest when the bug truly needs their context: live UI rendering, an interactive auth/SSO browser step, a workspace action a classifier blocks on your side. Ask once for explicit go-ahead, then proceed — don't ping-pong.

## MCP-change gotcha (#173)

A **connected MCP server runs the INSTALLED plugin code, not your worktree edits.** Calling the live tool to "test your fix" exercises the *old* code and validates nothing. To reproduce/validate an unmerged MCP change, run `claude --plugin-dir <worktree>` or run the worktree server directly with its env/auth — otherwise mark live validation deferred-to-post-merge and rely on unit-test evidence.

→ Worked repros, bisection examples, and the "read before guess" discipline: `reference.md`.
