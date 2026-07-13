# Systematic debugging — reference

Deeper material for the `systematic-debugging` skill. Read this when the lean SKILL.md isn't enough.

## Why local-repro-first is the whole game

The expensive loop is: push a fix → ask the user to retest in their UI → they hit a new error → you push another fix → repeat. Each cycle costs minutes of the user's time and a context switch. The cheap loop is: reproduce the failure in your own shell → diagnose → fix → confirm against the repro → hand back something that actually works. The diagnosis usually takes seconds once you can trigger the failure on demand.

So the first move after a bug report is **never** "try this fix and tell me if it works." It's "make the failure happen here." If you can't reproduce it, you don't understand it yet — and a fix you can't see fail-then-pass is a guess.

## Forming a falsifiable hypothesis

A good hypothesis names a specific cause and predicts what you'd see if it were true: "the subprocess inherits an empty PATH, so the `git` lookup fails — if so, the stripped-env repro will fail with command-not-found and passing PATH explicitly will fix it." That's testable in one run. "Something's wrong with the environment" is not a hypothesis; it's a shrug. One falsifiable guess at a time — changing several things at once destroys the signal.

## Bisect by layer — worked shape

When a failure only shows up through the full user path, walk inward until it disappears, then the boundary is your bug:

1. Call the core function/CLI directly with the same input. Fails? Bug is in the core — stop here.
2. Still passes? Run it under the stripped env (`env -i PATH=/usr/bin:/bin ...`). Fails now? Bug is an assumed env var.
3. Still passes? Run the next layer out (the wrapper, the proxy, the router). Keep going until the failure appears. The first layer that fails owns the bug.

## Read the logs before guessing

The user-facing tool almost always captured the failed subprocess's stdout, stderr, and exit code somewhere — a log file, a captured-output panel, a debug pane. Reading that turns "why is it broken" into "here is the exact traceback." Guessing before reading the captured output is how you burn cycles on the wrong hypothesis.

## Stripped-env repro — when and how

Reach for `env -i PATH=/usr/bin:/bin <command>` when the symptom is environment-shaped: works in your interactive shell but fails when launched by another process, by a scheduler, by a GUI app, or on another machine. The minimal env strips away your shell's accumulated exports so any reliance on an unset/assumed variable surfaces immediately. Add back variables one at a time to find the one that matters.

## The auto-mode classifier first-call block

On this setup the auto-mode safety classifier may block a "production read" call on the first attempt. Don't treat that as a dead end and don't ping-pong: ask once for explicit go-ahead ("can I hit your workspace to debug X?"), then proceed. Subagent Bash permission denials are similarly transient — a retry next session often clears them.

## MCP changes run installed code, not your worktree (#173)

The single most common false-validation in this repo: you edit an MCP server's code in a worktree, then call the live connected tool to "confirm the fix." The connected server is running the *installed* plugin build, not your edits — so you just tested the old code. Two honest options:

- Run `claude --plugin-dir <worktree>` so the harness loads the worktree code, then exercise the tool.
- Run the worktree server process directly with its env/auth configured and hit it.

If neither is feasible, record live validation as **deferred-to-post-merge** and proceed on unit-test evidence. Never report the live tool as having validated an unmerged MCP change.

## Hand back to the user only when their environment is truly required

Legitimate user-retest cases: visual/UX rendering that needs human eyes, an interactive browser SSO/OAuth step, a live workspace action that a classifier blocks on the agent side. Everything else, reproduce yourself. When you do need them, batch the ask — give them one clear thing to check, not a stream of "try this… now this…".
