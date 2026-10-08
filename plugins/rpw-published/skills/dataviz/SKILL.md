---
name: dataviz
description: Use before creating any chart, graph, plot, dashboard, or data visualization in any medium — HTML/React artifacts, inline SVG, plotting code (matplotlib, plotly, d3, Recharts), or rendered PNGs. Read it before writing chart code or choosing chart colors. Provides a form heuristic, a runnable palette validator, mark and interaction rules, and accessibility checks. For concept or architecture diagrams, use the diagram skill instead.
---

# Data visualization

Build the chart around the reader's question. Choose color only after the data,
comparison, and geometry are clear.

## Route the request

- Values, series, distributions, or trends → use this skill.
- Concepts, components, or relationships → use `diagram`.
- A request for both needs two artifacts; do not combine a concept map and a data
  plot into one graphic.

## Procedure

1. **State the comparison.** Write the sentence the chart must make obvious. Remove
   fields that do not support it.
2. **Choose a form.** Use position on a common scale when possible. Use a table or
   headline number when a plot adds no information. See `reference.md`.
3. **Specify encodings.** Record which field controls x, y, color, size, shape, and
   facet. Never use two y-axes.
4. **Choose color by role.** Identity uses a fixed categorical order; magnitude uses
   one light-to-dark hue; polarity uses two hues around a neutral midpoint; status
   colors are reserved for state.
5. **Validate color.** Run
   `node scripts/validate_palette.js "#hex,#hex,..." --surface "#hex"`. Fix every
   failure. Color must never be the only carrier of identity or status.
6. **Add labels and interaction.** Label units and important values. Interactive
   plots need keyboard-reachable marks and a tooltip or direct-detail view.
7. **Add an equivalent table.** Keep the underlying values available to readers and
   assistive technology.
8. **Render and inspect.** Check clipping, overlap, small screens, light and dark
   surfaces, empty data, and unusually long labels.

## Non-negotiable checks

- One quantitative scale per axis; no dual-axis chart.
- Start bars at zero. If a non-zero line-chart baseline is necessary, show it clearly.
- Keep entity colors stable when filtering or sorting.
- Use direct labels for four or fewer series; use a legend for larger sets.
- Do not put a number on every point when selective labels communicate the pattern.
- Do not use a pie or donut when precise comparison matters or there are more than
  five slices.
- Do not use 3-D perspective for ordinary analytical charts.
- Test the final rendered artifact, not only the source code.

## Design-system integration

The method is portable; tokens are inputs. In this repository, take chart colors,
surfaces, text, spacing, and status roles from `libs/ui/DESIGN.md`. Elsewhere, use the
consumer's design system. Do not copy this repository's palette into another brand.

## Files

- `reference.md` — form selection, encoding, interaction, and accessibility details.
- `scripts/validate_palette.js` — dependency-free contrast and perceptual-separation
  gate for categorical colors.

## Provenance

This is an independently written replacement for a previously reproduced Claude Code
bundled skill. The public Anthropic skill marketplace does not offer that bundled
`dataviz` definition as an installable plugin, so a cross-marketplace dependency cannot
supply it to a clean install. The repository-wide classification and dependency decision
are recorded in `../PROVENANCE.md`.
