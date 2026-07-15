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

3. **Authenticate**:

   ```bash
   gcloud auth application-default login \
     --scopes=https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/presentations,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/userinfo.email
   ```

   The `spreadsheets` scope powers the Sheets tools (#197). The broader `drive`
   scope already covers the Sheets API for most grants, so an existing token may
   keep working — but a narrowly-scoped grant (or one predating #197) needs this
   re-auth. Re-running `application-default login` **replaces** the ADC scope set,
   so include the full list above (dropping a scope silently breaks the tools that
   need it — see #74).

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
| `tabs.py` | The recursive `_find_tab_by_id` tab-tree lookup |
| `auth.py` | gcloud ADC token + `curl`/`urllib` HTTP primitives (`api`, `multipart_upload`, `_fetch_authed_bytes`) |
| `config.py` | Env-derived constants (`TARGET_FOLDER_ID`, `QUOTA_PROJECT`, bullet presets) |
| `cli.py` | Standalone CLI (`create`/`list`/`read`/`update`/`delete`/`add-tab`) |

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
| `- item` / `* item` (unordered list) | `BULLET_DISC_CIRCLE_SQUARE` bullets by default; override per-call via `gdocs_write_to_tab(..., bullet_preset=...)`. `NORMAL_TEXT` paragraph style |
| `1. item` (ordered list) | `NUMBERED_DECIMAL_ALPHA_ROMAN` bullets, `NORMAL_TEXT` paragraph style |
| `` ``` `` fenced code blocks | Courier New font, no backtick markers |
| `> blockquote` | italic paragraph (Docs has no native blockquote) |
| `---` horizontal rule | line of `─` box-drawing characters |
| `\| H1 \| H2 \|` tables | real Docs table (`insertTable`), header row bolded |

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

The Sheets tools are covered by `test_google_sheets_mcp.py` — the `sheets_ops`
ID/URL normalizer + A1 range encoder, and every `gsheets_*` tool: request
shaping (method/URL/query/body) via the single `policy.api` patch point, plus
read-only and allow-list gating on the writes. Fully mocked; runs in the gate.
