#!/usr/bin/env node
/**
 * visualize — render a Mermaid source as a styled SVG using the
 * canonical Mono Bold + tri-color gradient + neon glow theme.
 *
 * Usage:
 *   node render.mjs <input.mmd> <output.svg> [--highlights '<json>'] [--no-glow]
 *
 * --highlights: JSON object mapping node data-id → palette color name.
 *   Example: '{"TS":"yellow","EX":"emerald"}'
 *   Palette: yellow, emerald, ruby, sapphire, amethyst
 *
 * --no-glow: opt out of the neon drop-shadow glow on highlighted nodes.
 *
 * Side effects:
 *   - On first run, installs beautiful-mermaid into the skill dir.
 *   - Writes the rendered SVG to the output path.
 */

import { existsSync, readFileSync, writeFileSync } from 'fs';
import { dirname, join, resolve } from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const __dirname = dirname(fileURLToPath(import.meta.url));

// ── Lazy install of beautiful-mermaid on first use ──
const bmPath = join(__dirname, 'node_modules', 'beautiful-mermaid');
if (!existsSync(bmPath)) {
  console.error('First-time setup: installing beautiful-mermaid...');
  execSync('npm install --silent', { cwd: __dirname, stdio: 'inherit' });
}

const { renderMermaidSVG } = await import('beautiful-mermaid');

// ── CLI argument parsing ──
const args = process.argv.slice(2);
if (args.length < 2 || args.includes('--help') || args.includes('-h')) {
  console.error(`Usage: render.mjs <input.mmd> <output.svg> [--highlights '<json>'] [--no-glow]

Palette colors: yellow, emerald, ruby, sapphire, amethyst
Example:
  render.mjs source.mmd out.svg --highlights '{"TS":"yellow","EX":"emerald"}'`);
  process.exit(args.includes('--help') || args.includes('-h') ? 0 : 1);
}

const inputPath = resolve(args[0]);
const outputPath = resolve(args[1]);
const hIdx = args.indexOf('--highlights');
const highlights = hIdx >= 0 && args[hIdx + 1] ? JSON.parse(args[hIdx + 1]) : {};
const glow = !args.includes('--no-glow');

if (!existsSync(inputPath)) {
  console.error(`Input file not found: ${inputPath}`);
  process.exit(1);
}

// ── Canonical palette ──
// Each highlight color is a tri-color gradient (or 2-stop for `yellow`'s soft
// variant) with a designated `glow` color (most-vivid stop, used as a neon
// drop-shadow halo when --glow is enabled). All stops chosen so #000 text
// reads at ≥5:1 contrast across the gradient.
const PALETTE = {
  yellow:   { stops: ['#FFE066', '#FF8E3C', '#FF1F8F'], glow: '#FF488F' }, // sunset-drama
  emerald:  { stops: ['#00F5A0', '#00E5FF', '#C471F5'], glow: '#00E5FF' }, // aurora
  ruby:     { stops: ['#FF1F8F', '#C471F5', '#00E5FF'], glow: '#C471F5' }, // berry-cyber
  sapphire: { stops: ['#18FFFF', '#00B0FF', '#FF1F8F'], glow: '#00E5FF' }, // cyber-wave
  amethyst: { stops: ['#B388FF', '#FF488F', '#FFE066'], glow: '#FF488F' }, // ultraviolet
};

const SCOPE_CLASS = 'bm-visualize';
const COLORS = {
  bg:      '#FFFFFF',
  fg:      '#000000',
  line:    '#000000',
  muted:   '#000000',
  surface: '#FFFFFF',
  border:  '#000000',
};

// Identify the primary-accent node (first node with yellow assignment).
// All edges *from* that node get the yellow gradient backbone treatment.
const primaryAccentId = Object.entries(highlights).find(([_, c]) => c === 'yellow')?.[0];

