# Google Tasks MCP Server

MCP server for Google Tasks with **assigned-task visibility** (`showAssigned=true`). Exposes tools for listing task lists, listing tasks (including those assigned from Docs/Chat Spaces), and CRUD operations.

## Setup

1. **Change to this server directory and create env files from `template.env`**:

   ```bash
   cd mcp-servers/google-tasks
   cp template.env dev.env
   cp template.env test.env
   cp template.env prod.env
   ```

   Required variables:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REFRESH_TOKEN`

2. **Install dependencies** (uv, Python 3.12+):

   ```bash
   uv sync
   ```

  If your default Python is <3.12: `uv sync --python 3.12`

## Run

From this directory (defaults to `APP_ENV=dev`):

```bash
uv run python run_mcp.py
```

To run another environment:

```bash
APP_ENV=test uv run python run_mcp.py
APP_ENV=prod uv run python run_mcp.py
```

The server runs over stdio. Register in your MCP client using `google_tasks.mcp.json` — merge the `mcpServers` block. For manual config (e.g. Cursor), replace `${CLAUDE_PLUGIN_ROOT}` with the plugin root; Claude Code resolves it automatically.

## Test

```bash
uv run python test_google_tasks.py
```

- **Unit test**: Asserts that `gtasks_list_tasks` passes `showAssigned=True` to the Tasks API (mocked).
- **Connectivity test**: Validates credentials and API reach (skips if env vars are missing).

## Tools

| Tool | Description |
| ---- | ----------- |
| `gtasks_list_tasklists` | List all task lists |
| `gtasks_list_tasks` | List tasks in a list (**showAssigned=true** for assigned-task visibility) |
| `gtasks_create_task` | Create a task (or subtask) |
| `gtasks_update_task` | Update task title, notes, or due date |
| `gtasks_complete_task` | Mark a task as completed |
| `gtasks_delete_task` | Delete a task |

## showAssigned Behavior

By default, the Google Tasks API does **not** return tasks assigned to you from Google Docs or Chat Spaces. This server sets `showAssigned=true` on every `tasks.list` call so assigned tasks are included in results.
