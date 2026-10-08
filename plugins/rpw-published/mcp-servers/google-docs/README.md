# Google Docs MCP Server

MCP server for Google Docs CRUD, tabs (including nested subtabs), find/replace, tab-targeted write, advanced operations, Google Slides read/metadata + template fill (copy-template, batch placeholder replace, table-cell fill, image insert), and Google Sheets values read/write/append/clear + `batchUpdate` formatting. Uses gcloud ADC auth and enforces read-only mode, folder allow-list, and audit logging.

## Setup

1. **Install dependencies** (uv):

   ```bash
   cd mcp-servers/google-docs
   uv sync
   ```

2. **Configure environment files**:

   ```bash
   cp template.env dev.env
   cp template.env test.env
   cp template.env prod.env
   # Edit each file with environment-specific values
   ```

3. **Authenticate and validate the shared ADC grant**:

   ```bash
   cd "$CLAUDE_PLUGIN_ROOT/skills/mcp-setup"
   uv run python google_adc.py
   ```

   `server_registry.py` is the canonical scope source for all ADC-backed Google
   MCP servers. If validation reports missing scopes, run its generated full-union
   `gcloud auth application-default login --scopes=...` command. That command
   includes identity, Vertex, Drive, Docs, Sheets, Slides, and Tasks scopes.
   Re-running `application-default login --scopes=...` **replaces** the ADC scope
   set, so never substitute a Docs-only list.

## Run

Defaults to `APP_ENV=dev`:

```bash
uv run python run_mcp.py
```

Switch environment:

```bash
APP_ENV=test uv run python run_mcp.py
APP_ENV=prod uv run python run_mcp.py
```

Or register using `google_docs.mcp.json` — merge the `mcpServers` block. For manual config (e.g. Cursor), replace `${CLAUDE_PLUGIN_ROOT}` with the plugin root; Claude Code resolves it automatically.

## Tools

