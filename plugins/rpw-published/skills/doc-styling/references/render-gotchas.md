# Render gotchas — google-docs MCP

Detail moved out of [../SKILL.md](../SKILL.md) (#2001) to keep the skill inside its size budget.

Verified against the current `plugins/rpw-published/mcp-servers/google-docs/` source. Behavior
has shifted as bugs were fixed — trust the code, and when a live doc matters, validate the
render (create a scratch doc, write test content, run `gdocs_lint` on it, then delete it).

- **Markdown tables in nested sub-tabs write correctly** (was #198, fixed). The historical
  bug — tables rendering as empty grids in sub-tabs — came from a flat `tabId` scan that missed
  nested tabs; `write_to_tab` now resolves tabs through the recursive `_find_tab_by_id`, so
  tables land with content at any nesting depth. Tables are safe; you don't need to fall back
  to bulleted rows to work around this.
- **Hyperlinks, inline-cell formatting, and nested link-bullets render correctly** (#222,
  verified fixed). Code hyperlinks (`` [`code`](url) ``) get color-only styling (the auto
  underline is cleared so it doesn't clash with underscores); codespans inside **bold** are
  emitted at `weight:700` so they stay bold *and* monospace.
- **Every write tool applies the house style itself** (#2001). The renderer writes
  structure only. Then `gdocs_create` / `gdocs_update` / `gdocs_add_tab` /
  `gdocs_write_to_tab` normalize the written tab to `house_style.json` (named styles
  pinned per tab, stray overrides reset, blank paragraphs next to headings removed) and
  lint it. Blank markdown lines survive between prose blocks, never next to a heading.
  Code is Courier New at the inherited size. Every table cell is vertically centred with a
  bold + grey-tinted header row. There is no `style_preset`, `code_font`, or
  `bullet_preset` parameter. `gdocs_find_replace` is not gated: replaced text keeps the
  style it replaces.
- **Tables span the full text width; bullets are arrows, not dashes** (#1770). Column widths
  are computed per destination from `pageSize.width - marginLeft - marginRight` and split
  evenly, so a 2-column table is as wide as a 5-column one. Rendered unordered bullets come
  out `➔ / ◆ / ●`: the Docs API has no dash glyph and cannot define one (four probes in
  `docs/research/2026-09-13-gdocs-dash-bullets.md`). Keep writing `-` in markdown — that is
  the source syntax, not the rendered glyph.
- **Bullet inheritance + paragraph spacing are fixed** (#301). Inherited list bullets are
  cleared and paragraph spacing is normalized, so re-writing a tab no longer leaves stray
  bullets or compressed/expanded spacing from prior content.
- **`gdocs_read` reads nested sub-tabs and their tables** (#216). The current read path
  recurses into `childTabs` at any depth and renders each table's cells as tab-separated text,
  so sub-tab table content *is* surfaced. Doc-read API shape has bitten before (per-tab vs.
  top-level nesting), so for a high-stakes render still confirm against the live doc rather than
  trusting a single read.
- **`gdocs_find_replace` supports tab scoping.** Passing `tab_id` now sends the API-correct
  `tabsCriteria.tabIds`, so a tab-scoped replace works — the old Docs-API 400 came from an
  unsupported request shape and no longer applies. A unique `find_text` still works doc-wide
  when you omit `tab_id`; prefer that when the target string is already unique.
