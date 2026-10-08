# Layout recipes — the CSS side of the diagram skill

Everything the `diagram` SKILL.md points at for mechanics. The theme values and the
editorial rules live in SKILL.md; this file is how you get a shape out of CSS grid and
inline SVG. `template.html` is the runnable version of all of it.

## Canvas geometry

The page is a fixed-width `<body>` that stacks a brand bar, a header, and a `.canvas`:

```css
:root{ --canvas-w:1280px; --canvas-h:600px; --gutter:34px; }
body{ width:var(--canvas-w); min-height:var(--canvas-h); display:flex; flex-direction:column; }
.canvas{ flex:1 1 auto; padding:16px 34px 18px; display:flex; flex-direction:column; gap:16px; }
```

- **`width` belongs on `<body>`.** `render.sh` measures the page off `document.body`'s
  box. Put the width on an inner div instead and the measured width collapses to the
  throwaway viewport's, so the PNG comes out cropped.
- **`min-height`, never `height`.** `--canvas-h:600px` gives a 16:7.5 slide when the
  content is short and grows when it is not. `<body style="--canvas-h:0">` makes the PNG
  hug its content — right for a journey with no always-on band.
- **A `.section.grow` absorbs the spare height.** In the template that is the always-on
  band, so its cards stretch to the bottom edge instead of leaving a white strip.
- **Never set a height** on `.canvas`, a `.group`, or a `.card`. Heights are what clip
  content, and clipping is invisible in the source (see `examples/overlap-antipattern.html`).
- **Sizing:** keep `--canvas-w` ≤ 1600. The default 1280 renders 12px body copy at 24px in
  the PNG — legible when a doc column scales it to 800 wide.

## Frame

```html
<div class="brand-bar"></div>
<div class="hd">
  <h1>The answer, in one line</h1>
  <p>One sentence telling the reader which line to follow.</p>
</div>
```

`h1` is `white-space:nowrap`; if it wraps, it is too long. The subtitle is weight 400 and
should fit the rest of the line — two lines of subtitle push the whole canvas down and
read as a paragraph, not a caption.

## Sections and kickers

```html
<div class="section">
  <div class="kicker">Phase 1 · what happens first</div>
  ...a row...
</div>
```

| Class | Meaning |
|---|---|
| `.kicker` | black 4px rule — the reader's own side, or neutral |
| `.kicker.gate` | yellow rule — a human acts here |
| `.kicker.brand` | blue rule — the other party |
| `.kicker.dashed` | a trust boundary (the *boundary* framing) |

In a stepper the kickers sit **inside the row grid** and span their phase's columns
(`grid-column:1 / span 5`), so the rule lines up exactly over the cards it labels.

## Rows

```css
.row{ display:grid; align-items:stretch; }
```

Restate `grid-template-columns` inline per row. **Odd columns are cards, even columns
are gutters** (`var(--gutter)`), each gutter holding a `.chev` or a `.conn`:

```html
<div class="row" style="grid-template-columns:1fr var(--gutter) 1fr var(--gutter) 1fr;row-gap:11px">
```

With kickers in the same grid, `row-gap` is the space between the kicker row and the
card row. Cards go in `grid-row` 2 automatically when every kicker is placed explicitly
on row 1 — set `grid-column` on each card and let the grid auto-place the row.

For a band without gutters use `.cols3` / `.cols4` / `.cols6` (equal columns, fixed gap).

## Cards

```html
<div class="card gate">
  <div class="num">4</div>
  <h4>Send one test event</h4>
  <ul><li>You type SEND 1 TEST EVENT to unlock it</li><li>Exactly one event goes out</li></ul>
  <div class="state"><span class="dot gate"></span>1 event sent</div>
</div>
```

| Piece | Rule |
|---|---|
| `.num` | optional step numeral; only in steppers |
| `h4` | the headline; 2–5 words |
| `ul > li` | 2–3 facts, weight 400, one fact each |
| `.state` | `margin-top:auto` pins it to the bottom, so every card's footer sits on one line across the row |
| `.dot` / `.dot.gate` / `.dot.brand` | hollow = nothing happened yet; filled = it did |
| `.phrase` | a literal the reader types, mono |
| `.big` + `em` | a by-the-numbers tile: 42px numeral, then a 12.5px label |
| `.card.aside` | dashed — context, not part of the flow ("what never crosses") |
| `.card.muted` | grey — a stop state or an excluded path |

