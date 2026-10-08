# Reviewer pass — fresh context, read-only

Companion to [SKILL.md](SKILL.md) step 2. Read this when dispatching a critique pass.

## Why fresh context is the mechanism

A reviewer that has read the implementation conversation inherits its assumptions and re-derives
its blind spots. On #1492 the findings that mattered — stale empty-state data, whole-document
overflow at 390px, missing live-region semantics — were all *invisible from inside* the work that
introduced them, and all found by a reviewer who arrived knowing only the URL and the issue.

So the reviewer gets: the target URL, the issue text, the viewport matrix, the ship boundary. It
does **not** get the implementer's transcript, its rationale, or its self-assessment.

## Read-only is enforced, not requested

Dispatch the reviewer with no write tools. A reviewer that can edit becomes a second implementer
with nothing checking it, and its findings stop being independent evidence.

```
Agent(
  subagent_type: "rpw-published:reviewer",
  model: "opus",
  description: "UI review pass N",
  prompt: <the block below>
)
```

Model choice follows [`subagent-dispatch/model-selection.md`](../subagent-dispatch/model-selection.md):
critique is judgment a later step cannot recover, so it stays on a frontier model. The implementer's
mechanical follow-through often does not.

## The prompt block

```
You are reviewing a live UI. You have not seen the implementation work and you should not look for it.

Target: <URL>, launched with `<command>`.
Issue: <paste the issue body — requirements and security boundaries verbatim>.
Viewports: <e.g. 1280px, 390px>.
Frozen (do NOT propose changing): <security boundary, dependencies, out-of-scope surfaces>.

Drive the page in a browser per the agent-browser-standards skill: dedicated automation binary,
isolated profile, headless, accessibility snapshot over screenshot. Visit every viewport.

Work the checklists in ui-improvement-cycle/pass-checklists.md. For EACH finding report:
  - what a user sees or cannot do (not what the DOM looks like)
  - the viewport and the exact page state that shows it
  - the requirement or house rule it violates, cited
  - severity: ship-blocker / should-fix / nice-to-have

You are read-only. Do not edit files, run the gate, or open a PR.

Return, as the last lines of your final message, one line per finding in the form
`<severity> | <viewport> | <one-line summary>`. A prose narrative with no finding lines does not
count as a result.
```

## Processing the return

- **An empty final message is not an empty pass.** Read the subagent's transcript and any notes it
  left in the worktree before re-dispatching — on #1492 a reviewer's findings survived only in its
  transcript. Recover them, then decide.
- **No finding lines and no citations = a failed dispatch**, not a clean bill of health. Read-only
  dispatches carry that weaker obligation in place of artifact verification
  ([`subagent-dispatch/return-verification.md`](../subagent-dispatch/return-verification.md)).
- **De-duplicate against earlier passes before dispatching the implementer.** A finding raised in
  pass N-1 and still open is the same finding, not a new one — and if pass N-1 claimed it closed,
  it is an **escape**: record it in the retro.
- **Severity is the reviewer's opinion, not a verdict.** You still decide what blocks the ship,
  against the boundary you pinned before pass 1.
