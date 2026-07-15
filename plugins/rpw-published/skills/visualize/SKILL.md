---
name: visualize
description: This skill should be used to create a visual explanation of a concept as a styled Mermaid diagram. Trigger on phrases like "visualize X", "make a diagram of Y", "explain Z visually", "draw the architecture of W", "show me how X works", or when a multi-noun concept would be clearer with a picture than prose. Outputs a self-contained SVG using the canonical Mono Bold theme — pure white canvas, full black text, 1.25px borders, tri-color gradient fills with neon glow on highlighted nodes.
---

# Visualize Skill

Produce a visual explanation of a concept as a styled SVG diagram. Uses `beautiful-mermaid` with the canonical theme (Mono Bold structure + tri-color gradient highlights + neon drop-shadow glow). Output is a self-contained SVG file suitable for Slack drops, doc embeds, customer presentations.

## When to invoke

**Explicit triggers:**
- "visualize <concept>"
- "make a diagram of <X>"
- "explain <Y> visually"
- "draw <Z>"
- "show me how <X> works"
- "what does <W> look like?"

**Proactive use:** when explaining a multi-noun concept (≥4 entities + relationships) — reach for this skill instead of prose.

## The hard part is editorial

Rendering is mechanical; choosing what to draw is the skill. Before authoring:

1. **Pick the core nouns.** 7–10 entities that matter. Cut ruthlessly. A 25-node diagram is a failure of choice.
2. **Show structure, not actions.** Nouns + relationships, not verbs.
3. **Cluster.** Use Mermaid subgraphs to group related nouns.
4. **Pick one anchor.** The single node the reader should look at first. That gets the `yellow` accent.
5. **Highlight sparingly.** Most nodes stay white. Highlights are categorical, not decorative.
6. **Edge labels are 1–3 words.** "logs", "registers in", "contains" — not sentences.

## Highlight palette — tri-color gradients with neon glow

Used as box-fill on selected nodes. 0–3 highlights per diagram (not all five at once).

| Color | Gradient stops | Glow | Use for |
|---|---|---|---|
| `yellow` | `#FFE066 → #FF8E3C → #FF1F8F` (sunset-drama) | `#FF488F` | Primary accent / backbone |
| `emerald` | `#00F5A0 → #00E5FF → #C471F5` (aurora) | `#00E5FF` | Containers / scopes |
| `ruby` | `#FF1F8F → #C471F5 → #00E5FF` (berry-cyber) | `#C471F5` | Registries / catalogs |
| `sapphire` | `#18FFFF → #00B0FF → #FF1F8F` (cyber-wave) | `#00E5FF` | Outputs / artifacts |
| `amethyst` | `#B388FF → #FF488F → #FFE066` (ultraviolet) | `#FF488F` | Lifecycle stages |

The categorization is a suggested taxonomy — adapt per diagram, stay consistent within one document.

## Workflow

1. **Author** the Mermaid source at `/tmp/visualize-<slug>.mmd`.

2. **Render** via the bundled script:
   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/skills/visualize/render.mjs" \
     /tmp/visualize-<slug>.mmd \
     /tmp/visualize-<slug>.svg \
     --highlights '{"TS":"yellow","EX":"emerald","MOD":"sapphire"}'
   ```

   `--highlights` is a JSON object mapping node `data-id` → palette color name. Optional — omit for an all-white diagram.

   Add `--no-glow` to opt out of the neon drop-shadow halo (rare; default is glow on).

3. **Open**: `open /tmp/visualize-<slug>.svg` — renders in the default browser.

4. **Iterate.** Edit the `.mmd` source, re-run the render, the user refreshes the tab.

## Theme spec (locked — do not deviate)

The render script applies this automatically:

### Structure
- **Page canvas:** pure white `#FFFFFF`
- **Text:** pure black `#000000` everywhere (nodes, subgraph headers, edge labels)
- **Stroke widths:** 1.25px on ALL structural rects (nodes + subgraph rects, including header dividers — symmetric)
- **Edge labels:** NO stroke — text floats on canvas
- **Type:** font-weight 700, 13.5px nodes / 11px edge labels
- **Corner radius:** 4px on nodes, 0px on subgraphs

### Highlights
- Tri-color (or 2-stop) gradient fills via `<linearGradient>` at 135° diagonal
- Neon drop-shadow glow on each highlighted rect: `drop-shadow(0 0 4px <glow>) drop-shadow(0 0 12px <glow>)`
- Yellow backbone: when a node is highlighted yellow, edges from it use the yellow gradient's middle stop as a solid stroke, and edge label pills get the yellow gradient + glow

## First-time setup

The skill auto-installs `beautiful-mermaid` on first invocation. `node_modules/` and `package-lock.json` are gitignored.

## Output behavior

- File path: `/tmp/visualize-<slug>.svg` (or whatever the user specifies)
- Format: self-contained SVG (~14KB typical)
- Rendering surface: any modern browser, GitHub markdown, Notion paste, Slack drop
- **Privacy caveat:** the rendered SVG embeds `@import` for Inter from Google Fonts. Diagram **content** stays local; only the font file is fetched by viewers of the SVG. For air-gapped customer-data scenarios, post-process the SVG to remove the `@import` block.

## Example

```bash
node render.mjs examples/mlflow-core-nouns.mmd /tmp/mlflow.svg \
  --highlights '{"TS":"yellow","EX":"emerald","MOD":"sapphire","REG":"ruby","ALIAS":"amethyst"}'
```

Renders MLflow core nouns with all 5 palette colors, each as a tri-color gradient with a neon glow halo. The Tracking Server (yellow) acts as the backbone — its `persists` edges become yellow-stroked with yellow gradient pill labels.