`<code>` inside any text switches to the mono stack at weight 400.

## Groups and nodes (the journey framing)

A `.group` is a bordered zone that holds `.node`s; use it when the reader's question is
*where*, not *when*.

```html
<div class="group brand">
  <h3><span class="num">3</span>Model Registry<span class="verb">promotes</span></h3>
  <div class="vstack">
    <div class="node brand"><b>Registered Model</b><span>One name, many versions</span></div>
    <div class="node aside"><b>Serving endpoint</b><span>Outside MLflow</span></div>
  </div>
</div>
```

| Primitive | What it is for |
|---|---|
| `.group > h3` | zone heading, small caps; a `.num` in it numbers the zone |
| `.verb` badge in the `h3` | the edge verb, pushed to the right — `reads in place`, `persists` |
| `.subhead` | a divider inside a group with a hairline after the label |
| `.node` | one noun: `<b>` headline + `<span>` gloss |
| `.node.gate` / `.node.brand` / `.node.muted` / `.node.aside` | same roles as the card classes |
| `.vstack` / `.grid2` / `.grid3` | pack nodes; `.vstack` centres vertically so a short zone lines up with a tall one |

**Verb badges in headers beat edge labels.** One badge per group replaces N labels in the
gutter, and a badge cannot collide with a stroke.

## Connectors

### Chevrons — between cards in a row

```html
<div class="chev" style="grid-column:2"><svg viewBox="0 0 24 24">
  <path d="M6,4 L17,12 L6,20" fill="none" stroke="#000" stroke-width="2.5"/></svg></div>
```

The default. `stroke="#0B5CFF"` on the one chevron that crosses to the other party.

### SVG gutters — between groups, or with a label

One `<svg>` per gutter cell, absolutely filling it:

```html
<div class="conn" style="grid-column:2">
  <svg viewBox="0 0 100 100" preserveAspectRatio="none">
    <defs><marker id="arw" markerWidth="10" markerHeight="10" refX="9" refY="5"
      orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#000"/></marker></defs>
    <line x1="2" y1="50" x2="90" y2="50" marker-end="url(#arw)"/>
  </svg>
  <span class="elabel" style="left:50%;top:42%">logs</span>
</div>
```

- `viewBox="0 0 100 100"` + `preserveAspectRatio="none"` makes **x and y percentages of
  the cell**. A path written this way survives the neighbouring column growing taller.
- `vector-effect:non-scaling-stroke` (in the theme block) keeps the stroke width constant
  regardless of that stretch.
- **Stop at x ≈ 90, start at x ≈ 2.** The svg is `overflow:visible`, so a path past 100
  leaves the gutter and draws straight through the next group's border and text.
- **The theme styles `svg > path` and `svg > line` only** — direct children. A bare
  `.conn path{fill:none}` would also hit the marker's path and render every arrowhead
  hollow. Keep it that way if you add rules.
- `class="brand"` on a line = the blue 2.5px crossing arrow; give its marker
  `fill="#0B5CFF"` too. `class="dashed"` = weaker or asynchronous.
- **Fan-out** from one node to N groups: same start y, one bezier per target, control
  points at x 45–50 so the curves separate late. Read target y off the rendered PNG and
  nudge, rather than computing it.
- **Arrowheads stretch with the gutter's aspect ratio.** A tall, narrow gutter gives a
  tall, thin head. Widen the gutter (56px in the journey example) or use a chevron.

### Edge labels

`.elabel` is absolutely positioned with a `background:var(--paper)` so the line does not
read through the words. Place it with inline `left`/`top` percentages, offset off the
line's own row (`top:42%` against a line at `y=50`).

### The boundary crossing

For the *boundary* framing, the middle gutter is a column with a dashed vertical rule and
one arrow across it:

