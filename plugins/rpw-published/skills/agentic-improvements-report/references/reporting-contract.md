## Guardrails

- Inspect only the requested time window and sources. State the window, sample size, sources, selection method, omissions, timezone, and limitations.
- Keep collection read-only. Recommendations are proposals, not actions. Do not implement, file, or dispatch them without explicit approval.
- Distinguish counted facts from qualitative coding. Never turn a partial session sample into a population statistic.
- Compare prior cycles only when definitions, windows, and evidence are comparable. Label descriptive evidence and unknowns; do not imply causality.
- Separate observation, interpretation, and recommendation; cite sources close to each claim.
- Recommendations require specific evidence and a concrete action. Weak signals belong in a watch/unknown section.

## Consistent recommendation template

Use an accessible table or cards with these fields, in order:

| Field | Required content |
|---|---|
| Priority | P0/P1/P2/P3 and brief rationale; identify immediate decisions |
| Recommendation | One proposed change, phrased as a verb-led action |
| Evidence | Specific observations, dates/sources, and limitations |
| Impact | High / Medium / Low and outcome expected to improve |
| Confidence | High / Medium / Low based on recurrence and evidence quality |
| Effort | Low / Medium / High; name dependencies/owner if known |
| Verification / next step | A specific success criterion and how/when it can be checked; distinguish proposed verification from verified outcome |
| Approval/status | Proposed / approved / deferred / declined; never imply execution |

Keep priority definitions stable across cycles. Distinguish decisions needed now from future work. Put caveats beside claims rather than burying them.

## Report structure

1. **Prominent identity header** — exact label “Agentic Improvements,” reporting window, and one-sentence bottom line.
2. **Coverage and evidence** — sources, sample, method, unavailable sources, and limits.
3. **Observed usage** — workflows and activity shape; quantities only where counted.
4. **What changed** — comparison with prior cycle(s), explicitly stating “not comparable” or “insufficient baseline” when needed.
5. **Strengths and friction** — representative, cited examples without secrets or unnecessary personal data.
6. **Approval-ready recommendations** — the standard fields above, including a concrete success criterion and verification next step.
7. **Sources and method** — citations, definitions, missing data, and requested self-assessment.

## Comparing and visualizing patterns

Follow the repo `dataviz` skill and `libs/ui/DESIGN.md`. Select the simplest form for the question: paired bars/dots for measured cycle comparisons, tables for qualitative patterns or exact lookup. Each chart needs descriptive title, units, windows, denominators, source, direct labels, explanatory text, contrast, and a non-color-only encoding. Add an equivalent HTML table/text with the same values.

- Carry prior recommendations only when identities/statuses can be verified; otherwise mark “not rechecked.”
- With fewer than three comparable points, call trends preliminary and prefer a table.
- Never interpolate missing cycles, silently mix sampling methods, imply causality, or truncate bar axes to exaggerate. Explain overlapping categories where totals may not sum to 100%.
- Before shipping, render/inspect clipping, overlap, narrow width, 200% zoom, light/dark surfaces, and long labels, as required by dataviz.

## Self-contained HTML and identity

Use `../assets/template.html` as a standalone starting point; `../assets/example-report.html` demonstrates a comparison visualization with an equivalent table, clearly marked fictional. Keep styles inline and require no build/network connection. Use semantic landmarks, logical headings, table captions/headers, responsive layouts, visible focus styles, and readable contrast. Title and visible header must unmistakably say **Agentic Improvements**, not look like a generic dashboard.

For standalone HTML, inline token values are permitted only with a comment naming `libs/ui/DESIGN.md` as their source. Prefer design-system tokens; don't invent new design parameters.

Favicon assets must belong to this project and follow `favicon-standards` source → registry → build conventions. Never point at another project's icon. A registered web surface uses standard favicon tags and registry-matched theme color. A local report without server-owned icon paths should use a correct inline, project-specific data URI favicon or omit the favicon until a project source asset exists. Never invent an external `favicon.svg` path for raster art.

## Cycle continuity

For each claimed change, record prior/current values and windows, comparability (yes/partial/no), and evidence. Carry unresolved recommendations only when revalidated; otherwise mark “not rechecked.” Statuses such as implemented/effective, implemented/unverified, declined, deferred, or unresolved require evidence. This human-facing report does not define durable storage or collection automation (see issue #1599).
