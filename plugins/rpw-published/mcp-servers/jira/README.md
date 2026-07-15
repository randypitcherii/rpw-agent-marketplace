# Jira MCP Server

FastMCP server for the Jira REST v3 API, proxied through a Databricks Unity Catalog HTTP-proxy connection (`http_request` external function). No raw Jira API token lives on disk — credentials are resolved at runtime via the UC proxy.

This server owns the Jira surface only.

## Setup

1. **Change to this server directory and create env files from `template.env`**:

   ```bash
   cd mcp-servers/jira
   cp template.env dev.env
   cp template.env test.env
   cp template.env prod.env
   ```

   Fill in the placeholders (populated by the `/mcp-setup` skill, or set manually):
   - `UC_CONNECTION_NAME` — your Jira UC HTTP-proxy connection name
   - `DATABRICKS_PROFILE` — the Databricks CLI profile that can reach it

   `uc_proxy` validates access to the connection and exports `UC_PROXY_CONNECTION_NAME` / `UC_PROXY_PROFILE` at startup; alternatively set those two directly in the env file.

2. **Install dependencies** (uv, Python 3.10+):

   ```bash
   uv sync
   ```

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

The server runs over stdio. Register in your MCP client using `jira.mcp.json` — merge the `mcpServers` block.

## Test

```bash
uv run python -m unittest test_run_mcp_env -v
```

## Tools

| Tool | Description |
| ---- | ----------- |
| `jira_search` | Search Jira issues with JQL |
| `jira_get_issue` | Get a Jira issue by key (e.g. `ABC-123`) |
| `jira_create_issue` | Create a new issue (plain-text description, auto-wrapped in ADF) |
| `jira_add_comment` | Add a comment to an issue (plain text, auto-wrapped in ADF) |
| `jira_get_transitions` | List available transitions for an issue |
| `jira_transition_issue` | Transition an issue to a new state |
| `jira_list_projects` | List all projects the user can access |
| `jira_api_request` | Escape hatch — call any Jira REST v3 endpoint |