| Tool | Description |
| ---- | ----------- |
| `gdocs_list` | List docs in target folder |
| `gdocs_read` | Read doc content and tabs; inline images appear as `[image: <objectId>]` placeholders with an `inlineObjects` map of metadata (uri, width, height, description, title) |
| `gdocs_create` | Create doc with optional markdown |
| `gdocs_update` | Append markdown to doc |
| `gdocs_delete` | Trash doc |
| `gdocs_add_tab` | Add tab or sub-tab |
| `gdocs_rename_tab` | Rename an existing tab |
| `gdocs_clear_tab` | Clear all content from a tab, leaving the tab itself. Refuses if the tab holds embedded images (names their objectIds); pass `allow_image_destruction=True` to override |
| `gdocs_delete_tab` | Delete a tab |
| `gdocs_find_replace` | Replace text (optionally in a tab) |
| `gdocs_write_to_tab` | Insert markdown into a specific tab. Refuses if the tab holds embedded images (the clear+rebuild would destroy them, #311); pass `allow_image_destruction=True` to override |
| `gdocs_slides_create` | Create Google Slides presentation |
| `gdocs_slides_read` | Read a presentation's per-slide text (incl. tables + speaker notes). Accepts an ID or full Slides URL. See [Slides tools](#slides-tools) |
| `gdocs_slides_metadata` | Return a presentation's slide count + slide object IDs. See [Slides tools](#slides-tools) |
| `gdocs_slides_replace_text` | Replace all occurrences of text across a presentation (gated write). See [Slides tools](#slides-tools) |
| `gdocs_slides_copy_template` | Copy a Slides template deck to a new presentation (Drive `files.copy`, gated write). See [Slides tools](#slides-tools) |
| `gdocs_slides_replace_all_text` | Fill many `{{placeholders}}` from a mapping in one `batchUpdate` (gated write). See [Slides tools](#slides-tools) |
| `gdocs_slides_fill_table` | Write text into specific Slides table cells by (row, column) (gated write). See [Slides tools](#slides-tools) |
| `gdocs_slides_insert_image` | Insert an image from a URL onto a slide (`createImage`, gated write). See [Slides tools](#slides-tools) |
| `gsheets_read_values` | Read cell values from a Sheet range (`values.batchGet`). See [Sheets tools](#sheets-tools) |
| `gsheets_write_values` | Overwrite a range with values (`values.update`, gated write). See [Sheets tools](#sheets-tools) |
| `gsheets_append_rows` | Append rows after a table's last row (`values.append`, gated write). See [Sheets tools](#sheets-tools) |
| `gsheets_clear` | Clear the values in a range, keeping formatting (`values.clear`, gated write). See [Sheets tools](#sheets-tools) |
| `gsheets_format` | Apply raw `spreadsheets.batchUpdate` requests — formatting/structure (gated write). See [Sheets tools](#sheets-tools) |
| `gdocs_share` | Share doc with email |
| `gdocs_search` | Search text within doc |
| `gdocs_insert_person` | Insert person chip (@mention) |
| `gdocs_upload_image` | Upload local image to Drive (co-located with doc) and grant public read access |
| `gdocs_insert_image` | Insert inline image into a specific tab at a given index |
| `gdocs_lint` | Check a doc (or one tab) against the house style in `house_style.json`, in code. Returns a compact summary — `ok`, error/warning counts, `by_rule`, grouped violations with two short location samples — and never the doc content. See [House style lint](#house-style-lint) |
| `gdocs_get_image` | Fetch raw bytes of an inline image (base64 + mimeType). Discover objectIds via `gdocs_read` placeholders |

### Slides tools

These tools operate on Google **Slides** presentations (not Docs). They accept
either a raw presentation ID or a full Slides URL (e.g.
`https://docs.google.com/presentation/d/<ID>/edit`) and normalize it to the bare
ID before calling the Slides API. All require the Slides API to be enabled and
may fail otherwise.

Read/create (`tools_media.py`): `gdocs_slides_create`, `gdocs_slides_read`,
`gdocs_slides_metadata`, `gdocs_slides_replace_text`. Template-fill
(`tools_slides.py`, #196): `gdocs_slides_copy_template`,
`gdocs_slides_replace_all_text`, `gdocs_slides_fill_table`,
`gdocs_slides_insert_image`.

**Template-fill flow (data → customer-ready deck).** Google's guidance is to copy
a shared master template and edit the copy, never the master:

1. `gdocs_slides_copy_template(master_id, "Acme — Q3 Plan")` → new deck id
2. `gdocs_slides_replace_all_text(new_id, {"{{account}}": "Acme", "{{quarter}}": "Q3 FY26"})`
3. `gdocs_slides_fill_table(new_id, table_object_id, [{"row": 1, "column": 1, "text": "$1.2M"}])`
4. `gdocs_slides_insert_image(new_id, slide_object_id, image_url)`
5. `gdocs_slides_read(new_id)` to verify

Object IDs for tables and slides come from `gdocs_slides_read`
(`pageElementIds` per slide) and `gdocs_slides_metadata` (`slideObjectIds`).

#### `gdocs_slides_read`

Reads a presentation's per-slide text, walking shape text runs, table cells
(rendered tab-separated), and speaker-notes shapes. Returns JSON:

```json
{
  "presentationId": "<id>",
  "title": "<title>",
  "url": "https://docs.google.com/presentation/d/<id>/edit",
  "slideCount": 2,
  "slides": [
    {
      "objectId": "<slide object id>",
      "index": 0,
      "text": "<concatenated shape + table text>",
      "notes": "<speaker-notes text>",
      "pageElementIds": ["<page element object id>", "..."]
    }
  ]
}
```

On API error (e.g. a 404 for a missing presentation) the raw
`{"error": {...}}` envelope is returned unchanged, consistent with `gdocs_read`.
An empty or absent slides list yields an empty `slides` array and a
`slideCount` of `0`.

#### `gdocs_slides_metadata`

Returns just the presentation's slide count and the ordered list of slide
object IDs — a lightweight projection of the read response:

```json
{
  "presentationId": "<id>",
  "title": "<title>",
  "url": "https://docs.google.com/presentation/d/<id>/edit",
  "slideCount": 2,
  "slideObjectIds": ["slide_1", "slide_2"]
}
```

The underlying `{"error": {...}}` envelope is passed through on API error.

#### `gdocs_slides_replace_text`

Replaces all occurrences of `find` with `replace` across the presentation via a
single `replaceAllText` request through the Slides `presentations:batchUpdate`
endpoint. Parameters: `presentation_id`, `find`, `replace`, and `match_case`
(default `False`). This is a **gated write**: it is blocked in read-only mode
(`GDOCS_READ_ONLY=true`), subject to the folder allow-list, and appends an audit
log entry on success. Returns the raw Slides `batchUpdate` response JSON (whose
`replies` include `replaceAllText.occurrencesChanged`), or the `{"error": ...}`
envelope on failure.

#### `gdocs_slides_copy_template`

Copies a Slides master template to a brand-new deck via Drive `files.copy`, so
the master is never mutated — the template-fill entry point. Parameters:
`template_id` (raw ID or Slides URL of the master), `title` (new deck name), and
optional `folder_id` (destination; subject to the folder allow-list when set).
A **gated write**: blocked in read-only mode, audited on success. Returns
`{"status": "copied", "presentationId", "url"}` for the *new* deck, or
`{"error": ...}`.

#### `gdocs_slides_replace_all_text`

Fills many `{{placeholders}}` in one atomic `batchUpdate` — pass a `replacements`
mapping of literal find-strings (include the braces exactly as they appear in the
template) to their values, plus optional `match_case` (default `False`). Prefer
this over calling `gdocs_slides_replace_text` once per placeholder. A **gated
write**. Returns the raw Slides `batchUpdate` response (each reply carries an
`occurrencesChanged`; `0` means that key wasn't found), or `{"error": ...}`. An
empty mapping is rejected before any API call.

#### `gdocs_slides_fill_table`

Writes text into specific cells of an existing Slides table via `insertText`.
Parameters: `presentation_id`, `table_object_id` (from `gdocs_slides_read`'s
`pageElementIds`), `cells` (a list of `{"row", "column", "text"}`, 0-indexed),
and `clear_existing` (default `False`). Text is inserted at the start of each
cell; set `clear_existing=True` to delete a cell's current text first (deleting
an *already-empty* cell errors on the Slides API, so leave it `False` for empty
cells). For cells holding `{{placeholder}}` tokens, prefer
`gdocs_slides_replace_all_text`. A **gated write**. An empty `cells` list is
rejected before any API call.

#### `gdocs_slides_insert_image`

Inserts an image from a public URL onto a slide via `createImage`. Parameters:
`presentation_id`, `page_object_id` (the slide's objectId from
`gdocs_slides_metadata`), `image_url` (e.g. from `gdocs_upload_image`), and
optional sizing/positioning in points — `width_pt`/`height_pt` (pass both to
size) and `translate_x_pt`/`translate_y_pt` (top-left offset). A **gated write**.
Returns the raw Slides `batchUpdate` response (its reply carries the created
image's `objectId`), or `{"error": ...}`.

### Sheets tools

These five tools operate on Google **Sheets** spreadsheets (#197). They ride the
same authenticated client and `policy` gating as the Docs/Slides tools — Sheets
API v4 needs no new dependency and no separate credential store. Every
`spreadsheet_id` argument accepts a raw ID or a full Sheets URL
(`https://docs.google.com/spreadsheets/d/<ID>/edit`) and is normalized to the
bare ID. All ranges use **A1 notation**:

| Range | Meaning |
| ----- | ------- |
| `Sheet1!A1:C10` | a rectangular block |
| `Sheet1!A:A` | an entire column |
| `Sheet1!2:2` | an entire row |
| `'Q3 Data'!A1:B` | sheet name with a space (single-quote it) |
| `Sheet1` | the sheet's whole used range |

`gsheets_read_values` is ungated (like `gdocs_read`). The four write tools are
**gated writes**: blocked in read-only mode (`GDOCS_READ_ONLY=true`), subject to
the folder allow-list, and audited on success. `values` is a list of rows, each
a list of cells — `[["Name", "Score"], ["Ann", 91]]`.

#### `gsheets_read_values`

Reads a range via `spreadsheets.values.batchGet`. Pass several ranges
comma-separated (`"Sheet1!A1:B2,Sheet2!A1:A5"`) to read them in one call. Returns
the raw batchGet JSON (`valueRanges[].values`). Cells come back as strings;
empty trailing cells/rows are omitted by the API.

#### `gsheets_write_values`

Overwrites a range via `spreadsheets.values.update`. `range` anchors the
top-left; the block extends right/down to fit `values`. `value_input_option`
defaults to `USER_ENTERED` (inputs parse like the Sheets UI — `=SUM(A1:A2)`
becomes a formula, `5` a number); pass `RAW` to store inputs verbatim. Cells
outside the written block are left untouched — clear first with `gsheets_clear`
if needed.

#### `gsheets_append_rows`

Appends rows after a table's last row via `spreadsheets.values.append` with
`insertDataOption=INSERT_ROWS` (existing rows below shift down). `range`
identifies the table (typically the sheet name or its header). Same
`value_input_option` as `gsheets_write_values`.

#### `gsheets_clear`

Clears cell *values* in a range via `spreadsheets.values.clear`; formatting,
notes, and data validation are left intact. Returns `{spreadsheetId,
clearedRange}`.

#### `gsheets_format`

Raw passthrough to `spreadsheets.batchUpdate` — the escape hatch for everything
beyond cell values (formatting, add/delete sheets, merges, frozen rows,
conditional formats, column widths). `requests` is the list of Request objects,
sent verbatim as `{"requests": requests}`. Requests target sheets by numeric
`sheetId` (the gid, `0` for the first sheet), **not** by name, and use 0-based
half-open `GridRange`. Example — bold the header row:

```json
[{"repeatCell": {
    "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
    "cell": {"userEnteredFormat": {"textFormat": {"bold": true}}},
    "fields": "userEnteredFormat.textFormat.bold"}}]
```

The tool's decorated docstring carries more shapes (background color, freeze
row, auto-resize columns).

## House style lint

`house_style.json` is the single source of style values (#2001). The values come from the
owner's hand-built Jam Session template. Constructs the
template does not contain (tables, code) carry forward earlier validated decisions; each
section says which with `"source"`.

`style_lint.py` is pure code over a `documents.get?includeTabsContent=true` payload. For every
paragraph and text run it resolves the **effective** style — NORMAL_TEXT, then the paragraph's
named style, then explicit overrides, the same cascade Docs uses — and compares it to the spec.
So a doc passes whether its style comes from pinned named styles or from explicit values.

| Rule family | Checks |
| ----------- | ------ |
| `page.*` | Page size and margins |
| `named_style.*` | The doc's own NORMAL_TEXT / HEADING_1..6 / TITLE / SUBTITLE definitions (font, size, bold, colour, line spacing, space above/below) |
| `paragraph.*` | Effective line spacing, space above and space below of every paragraph, table cells included |
| `run.*` | Effective font family (house font or an allowed code font), size, heading bold, heading colour |
| `list.*` | Unordered glyph `-` (**warning**: the API cannot create dash lists) and the 36pt indent ladder with an 18pt hanging indent |
| `blank.*` | More than one consecutive blank paragraph, or a blank paragraph next to a heading. The tab-end anchor is ignored |
| `table.*` | Every cell vertically centred, bold header row, total width equal to the text width |

`ok` is false only on errors. Output is bounded (at most 10 groups, 2 samples each, locator
snippets of 24 characters), so an agent can gate on it without reading the doc back.

### Normalize, and the post-write gate

`style_normalize.py` turns a `documents.get` payload into the `batchUpdate` requests that bring
each tab to the spec. It is pure and returns requests in execution order:

1. `updateNamedStyle` (tab-scoped) for every named style that differs from the spec.
2. The linter's own traversal, run as if step 1 had already happened, so every remaining
   violation is an explicit override. Overrides are **reset** (field in the mask, value
   unset) so text inherits the pinned named style. List indents, table alignment, widths,
   header bold and page setup are set explicitly.
3. Extra blank paragraphs are deleted last, highest index first. Docs requires a paragraph
   before a table, so that one is kept. Under a heading, the heading's newline is deleted
   instead, which merges the heading onto it.

A clean tab produces no requests, so a second normalize is a no-op.

`style_gate.py` runs normalize and then lint after every successful `gdocs_create`,
`gdocs_update` (the first tab, where the append lands), `gdocs_add_tab` (the new tab) and
`gdocs_write_to_tab`. The result gains
`style: {ok, errors, warnings, by_rule, samples, normalized, tabId}`. If errors remain, the
status gets a `_but_style_check_failed` suffix and `error` is set; the content is still
written. `gdocs_find_replace` is not gated: `replaceAllText` keeps the replaced text's style,
and a doc-wide replace would otherwise restyle tabs the agent never wrote.

## Module Layout

The server is split into focused modules (restructured from the former
`gdocs_mvp.py` monolith in #318):

| Module | Responsibility |
| ------ | -------------- |
| `app.py` | The shared `FastMCP` instance both tool modules register on |
| `mcp_server.py` | Core CRUD + tab-lifecycle `@mcp.tool` surface; process entrypoint (`main`) |
| `tools_media.py` | Media/collab tools: slides (create/read/metadata/replace-text), share, search, person chip, image upload/insert |
| `tools_sheets.py` | Google Sheets `@mcp.tool` surface: `gsheets_read_values`/`write_values`/`append_rows`/`clear`/`format` (values.* + batchUpdate) |
| `tools_slides.py` | Slides template-fill `@mcp.tool` surface: `gdocs_slides_copy_template` (Drive copy) + `gdocs_slides_replace_all_text`/`fill_table`/`insert_image` (batchUpdate) |
| `sheets_ops.py` | `normalize_spreadsheet_id` (ID/URL) + `encode_range` (A1 path encoding) helpers used by the `gsheets_*` tools |
| `policy.py` | Read-only mode, folder allow-list, audit log, Docs-API error mapping |
| `docs_read.py` | `list_docs`, `read_doc`, `get_image_bytes` |
| `docs_write.py` | `create_doc`/`update_doc`/`delete_doc`, `add_tab`, `find_replace`, `clear_tab_content`, `write_to_tab` |
| `slides_read.py` | `read_presentation` / `normalize_presentation_id` — Slides read-path (shape/table/notes text extraction), used by the `gdocs_slides_*` tools |
| `markdown_render.py` | `_insert_markdown` — markdown AST → Docs `batchUpdate` requests |
| `markdown_inline.py` | Inline-token helpers (`_walk_inlines`, UTF-16 offsets, image detection) |
| `style_normalize.py` | `normalize_requests` — pure `documents.get` → `batchUpdate` requests that bring a tab to `house_style.json` |
| `style_gate.py` | Post-write gate: normalize the written tab, re-lint, attach the `style` summary / fail the result |
| `style_lint.py` | `lint_document` — house-style check over a `documents.get` payload, driven by `house_style.json` |
| `tabs.py` | The recursive `_find_tab_by_id` tab-tree lookup |
| `auth.py` | gcloud ADC token + `curl`/`urllib` HTTP primitives (`api`, `multipart_upload`, `_fetch_authed_bytes`) |
| `config.py` | Env-derived constants (`TARGET_FOLDER_ID`, `QUOTA_PROJECT`, bullet presets) |

### Extensions

Sheets support (#197) has landed as a **sibling tool module**, `tools_sheets.py`,
registered on the same `app.mcp` instance and reusing `auth`/`policy` — mirroring
how `tools_media.py` sits beside `mcp_server.py`. Its ID/URL + range-encoding
helpers live in `sheets_ops.py`, and the Docs code was left untouched. The tools
call the Sheets API v4 (`values.batchGet`/`update`/`append`/`clear` and
`spreadsheets.batchUpdate`) over the shared authenticated client — no new
dependency.

Slides support (#196) has landed in two layers. The **read/create** layer — the
read-path library `slides_read.py` plus the `gdocs_slides_read` /
`gdocs_slides_metadata` / `gdocs_slides_replace_text` tools and the minimal
`gdocs_slides_create` shim — is registered in `tools_media.py`. The
**template-fill** layer is a sibling module `tools_slides.py`, mirroring how
`tools_sheets.py` sits beside `tools_media.py`: `gdocs_slides_copy_template`
(Drive `files.copy` — never mutate the master) plus the batch-fill tools
`gdocs_slides_replace_all_text` / `gdocs_slides_fill_table` /
`gdocs_slides_insert_image`, all riding the same authenticated `auth`/`policy`
client (Slides v1 + Drive v3 — no new dependency). Together they cover the
"copy → replace placeholders → fill tables → insert images" motion an agent
needs to populate a customer deck from a template.

## Safety Controls

- **Read-only mode**: Set `GDOCS_READ_ONLY=true` to block all writes.
- **Folder allow-list**: Set `GDOCS_ALLOWED_FOLDERS=folder1,folder2` to restrict operations to those folders.
- **Audit log**: Set `GDOCS_AUDIT_LOG_PATH=/path/to/log` to append one line per mutation.

## Markdown Constructs Supported

`_insert_markdown` (used by `gdocs_create`, `gdocs_update`, `gdocs_add_tab`, `gdocs_write_to_tab`) supports:

| Construct | Rendering |
|-----------|-----------|
| ATX headings (`#`–`######`) | `HEADING_1`–`HEADING_6` paragraph style |
| `**bold**` | bold text style |
| `*italic*` / `_italic_` | italic text style |
| `` `inline code` `` | Courier New font |
| `[text](url)` | hyperlink (blue, underlined) |
| `` [`code`](url) `` | code hyperlink — blue + Courier New, **no** underline (underscores in code clash with it) |
| nested inline styles | styles nested inside links/bold/italic are preserved (e.g. `` **`code`** `` is bold monospace, `` [**`x`**](url) `` is a bold-mono link) |
| `- item` / `* item` (unordered list) | `BULLET_ARROW_DIAMOND_DISC` bullets (`➔ / ◆ / ●`), `NORMAL_TEXT` paragraph style, 36pt indent per level |
| `1. item` (ordered list) | `NUMBERED_DECIMAL_ALPHA_ROMAN` bullets, `NORMAL_TEXT` paragraph style |
| `` ``` `` fenced code blocks | Courier New font, no backtick markers |
| `> blockquote` | italic paragraph, 36pt indent, grey left border (Docs has no native blockquote) |
| `---` horizontal rule | line of `─` box-drawing characters |
| `\| H1 \| H2 \|` tables | real Docs table (`insertTable`), every cell vertically centred, columns split evenly across the destination's text width (`pageSize.width - marginLeft - marginRight`, `FIXED_WIDTH`), header row bolded + grey-tinted |

The renderer emits structure only: each paragraph sets just its named style, and spacing, fonts and sizes come from the named styles that the post-write normalize pass pins (#2001, see [House style lint](#house-style-lint)). Blank markdown lines survive as one empty paragraph between prose blocks, but never next to a heading, whose own space-above separates sections. There are no style presets and no per-call font/bullet knobs: one user, one house style.

**Dash (`-`) bullets are not reachable and never will be over `batchUpdate`.** Hand-typed tabs use dashes, but the API exposes no dash glyph: none of the 16 `BulletGlyphPreset` values renders `-`, `Bullet.listId` is read-only, and no request in the 40-request write surface defines a list glyph. The one mechanism that *does* inherit `-` — splitting a paragraph that already belongs to a dash list — needs a dash list inside the very paragraph being written, which a freshly added tab never has (list definitions are per-tab). The renderer therefore uses `BULLET_ARROW_DIAMOND_DISC` (`➔ / ◆ / ●`), the closest horizontally-oriented preset. Full probe record with exact requests and errors: `docs/research/2026-09-13-gdocs-dash-bullets.md` (#1770).

> **Note**: Tables use the documented two-phase `insertTable` → `documents.get` → reverse-order cell `insertText` pattern. Header row cells receive `updateTextStyle.bold` in the same batch as cell fills. Inline formatting inside cells (bold/italic/code/links, including nested styles such as a code link) is rendered via the same `_walk_inlines` path as body paragraphs.

## Test

```bash
uv run python -m unittest -v
```

Tests validate read-only blocking, allow-list behavior, audit log, and markdown rendering — without live Google API calls. As of #180 this mocked suite (`test_google_docs_mcp.py`) also runs as part of the repo gate (`make check`), so gdocs regressions fail the gate.

The Slides tools are covered by dedicated mocked suites: `test_slides_read.py`
(the `slides_read.py` read-path library — the URL/ID normalizer plus per-slide
text/table/notes extraction, patching the single `auth.api` point) and
`test_slides_tools.py` (the `gdocs_slides_read` / `gdocs_slides_metadata` /
`gdocs_slides_replace_text` MCP tools, patching `slides_read.read_presentation`
for reads and `policy.api` for the gated `replaceAllText` write — including its
read-only-mode rejection). Both run as part of the repo gate.

The Slides template-fill tools (#196) are covered by `test_slides_write_tools.py`
— every `tools_slides.py` tool (`gdocs_slides_copy_template`,
`gdocs_slides_replace_all_text`, `gdocs_slides_fill_table`,
`gdocs_slides_insert_image`): request shaping (method/URL/query/body) via the
single `policy.api` patch point, plus read-only and allow-list gating on the
writes. Fully mocked; runs in the gate.

The house style is covered by `test_style_lint.py` (each rule, output bounds, the
`gdocs_lint` tool), `test_style_normalize.py` (request shape, ranges and ordering for every
repair, over index-bearing synthetic payloads) and `test_style_gate.py` (normalize → re-lint
over a fake API, batching, failure envelopes, and which tools gate which tab). Fully
mocked; all run in the gate (`make verify-mcp-gstyle`).

The Sheets tools are covered by `test_google_sheets_mcp.py` — the `sheets_ops`
ID/URL normalizer + A1 range encoder, and every `gsheets_*` tool: request
shaping (method/URL/query/body) via the single `policy.api` patch point, plus
read-only and allow-list gating on the writes. Fully mocked; runs in the gate.

### Live integration tier (manual, never in the gate)

`live_test_rich_content.py` (#298) hits the real Docs/Drive APIs with your
gcloud ADC credentials: it auto-creates a scratch doc, runs the rich-content
round-trip (clear tab → nested list + table + inline image → `gdocs_read`
structure assertions, including content landing *after* the table/image),
verifies `gdocs_get_image` returns real fetchable bytes, exercises a nested
sub-tab write/read (recursive tab lookup + per-tab `inlineObjects` collection),
and trashes the scratch doc afterward. The `live_test_*.py` name keeps it out
of every automatic discovery path (the gate's explicit `-p` patterns, unittest's
`test*.py` default, pytest's `test_*.py` / `*_test.py`) — CI could not reach
Google anyway (workspace IP ACL). Run it manually:

```bash
uv run --with fastmcp --with mistune --with python-dotenv \
    python -m unittest live_test_rich_content -v
```