// ── Gradient <defs> for each color actually used ──
const usedColors = [...new Set(Object.values(highlights))];
const gradientDefs = usedColors
  .filter((color) => PALETTE[color])
  .map((color) => {
    const stops = PALETTE[color].stops;
    const stopElems = stops
      .map((hex, i) => `<stop offset="${(i / (stops.length - 1)) * 100}%" stop-color="${hex}"/>`)
      .join('');
    return `<linearGradient id="${SCOPE_CLASS}-grad-${color}" x1="0%" y1="0%" x2="100%" y2="100%">${stopElems}</linearGradient>`;
  })
  .join('');

// Per-node highlight rules — gradient fill + optional glow filter
const highlightRules = Object.entries(highlights)
  .map(([nodeId, colorName]) => {
    const palette = PALETTE[colorName];
    if (!palette) return '';
    const glowFilter = glow
      ? `filter: drop-shadow(0 0 4px ${palette.glow}) drop-shadow(0 0 12px ${palette.glow});`
      : '';
    return `
    .${SCOPE_CLASS} .node[data-id="${nodeId}"] rect {
      fill: url(#${SCOPE_CLASS}-grad-${colorName});
      stroke: #000000;
      stroke-width: 1.25;
      ${glowFilter}
    }`;
  })
  .join('');

// Yellow-node backbone: edges from the yellow-highlighted node take the yellow
// gradient's middle stop as a solid stroke (gradient strokes on thin lines
// don't read), and edge label pills get the gradient + glow.
const yellowMid = PALETTE.yellow.stops[1];
const backboneRules = primaryAccentId ? `
    .${SCOPE_CLASS} .edge[data-from="${primaryAccentId}"] {
      stroke: ${yellowMid};
      stroke-width: 1.25;
    }
    .${SCOPE_CLASS} .edge-label[data-from="${primaryAccentId}"] rect {
      fill: url(#${SCOPE_CLASS}-grad-yellow);
      stroke: none;
      stroke-width: 0;
      rx: 3;
      ry: 3;
      ${glow ? `filter: drop-shadow(0 0 4px ${PALETTE.yellow.glow});` : ''}
    }
    .${SCOPE_CLASS} .edge-label[data-from="${primaryAccentId}"] text {
      fill: #000000;
      font-weight: 700;
      font-size: 11px;
    }
` : '';

const cssOverrides = `
    /* visualize — Mono Bold + tri-color gradients + neon glow (locked spec) */

    .${SCOPE_CLASS} .node rect {
      rx: 4;
      ry: 4;
      stroke-width: 1.25;
      stroke: #000000;
      fill: #FFFFFF;
    }
    .${SCOPE_CLASS} .node text {
      font-weight: 700;
      font-size: 13.5px;
      fill: #000000;
    }
    ${highlightRules}

    .${SCOPE_CLASS} .subgraph rect {
      stroke-width: 1.25;
      stroke: #000000;
      rx: 0;
      ry: 0;
      fill: #FFFFFF;
    }
    .${SCOPE_CLASS} .subgraph text {
      fill: #000000;
      font-weight: 700;
    }

    .${SCOPE_CLASS} .edge {
      stroke-width: 1.25;
      stroke: #000000;
    }
    ${backboneRules}

    .${SCOPE_CLASS} .edge-label text {
      font-size: 11px;
      font-weight: 700;
      fill: #000000;
    }
    .${SCOPE_CLASS} .edge-label rect {
      rx: 0;
      ry: 0;
      stroke: none;
      stroke-width: 0;
      fill: #FFFFFF;
    }
`;

// ── Render ──
const source = readFileSync(inputPath, 'utf-8');
let svg = renderMermaidSVG(source, COLORS);
svg = svg.replace(/^<svg /, `<svg class="${SCOPE_CLASS}" `);
svg = svg.replace(/(<svg[^>]*>)/, `$1<defs>${gradientDefs}</defs><style>${cssOverrides}</style>`);

writeFileSync(outputPath, svg);
console.log(`Rendered: ${outputPath} (${svg.length}b)${glow ? ' [glow]' : ' [no-glow]'}`);
