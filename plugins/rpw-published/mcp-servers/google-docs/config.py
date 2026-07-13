"""
Configuration constants for the Google Docs MCP server.

Values are read from the environment at import time (same behavior as the
former gdocs_mvp module). Modules reference these as ``config.<NAME>`` so tests
can override them via ``patch.object(config, "TARGET_FOLDER_ID", ...)`` and the
change is visible at every call site.
"""

import os

# ============================================================================
# CONFIG — Change this folder ID to scope all operations
# ============================================================================
TARGET_FOLDER_ID = os.environ.get("GDOCS_TARGET_FOLDER_ID", "")
QUOTA_PROJECT = os.environ.get("GDOCS_QUOTA_PROJECT", "your-gcp-project-id")
DEFAULT_CODE_FONT = "Courier New"

# Space rendered below every emitted heading/normal paragraph (#301 bug 2). Blank
# markdown lines are dropped by the parser, so without an explicit spaceBelow the
# rendered doc reads as a dense wall of single-spaced lines. A small paragraph
# spacing reproduces the visual gap of normal Docs prose without littering the
# doc with invisible U+00A0 spacer paragraphs (the previous content-side hack).
PARAGRAPH_SPACE_BELOW_PT = 10

# Unordered-list bullet presets accepted by gdocs_write_to_tab's bullet_preset
# parameter (#170). These are the Docs API createParagraphBullets.bulletPreset
# enum values that render a bullet glyph; ordered lists always use the NUMBERED
# preset and are not overridable. A literal "-" dash glyph is NOT achievable via
# the Docs API (NestingLevel.glyphSymbol is read-only over batchUpdate), so the
# closest visually-lighter preset is the best available approximation.
VALID_BULLET_PRESETS = frozenset({
    "BULLET_DISC_CIRCLE_SQUARE",
    "BULLET_DIAMONDX_ARROW3D_SQUARE",
    "BULLET_CHECKBOX",
    "BULLET_ARROW_DIAMOND_DISC",
    "BULLET_STAR_CIRCLE_SQUARE",
    "BULLET_ARROW3D_CIRCLE_SQUARE",
    "BULLET_LEFTTRIANGLE_DIAMOND_DISC",
    "BULLET_DIAMONDX_HOLLOWDIAMOND_SQUARE",
    "BULLET_DIAMOND_CIRCLE_SQUARE",
})
