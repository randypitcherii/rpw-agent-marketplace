---
name: diagram
description: Create a concept or architecture diagram as a styled PNG — a self-contained HTML file (CSS grid, inline SVG) screenshotted by headless Chrome at 2×, its only dependency. Trigger on "make a diagram of X", "draw the architecture of Y", "visualize how Z works", "explain W visually", or when a multi-noun concept reads better as a picture. House Brief theme — a one-slide briefing with title, kicker-labelled sections, and cards. For charts or dashboards, use dataviz.
---

# Diagram Skill

Produce a visual explanation of a concept as a styled PNG. You author one **self-contained
HTML file** — CSS grid for layout, inline SVG for connectors — and headless Chrome
screenshots it at 2× for crisp text. PNG is the user-facing artifact because it pastes
reliably into Slack, docs, decks, and notebooks.

HTML replaced D2 on 2026-08-12 (#966). The **Brief** theme replaced Mono Bold on
2026-09-03 (#1034): a diagram is a one-slide briefing a non-technical reader follows
without anyone explaining it, not a bare box-and-arrow map.

## When to invoke, and routing

"visualize <concept>" · "make a diagram of <X>" · "explain <Y> visually" · "show me how
<X> works" — and **proactively** when explaining ≥4 entities and their relationships.

This skill draws **structure**: nouns, zones, steps, labeled edges. Anything driven by rows
of data → `dataviz`. A combined request → two artifacts, never one hybrid image.

This skill produces a **static Brief PNG**. When engineers need to search nodes, trace
routes, open source references, or compare architecture revisions, use
[Archify](interactive-maps.md) instead. “Architecture” alone does not trigger that route;
the artifact must need interaction.

## The hard part is editorial

Rendering is mechanical; choosing what to draw is the skill. Before authoring:

1. **Name the reader's first question.** "Where does my data go?" · "What do I actually
   do?" · "What leaves my walls?" · "How big is this?" The answer picks the framing and
   becomes the **title**.
2. **Write the title and subtitle first.** Title: the answer, one line ("Six steps from
   your table to Acme"). Subtitle: one sentence saying which line of the picture to
   follow. If you cannot write these, you do not yet know what the diagram is for.
3. **Pick the core nouns.** 5–9 cards or nodes. Cut ruthlessly; 25 nodes is a failure of
   choice.
4. **Every card gets a headline and 2–3 plain-weight facts.** Bold headline, weight-400
   bullets, one fact each — so the eye can skim headlines alone and still get the story.
5. **Pick the one moment a human acts.** That card is yellow (`.gate`) — the anchor. Most
   diagrams have one; never more than two.
6. **Colour the other party blue** (`.brand`) — the vendor, the public mirror, the
   endpoint across the wire. One blue zone.
7. **Everything else stays white.** Three fills is the whole palette. Wanting a fourth
   means fewer nouns.
8. **Group under kickers** — a 4px rule + small-caps label whose colour says whose turn
   it is before the reader reads a word.
9. **Say the return path in prose.** Back-edges are the biggest single cause of unreadable
   diagrams. "Workers report back" belongs in the subtitle, not in an arc.

### Four framings, one skin

Same facts, different first impression. Pick by the reader's question; copy the example.

| Framing | Reader's first question | Shape | Start from |
|---|---|---|---|
| **Stepper** (default) | "What do I actually do?" | Numbered cards in a row, phase kickers above, a **state footer** on every card (`NOTHING SENT` → `SENT`), an always-on band below | `examples/release-stepper.html` |
| **Journey** | "Where does my data go?" | Three zones left→right (yours · the middle · theirs), each a `.group` of nodes | `examples/mlflow-journey.html` |
| **Boundary** | "What leaves my walls?" | Two zones split by a dashed blue rule; exactly one arrow crosses; a dashed "what never crosses" card | the journey example + the boundary recipe |
| **By the numbers** | "How big is this?" | A row of `.big` numeral tiles, a batch strip, an always-on band | `template.html` — `.big` is in the style block |

**Direction:** rows flow left-to-right; the canvas stacks rows. Keep width ≤ 1600 CSS px.
The slide proportion (`--canvas-h:600px`) is a *minimum*, never a clip — set
`--canvas-h:0` on `<body>` to hug content. A chain deeper than ~6 steps is a strip either
way: collapse the middle into fewer nouns first.

## Workflow

1. **Copy `template.html`** to `/tmp/diagram-<slug>.html`. Replace the `<body>`; leave
   the `<style>` block alone.
2. **Author the body.** Primitives, connector geometry, framing recipes:
   `layout-recipes.md`. Self-contained — system fonts, inline CSS, inline SVG, **zero
   network requests**.
3. **Render:** `./render.sh /tmp/diagram-<slug>.html /tmp/diagram-<slug>.png`. Two Chrome
   passes: measure the page, then screenshot a window of exactly that size at 2×. It
   prints CSS and pixel sizes — confirm 2×. A hand-guessed `--window-size` clips or pads.

   Env overrides (full list in `render.sh`'s header): `CHROME_PATH` — explicit binary;
   `RPW_SCALE` — scale factor (default 2); `RPW_DIAGRAM_UNSAFE_NO_SANDBOX=1` — **unsafe**,
   opts into `--no-sandbox`, Chrome's containment boundary against a renderer bug. Only for
   root-in-a-container, where Chrome refuses to start otherwise — a "could not measure"
   failure whose stderr mentions "sandbox". Never a default fix for an unrelated failure;
   the HTML is agent-authored and may embed unescaped external text.
4. **QA — mandatory:** run
   `./qa.sh /tmp/diagram-<slug>.html /tmp/diagram-<slug>.png`; require its JSON receipt to
   pass, then follow the human image-readback gate in [qa.md](qa.md). Mechanical checks
   cannot establish factual truth or communication quality.
5. **Open** the PNG; **iterate** — edit, re-render, re-QA.
6. **Offer variations when the audience is unclear.** Two to four framings of the same
   facts, each its own HTML + PNG, plus a short table of *reader's question → framing →
   best for*. Recommend one.

If Chrome is missing: `brew install --cask google-chrome` or `apt-get install chromium`.
Never hand-write the SVG or PNG instead.

## QA acceptance gate

[qa.md](qa.md) owns both halves of acceptance: the deterministic `qa.sh` receipt and the
human PNG readback. A green receipt is necessary, never sufficient. The anti-pattern and
fixed examples prove the checker rejects known geometry failures without rejecting their
repair.

## The theme: Brief

Copy the `<style>` block from `template.html` verbatim.

| Token | Value | Where |
|---|---|---|
| `--paper` | `#FFFFFF` | canvas and default card fill |
| `--ink` | `#000000` | every heading, stroke, bullet; headings 700, body 400 |
| `--brand` | `#0B5CFF` | the top bar; the other party's kicker, border, chevron, `.num` |
| `--brand-tint` | `#E9F0FF` | fill for `.brand` cards and nodes |
| `--gate` | `#FFD24D` | the moment a human acts — kicker rule, 7px left bar, `.num`, `.dot` — **the anchor** |
| `--gate-tint` | `#FFF4D2` | fill for `.gate` cards and nodes |
| `--muted` | `#F2F2F2` | stop states, excluded paths |

- **Frame:** 5px brand bar; `h1` (24px) + subtitle (13.5px, 400) on one baseline over a rule.
- **Kickers:** 10.5px small caps over a 4px rule; `.gate` / `.brand` recolour it.
- **Cards:** 1px black, 4px radius; `h4` 15px; `li` 12px weight 400; a small-caps `.state`
  footer whose `.dot` is hollow until something happens.
- **Strokes:** 1px cards, 1.5px groups and connectors, 2.5px chevrons. Blue only on the
  arrow that crosses to the other party. `.phrase` / `<code>` in the mono stack.

## Output behavior

- Path: `/tmp/diagram-<slug>.png` unless told otherwise; default slide 1280×600 CSS →
  2560×1200 px. Offline-safe: zero network requests.
- Keep the `.html` and `.qa.json` beside the PNG — source, evidence, artifact. Committed
  diagrams commit all three (see `project-readme`). Inline embeds get a smaller quantised
  copy too (recipe in `layout-recipes.md`).

Converting a `.d2`, `.mmd`, or Mono Bold-era `.html`: the construct table is in
`layout-recipes.md`.