```html
<div style="position:relative">
  <div style="position:absolute;left:50%;top:0;bottom:0;border-left:2.5px dashed var(--brand)"></div>
  <div style="position:absolute;left:0;right:0;top:50%;transform:translateY(-50%);
              display:flex;flex-direction:column;align-items:center;gap:5px">
    <span style="font-size:11.5px;background:var(--paper);padding:1px 6px">one HTTPS POST</span>
    <svg viewBox="0 0 118 26" width="118" height="26">
      <line x1="0" y1="13" x2="104" y2="13" stroke="#0B5CFF" stroke-width="2.5"/>
      <path d="M99,6 L111,13 L99,20" fill="none" stroke="#0B5CFF" stroke-width="2.5"/>
    </svg>
  </div>
</div>
```

Pair it with a `.kicker.dashed` above ("The boundary") and a `.card.aside` on the far side
("What never crosses").

## Rendering

`./render.sh <in.html> [out.png]` does two Chrome passes, because `--screenshot` captures
the *window*, not the page:

1. **Measure.** Appends a measuring script to a temp copy, reads the page size back out
   of `<title>` via `--dump-dom`. It measures `document.body`'s box because
   `documentElement.scrollHeight` floors at the viewport height — measure that instead and
   a tall window reports the *window's* height, padding the PNG with dead white space.
2. **Screenshot.** `--window-size=<measured> --force-device-scale-factor=2` → a PNG at
   exactly 2× the CSS pixel size.

It prints `out.png  <w>x<h> css px  ->  <2w>x<2h> px @2x`. If those numbers are not 2× the
CSS size, the scale factor did not apply and the PNG is not the artifact you promised.

Overrides: `CHROME_PATH` for an odd Chrome install, `RPW_SCALE` for a scale other than 2.
Chrome discovery order is `CHROME_PATH` → PATH (`google-chrome`, `chromium`, …) → the macOS
app bundle and `/opt/google/chrome/chrome`.

### An embed-sized copy

A notebook or doc that inlines the PNG as base64 wants a smaller file. With Pillow:

```bash
uv run --with pillow python -c "
from PIL import Image; im=Image.open('out.png'); w=1600
im.resize((w, im.height*w//im.width), Image.LANCZOS).quantize(64).save('out-embed.png', optimize=True)"
```

Keep the full-size PNG next to it; the embed copy is a derivative.

### Troubleshooting

| Symptom | Cause |
|---|---|
| PNG is Chrome's "site can't be reached" page | a relative `file://` path — `render.sh` absolutises it; a hand-run `chrome` invocation does not |
| Bottom of the diagram cut off | a hand-passed `--window-size` (or a `height` set in CSS) |
| Wide white band under the diagram | same, oversized in the other direction — or `--canvas-h` taller than the content wants; set it to 0 |
| Cards in the always-on band mostly empty | the band is the `.section.grow`; give it more facts or set `--canvas-h:0` |
| Arrowheads hollow | a `path{fill:none}` rule reached the `<marker>`; style `svg > path` only |
| Text blurry | `--force-device-scale-factor=2` missing |
| Fonts differ from the reference PNG | the CSS names a font this machine lacks — keep the theme's system stack |

## Migrating an older source

| D2 / Mono Bold HTML | Brief HTML |
|---|---|
| `direction: right` | a `.row` with cards or groups in odd columns |
| `x: Label { ... }` container / `.group` | `<div class="group"><h3>Label</h3>…</div>` — unchanged |
| `a: Label` / `.node` | `<div class="node"><b>Label</b><span>gloss</span></div>` — or a `.card` with an `h4` if it has facts |
| `.node.hub.anchor` (the yellow hub) | there is no hub. Either the zone numbered `1`, or the `.gate` card if the anchor was a human action |
| `.node.accent` (cyan) | `.brand` if it is the other party; otherwise plain |
| `a -> b: verb` | a `.chev` between cards, or a `.conn` + `.verb` badge / `.elabel` |
| `style.stroke-dash: 4` | `class="dashed"` |
| no title | write the `h1` + subtitle first — the migration is the moment to say what the picture is for |
| `d2` + `rsvg-convert` | `./render.sh` |

Mermaid `.mmd` sources predate D2; convert them the same way, via the D2 column.
