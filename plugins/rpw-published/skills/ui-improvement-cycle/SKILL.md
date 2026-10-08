---
name: ui-improvement-cycle
description: Take a live UI to ship-ready through repeated reviewer/implementer passes — browser inspection, fresh-context read-only critique, independent red→green implementation, technical review, full-path browser verification, and a compact retro. Use when iterating on a rendered surface rather than building one feature. Trigger on "improve this UI through review cycles", "iterate in the browser", "run reviewer/implementer passes". NOT e2e test architecture or chart design.
---

# UI Improvement Cycle

**The problem: a UI that passes its tests still ships broken, and one review pass does not find it.**
Issue #1492 (the LLM proxy operations dashboard) needed three reviewer→implementer passes plus a
technical review before it was shippable. Across those passes the loop found stale empty-state data,
whole-document horizontal overflow at 390px, missing live-region semantics, an unsafe repair
lifecycle, regressed membership mutations, absent real token telemetry, and missing ranking charts.
**None of those were visible from the diff.** Every one needed a rendered page, and most were found
by the *next* pass rather than the one that introduced them.

That cadence worked, but it lived in a long bespoke prompt with hand-rolled artifact verification.
This skill is that cadence, reusable.

## When to invoke — and when not

**Invoke** when the deliverable is a *rendered surface getting better over passes*: a dashboard, an
operations page, a form-heavy admin view, a UI arriving with a list of complaints rather than one
spec. Two or more of {layout, accessibility, data correctness, charting, mutation safety} in play is
the signal.

**Do not invoke** for a single scoped UI feature (ordinary `tdd` plus a browser check), for
designing a chart (`dataviz`), for deciding which rung an e2e test belongs on
(`browser-testing-standards`), or for recording a demo GIF (`demo-capture`). Those are the
composed parts, and this skill calls them; it does not restate them.

## Inputs — pin these before pass 1

| Input | Why it must be explicit |
|---|---|
| Target URL + how to launch it | A pass that guesses the URL reviews the wrong build. |
| Issue number | Every pass writes `Refs #<n>`; the retro hangs off it. |
| Pass budget (default 3) | Passes are not free; an open-ended loop never converges. |
| Viewport matrix (default 1280px + 390px) | 390px is where whole-document overflow appears. |
| Ship / no-ship boundary | What may change vs. what is frozen (security boundary, deps, scope). |
| Reviewer + implementer models | Distinct contexts, per `subagent-dispatch`. |

## The loop — one pass, five steps

Run steps 1–5 in order, once per pass. Later passes are shorter, never skipped.

1. **Inspect the live page.** Drive the real app in a browser per `agent-browser-standards` —
   dedicated automation binary, isolated profile, headless, accessibility snapshots over
   screenshots. Capture each viewport in the matrix. A pass with no rendered evidence is a
   diff review wearing this skill's name.
2. **Critique from a fresh context, read-only.** Dispatch a reviewer that has *not* seen the
   implementation conversation, with no write tools. Fresh context is the mechanism: a reviewer
   carrying the implementer's reasoning re-derives the same blind spot. Template:
   [reviewer-prompt.md](reviewer-prompt.md).
3. **Implement red→green, independently.** Dispatch an implementer that **reproduces each finding
   before changing code** — a failing test or a captured browser state first, per `tdd`. A finding
   it cannot reproduce goes back to the reviewer as disputed, never silently fixed. Template:
   [implementer-prompt.md](implementer-prompt.md).
4. **Technical review the diff.** Run `/code-review` and `/security-review`, then the
   repo-specific pass in `code-review-and-pr`. This is the step that catches what a
   looks-right page hides: mutation safety, server-side target mapping, telemetry that leaks.
5. **Verify the full path yourself.** Re-run the gate, re-drive the browser at every viewport, and
   check the agent's claims against ground truth per
   [`subagent-dispatch/return-verification.md`](../subagent-dispatch/return-verification.md) —
   claimed files exist and are non-empty, claimed tests actually run, claimed browser states
   actually render. **Only then does the finding count as closed.**

Between passes, apply the checklists in [pass-checklists.md](pass-checklists.md) so a
dimension no reviewer happened to look at does not escape the whole cycle.

## Non-negotiables

- **Human-gated at two points.** Live browser iteration against a real service, and shipping, both
  need the human. The loop prepares evidence and stops; it never merges, publishes, or mutates a
  live system on its own.
- **Reviewers are read-only.** A reviewer that can write becomes an implementer with no independent
  check on it.
- **Verify claims, recover from silence.** A subagent that returns an empty final message has often
  still done the work — read its transcript and its worktree for findings before re-dispatching.
  Verification failure is reported as unverified, never as done.
- **Escaped defects are the cycle's own metric.** A finding that pass N introduced and pass N+1
  found is an *escape*; count them in the retro. Rising escapes mean the checklists are wrong, not
  that the reviewers are good.
- **Never add a required rung-3 browser test without the CI preflight** in
  [ci-preflight.md](ci-preflight.md). A required test whose browser is absent on the runner is a red
  gate for everyone, and a silent skip is worse.
- **One retro, compact.** [retro-template.md](retro-template.md): findings by pass, escapes, gate
  evidence, reusable-process changes. Written to the house standard (`communication`) — a
  screen, not a log.

## Companion files

| File | Read when |
|---|---|
| [reviewer-prompt.md](reviewer-prompt.md) | Dispatching a critique pass |
| [implementer-prompt.md](implementer-prompt.md) | Dispatching a fix pass |
| [pass-checklists.md](pass-checklists.md) | Deciding what each pass must cover |
| [ci-preflight.md](ci-preflight.md) | Before making a browser test required |
| [retro-template.md](retro-template.md) | Closing the cycle |

## Composition — what lives elsewhere

This skill owns the **loop**: pass structure, role separation, verification, and the retro. It owns
none of the domain rules. Design-system conformance (tokens, typography, status colors, the
accessibility floor a reviewer critiques against): `libs/ui/DESIGN.md` via the `web-design` skill.
Browser launch and snapshots: `agent-browser-standards`. Test rungs and
suite hygiene: `browser-testing-standards`. Chart form, palette, and accessible fallbacks:
`dataviz`. Red→green: `tdd`. Dispatch, model choice, return verification: `subagent-dispatch`.
Review dimensions and PR shape: `code-review-and-pr`. Report shape: `communication`. When a rule
here disagrees with its source skill, **the source skill wins** — fix this one.
