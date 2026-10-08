"""
Configuration constants for the Google Docs MCP server.

Values are read from the environment at import time (same behavior as the
former gdocs_mvp module). Modules reference these as ``config.<NAME>`` so tests
can override them via ``patch.object(config, "TARGET_FOLDER_ID", ...)`` and the
change is visible at every call site.
"""

import json
import os
from pathlib import Path

# ============================================================================
# CONFIG — Change this folder ID to scope all operations
# ============================================================================
TARGET_FOLDER_ID = os.environ.get("GDOCS_TARGET_FOLDER_ID", "")
QUOTA_PROJECT = os.environ.get("GDOCS_QUOTA_PROJECT", "your-gcp-project-id")
# ---------------------------------------------------------------------------
# The house style (#2001)
# ---------------------------------------------------------------------------
# house_style.json is the single source of style values. The renderer emits
# structure only; paragraph spacing, fonts and sizes come from named styles that
# the normalize pass (style_normalize.py) pins after every write tool, and the
# lint (style_lint.py) checks. The constants below are the few values the
# renderer itself needs, read from that file so they cannot drift.
HOUSE_STYLE = json.loads((Path(__file__).resolve().parent / "house_style.json").read_text(encoding="utf-8"))

# Monospace font for code blocks and inline code.
CODE_FONT = HOUSE_STYLE["code"]["font_family"]

# Grey tint + bold on table header rows. Validated: 48/48 corpus tables have a
# bold row 0, and tinted header cells are never reverted where the renderer
# applied them (#1768).
TABLE_HEADER_TINT_RGB = HOUSE_STYLE["tables"]["header_row_tint_rgb"]

# Vertical centring applies to EVERY cell, not just the header row (#1770). The
# header-only version left body cells sitting at the top of their cell, which
# reads as a rendering bug next to a centred header — and Randy centres whole
# tables by hand.
TABLE_CELL_CONTENT_ALIGNMENT = HOUSE_STYLE["tables"]["cell_content_alignment"]

# Tables span the destination's full text width (#1770). Columns were previously
# left to whatever Docs' insertTable chose, and before that hard-set to 175pt
# each — 3 columns = 525pt on a 468pt text column, i.e. an overflowing table.
# The width is COMPUTED per destination at write time from
# pageSize.width - marginLeft - marginRight (a tab uses its own
# documentTab.documentStyle), split evenly, FIXED_WIDTH. The Docs API exposes no
# table alignment field, so full width is also what makes "centre the table"
# moot. This constant is only the fallback for a destination that reports no
# documentStyle at all: US Letter (612pt) with 1" margins, which is every doc in
# Randy's corpus.
FALLBACK_TEXT_WIDTH_PT = HOUSE_STYLE["page"]["width_pt"] - 2 * HOUSE_STYLE["page"]["margin_pt"]

# Block quotes: indented with a left rule, so a quote does not read as body
# prose (PAIN-003). Docs has no native blockquote construct.
BLOCK_QUOTE_INDENT_PT = 36
BLOCK_QUOTE_BORDER = {
    "color": {"color": {"rgbColor": {"red": 0.6, "green": 0.6, "blue": 0.6}}},
    "width": {"magnitude": 1.5, "unit": "PT"},
    "padding": {"magnitude": 6, "unit": "PT"},
    "dashStyle": "SOLID",
}

# Unordered lists. Hand-typed tabs use "-" dash glyphs, which the Docs API
# cannot produce for rendered content — four live probes in
# docs/research/2026-09-13-gdocs-dash-bullets.md (#1770): no dash exists in the
# BulletGlyphPreset enum, Bullet.listId is read-only, nothing in the 40-request
# write surface defines a glyph, and the one mechanism that DOES yield "-"
# (splitting an existing dash paragraph) needs a dash list inside the very
# paragraph being written to — which a freshly added tab never has, because list
# definitions are per-tab.
# BULLET_ARROW_DIAMOND_DISC is the fallback: measured glyphs ➔ / ◆ / ●, and its
# top-level mark is the only horizontally-oriented one of the nine presets, so it
# reads closest to a dash.
BULLET_PRESET = "BULLET_ARROW_DIAMOND_DISC"
ORDERED_BULLET_PRESET = "NUMBERED_DECIMAL_ALPHA_ROMAN"

# Indent applied per bullet nesting level to the 2nd+ paragraph of a loose (multi-
# paragraph) list item (#528). Those paragraphs are inserted as ordinary list lines
# so their text survives, then un-bulleted — Docs drops the bullet indentation with
# the bullet, so the indent has to be restored explicitly or the continuation text
# falls back to the left margin. 36pt matches the Docs default bullet indentStart,
# which is where the item's own text sits.
LIST_INDENT_PER_LEVEL_PT = HOUSE_STYLE["lists"]["indent_step_pt"]
