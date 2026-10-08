---
name: favicon-standards
description: Give a project its icon and wire it into a web surface as a favicon — the generation prompt, the hue registry, the asset pipeline, and the required HTML tag set. Use when adding a favicon, creating a project icon, a new web surface has the default blank tab icon, an icon looks wrong at 16px, or the favicon gate test fails. Trigger on "add a favicon", "project icon", "generate an icon for this project", "why is our tab icon blank", "regenerate the icons".
---

# Project Icons and Favicons

Every project gets an icon; every web surface we build serves that icon as its
favicon. A blank tab is a bug — a browser tab strip with six of our surfaces open
should be readable at a glance.

Two things carry the standard, and they do not overlap:

| Artifact | Owns |
|---|---|
| `assets/project-icons/registry.json` | which project has which hue, glyph, source, asset dir, theme color, and surfaces |
| `scripts/build_icons.py` | turning one source image into the shipped asset set |

`tests/test_favicon_standards.py` asserts the tree matches the registry, and runs
in `make check`. **Add a surface → add it to the registry**, or the gate fails.

Icons are one piece of the design system — the rest of a surface's styling
(tokens, typography, status colors) comes from `libs/ui/DESIGN.md` via the
`web-design` skill; the hue registry stays authoritative for icon hues only.

## The pipeline, end to end

```bash
# 1. generate a 1024x1024 source (prompt below), save it into the repo
#    so the set is regenerable — never keep the source outside the tree
mv ~/Downloads/generated.png assets/project-icons/<project>.png

# 2. build the asset set; it prints the theme-color to use
make icons SRC=assets/project-icons/<project>.png OUT=<web-root>

# 3. paste the tag set into the surface's <head>, with that theme-color
# 4. add the project (or the new surface) to assets/project-icons/registry.json
make check
```

## Generation prompt — two passes

**Pass 1, invention.** Ask the image model for the glyph, giving it the project's
one-line description and nothing else: *"What single simple shape would represent
this project as an app icon? Name one shape."* Take its answer.

**Pass 2, production.** Drop that shape name into this template, varying **only**
the glyph and the hue. Everything else is fixed, because everything else is what
makes eight icons look like one family:

> A single app icon tile, square, filling the entire frame edge to edge with no
> border or margin. Digital art with gradients, striking color contrasts, lighting
> and shadow work, digital textures, smooth abstract shapes. Deep `<HUE>` ground
> with a bright `<HUE>` gradient. Centered on it, one solid filled white
> **`<GLYPH>`** silhouette, geometric and simple, occupying about half the tile.
> The silhouette must be a single filled shape, not an outline. It must never
> resemble a letter of any alphabet. Don't include any people or text of any kind
> in your image.

Two-pass, rather than naming the glyph yourself: the model's own reading of the
project is usually better than ours, but a description handed straight to the
production prompt drifts — it invents a scene, not a silhouette. Pass 1 gets the
idea; pass 2 pins it to one shape.

## Hue: 45° steps first, claimed once

One palette family rotated per project, so no two icons read as the same color at
16px. `registry.json` holds the assignments and the reserved-but-unbuilt ones.
Claim the next unused step; never reuse one.

The 45° ladder (0/45/…/315) is now fully claimed or reserved, so the registry's
`VALID_HUES` widened to 15° steps: the ninth project takes the free step farthest
from every hue already listed. Finer steps mean two hues can sit 15° apart — the
glyph carries the distinction at 16px, so make it a shape nobody else uses.

## The 16px rule

16px is the binding constraint — it is the size the browser actually picks, and it
is ~256 pixels total. So:

- **At most two elements** in the glyph. A bolt is fine. A bolt inside a shield
  with a gradient ring is three, and at 16px it is a smudge.
- **Filled, never outlined.** Outline strokes vanish below ~24px.
- **Never letter-shaped.** An arch, a door, a bracket all read as a letterform at
  small size, which makes the icon look like a typo.
- **Verify, do not assume.** Upscale `favicon-16.png` with NEAREST onto both a dark
  (`#18181B`) and a light (`#FAFAFA`) ground and look at it. If you cannot tell
  what it is, re-roll pass 2 — do not ship it and hope.

## What the prompt must NOT be asked to fix

Two defects come back from every image model no matter how the prompt is worded,
so `scripts/build_icons.py` fixes them deterministically instead:

- **Opaque corners.** A generated "rounded" tile has its ground painted into the
  corners, which shows as four bright dots on a dark tab strip. Only a real alpha
  mask removes them.
- **A tile floating on a flat margin.** The script detects a flat border ring and
  crops it; a tile that correctly bleeds to the frame is left alone.

Re-rolling for either is wasted effort. Re-roll only for the glyph.

## Required tag set

```html
<!-- Project icon (favicon-standards skill). Assets are generated from
     assets/project-icons/<project>.png by scripts/build_icons.py — never hand-edited.
     .ico first for the browsers that read only that one. -->
<link rel="icon" href="/favicon.ico" sizes="any" />
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<meta name="theme-color" content="#RRGGBB" />
```

- **No `favicon.svg`.** The art is raster. A PNG wrapped in an `<svg><image>` to
  claim an SVG slot is a lie the browser then prefers over the real sized PNGs.
- `apple-touch-icon.png` is **unmasked and opaque on purpose** — iOS applies its
  own mask, and an alpha channel there composites against black.
- `theme-color` is per project, not a house color: use the value `make icons` prints.

### When the surface cannot own the paths

A reverse proxy whose `/favicon.*` paths pass through to an upstream app cannot
serve its own — a route there would shadow the app's tab icon. Such a surface
inlines a base64 data URI instead, computed once at import (see the retired
`projects/omnigent-front-door`'s `checks.py:favicon_tag` for the pattern, #1758).
Record it as `inline` in the registry with the reason. That also means the icon
still renders when the upstream is down, which is exactly when someone is reading
a diagnostic page.

## Two tiers: icon and hero

The 16px constraint kills the abstract-art look, and abstract art is the house
style everywhere else. So each project gets **two** images from the same palette:

| Tier | Size | Content | Used by |
|---|---|---|---|
| Icon | 512 → 16 | one white glyph on the hue ground | favicons, home screen, manifest |
| Hero | 1024+ | pure abstract, no glyph | README header, docs banner, slide art |

The hero uses the standard prompt with no glyph clause and the same hue — same
family, no legibility constraint. Heroes are **not built yet** (web surfaces came
first); build one when a project's README needs it.
