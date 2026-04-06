# Google Docs with Subtabs MCP Server

MCP server for Google Docs CRUD, tabs, find/replace, tab-targeted write, and advanced operations. Uses gcloud ADC auth and enforces read-only mode, folder allow-list, and audit logging.

## Setup

1. **Install dependencies** (uv):

   ```bash
   cd mcp-servers/google-docs-with-subtabs
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
   gcloud auth application-default login
   ```

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

Or register using `google_docs_with_subtabs.mcp.json` — merge the `mcpServers` block. For manual config (e.g. Cursor), replace `${CLAUDE_PLUGIN_ROOT}` with the plugin root; Claude Code resolves it automatically.

## Tools

| Tool | Description |
| ---- | ----------- |
| `gdocs_list` | List docs in target folder |
| `gdocs_read` | Read doc content and tabs |
| `gdocs_create` | Create doc with optional markdown |
| `gdocs_update` | Append markdown to doc |
| `gdocs_delete` | Trash doc |
| `gdocs_add_tab` | Add tab or sub-tab |
| `gdocs_find_replace` | Replace text (optionally in a tab) |
| `gdocs_write_to_tab` | Insert markdown into a specific tab |
| `gdocs_slides_create` | Create Google Slides presentation |
| `gdocs_share` | Share doc with email |
| `gdocs_search` | Search text within doc |
| `gdocs_insert_person` | Insert person chip (@mention) |

## Safety Controls

- **Read-only mode**: Set `GDOCS_READ_ONLY=true` to block all writes.
- **Folder allow-list**: Set `GDOCS_ALLOWED_FOLDERS=folder1,folder2` to restrict operations to those folders.
- **Audit log**: Set `GDOCS_AUDIT_LOG_PATH=/path/to/log` to append one line per mutation.

## Test

```bash
uv run python -m unittest -v
```

Tests validate read-only blocking, allow-list behavior, and audit log without live Google API calls.
