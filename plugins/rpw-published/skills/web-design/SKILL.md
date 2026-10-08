---
name: web-design
description: Entry point for building or styling any web surface — routes to the canonical design system (libs/ui/DESIGN.md, Stitch convention) and the specialized UI skills. Use when creating or restyling a page or dashboard, picking colors/typography/spacing, or asking where our design preferences live. Trigger on "build a web UI", "style this page", "our design tokens", "match our design system". NOT chart method (dataviz), diagrams, or UI iteration — it routes to those.
---

# Web Design

**One design system, one file, everything else points at it.** All design
*preferences* — tokens, typography, spacing, status colors, accessibility floor,
the generation prompt framework — live in **`libs/ui/DESIGN.md`** (Stitch
`DESIGN.md` convention, #1596). This skill is the router: it tells you to read
that file and which specialized skill owns the method for your task. It restates
nothing; if this file and DESIGN.md ever disagree, DESIGN.md wins.

## The procedure

1. **Read `libs/ui/DESIGN.md`** (repo-relative; in this monorepo, `libs/ui/DESIGN.md`
   from the root). Every styling decision — color, font, radius, spacing, status
   semantics — comes from there. Do not invent values.
2. **Consume tokens as CSS custom properties.** Link or inline `libs/ui/tokens.css`
   and write `hsl(var(--name))`; never paste raw hex/HSL for anything a token
   covers. App-local additions are namespaced (`--hv-*` pattern) and additive only.
3. **Route method questions** to the owning skill (table below).
4. **Generating a new screen?** Use DESIGN.md's 3-layer prompt framework
   (Anatomy / Vibe / Content) — structure and content in the prompt, colors and
   fonts from the tokens, never restated in the prompt.
5. **Before shipping**, check the DESIGN.md accessibility floor (contrast, focus
   ring, 390px viewport) and the favicon gate.

## Routing table

| Task | Skill / asset |
|---|---|
| Any styling parameter (color, type, spacing, status) | `libs/ui/DESIGN.md` — always first |
| Charts, plots, dashboard visualizations | `dataviz` (method; palette parameters from DESIGN.md) |
| Concept / architecture diagram PNGs | `diagram` (its own Brief theme — intentionally not the app design system) |
| Project icon + favicon wiring | `favicon-standards` |
| Iterating a live rendered surface to ship-ready | `ui-improvement-cycle` |
| Recording a demo GIF for a PR | `demo-capture` |
| e2e test placement for a UI | `browser-testing-standards` |
| Driving a browser as an agent | `agent-browser-standards` |
| Customer-facing prose/doc formatting | `doc-styling` (not app UI) |

## Hard rules

- **Never restate DESIGN.md content** in another skill, app doc, or prompt —
  point at it. Duplication is how the suite drifted before #1596.
- **Tokens change in `libs/ui` or nowhere.** `tokens.css` and DESIGN.md's tables
  move in the same commit; the gate test (`tests/test_web_design_standard.py`)
  fails on drift.
- **Zero network requests** for page chrome: system fonts, inline or repo-served
  CSS. Surfaces must render offline.
- Standalone artifacts (outside the monorepo, e.g. a shareable HTML report) may
  inline the token values, but must carry a comment naming
  `libs/ui/DESIGN.md` as the source.
