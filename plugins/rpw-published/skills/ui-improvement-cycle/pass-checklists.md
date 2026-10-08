# Pass checklists — the dimensions a reviewer forgets

Companion to [SKILL.md](SKILL.md) step 2. These are **pointers with a trigger**, not a second copy
of the source skills. Each row names what to look for and where the rule actually lives.

Every dimension is checked every pass. A dimension nobody looked at is how a defect escapes the
whole cycle, and an escaped defect costs a pass.

## Layout and responsiveness

| Look for | Rule lives in |
|---|---|
| Whole-**document** horizontal scroll at the narrow viewport — the #1492 finding a wide desktop never shows | the issue's own viewport requirement |
| Wide content (tables, charts) overflowing the document instead of scrolling inside its wrapper | same |
| Content that only reflows because the window is wide enough to hide the bug | same |

Check the narrow viewport first. It is where the finding is.

## Accessibility

| Look for | Rule lives in |
|---|---|
| Status that changes without a live region announcing it (#1492's missing live-region semantics) | `dataviz` (interaction/accessibility rules) |
| Color as the only signal for state — pair it with text or a glyph | `dataviz` |
| Values readable only by hovering a chart — every chart needs a keyboard-readable table equivalent | `dataviz` |
| Focus lost or trapped after a mutation, dialog, or re-render | `agent-browser-standards` (snapshots expose focus) |

Take an accessibility snapshot, not a screenshot. A screenshot cannot show you a missing role.

## Data correctness

| Look for | Rule lives in |
|---|---|
| Empty states rendering stale or invented data instead of "no data" | the issue's requirements |
| Rollups computed from a truncated recent slice rather than the whole selected window | same |
| Telemetry the page claims to show that is not actually recorded (#1492's absent token counts) | same |
| Human-facing numbers without locale separators or unit context | same |

Read the query, not the rendered number. A plausible number is the hard case.

## Charts

Route through `dataviz` before writing chart code: form heuristic, palette validator, mark specs,
accessible fallback. Two cycle-specific additions:

- **Assets are local.** No CDN, no off-host fetch — a vendored library is committed and served.
- **A ranking view is a chart too.** "Slowest N", "largest N" were missing from #1492 pass 1 and
  found in pass 2; if the issue asks *which are worst*, a bare total does not answer it.

## Mutation and security boundaries

| Look for | Rule lives in |
|---|---|
| A mutation reachable without the page's existing host/origin guard | `code-review-and-pr`, plus `/security-review` |
| Any command, argv, or path accepted from the browser — map targets server-side | same |
| A destructive or repair action with no explicit confirmation, or with an unsafe lifecycle (#1492) | the issue's security boundaries |
| A mutation that regressed while a nearby feature was added — cover it with a test | `tdd` |

This block is the one a rendered page cannot verify for you. It is a diff review.

## Gate and evidence

| Look for | Rule lives in |
|---|---|
| The new test in the default gate command, or beside it | `browser-testing-standards` |
| Fixed sleeps, hardcoded ports, live network calls in the new test | same |
| A missing browser skipping silently instead of failing under CI | [ci-preflight.md](ci-preflight.md) |
| Tests asserting user-visible behavior rather than the current DOM's incidental shape | same |
