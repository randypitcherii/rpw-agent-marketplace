# Implementer pass — reproduce first, then red→green

Companion to [SKILL.md](SKILL.md) step 3. Read this when dispatching a fix pass.

## The rule that makes the pass worth anything

**The implementer reproduces every finding before it changes a line.** A failing test, or a captured
browser state at the named viewport — something that is red now and green after.

Without it a pass degrades into "the reviewer said so, so I edited something": #1492 saw a
membership mutation regress and real token telemetry go missing, both under changes that looked
plausible and had nothing proving them. Reproduction is also the cheapest filter on wrong findings —
a reviewer who misread the page produces a finding that will not reproduce.

**A finding that will not reproduce goes back as disputed.** Not silently fixed, not quietly
dropped. Say which finding, what you tried, and what the page actually did.

## Dispatch

```
Agent(
  subagent_type: "rpw-published:build-worker",
  model: "sonnet",
  description: "UI fix pass N",
  prompt: <the block below>
)
```

## The prompt block

```
Fix the findings below in <worktree path>, on branch <branch>.

Findings (from an independent read-only review of the live page):
<one block per finding: summary, viewport, page state, cited requirement, severity>

Frozen (do NOT change): <security boundary, dependencies, out-of-scope files>.
Files you own: <explicit list>.

For EACH finding, in this order:
  1. Reproduce it. Write the failing test, or drive the page and capture the broken state.
     Put the test at the LOWEST rung that can hold it (browser-testing-standards): a pure
     unit test, then a node DOM harness, then headless Chrome. Do not reach for rung 3 for
     something a DOM harness proves.
  2. Fix it, with the reproduction going red -> green.
  3. Re-drive the page at the finding's viewport and confirm the user-visible behavior changed.

If a finding does NOT reproduce, do not change code for it. Report it as disputed with what you
observed.

Chart work follows the dataviz skill (form, palette, accessible table equivalent). Test structure
follows browser-testing-standards. Red->green follows tdd.

Commit locally with `Refs #<issue>` before running the gate. Then run `make check` in the
foreground and poll it to completion.

Return, as the last lines of your final message:
  - the commit sha
  - one line per finding: `<finding> | fixed | <test path>` or `<finding> | disputed | <what you saw>`
```

## Verify before you believe it (step 5)

Every claim the implementer makes gets checked against ground truth, per
[`subagent-dispatch/return-verification.md`](../subagent-dispatch/return-verification.md):

| Claim | Check |
|---|---|
| "commit landed" | `git -C <abs-worktree> log --oneline <base>..<branch> -- <owned paths>` **and** `git -C <abs-worktree> status --porcelain` empty |
| "added test X" | `test -s <abs-path>` — then run it and watch it pass |
| "test proves the finding" | revert the fix locally, confirm the test goes red, restore |
| "page renders correctly now" | drive it yourself, at that viewport |
| "gate is green" | your own `make check`, not a quoted summary |

Two failed verifications on the same finding is the stopping point
(`subagent-dispatch`): stop re-dispatching, and either fix it inline or park it and say so.
