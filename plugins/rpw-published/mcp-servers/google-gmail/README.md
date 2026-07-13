# Gmail MCP Server

FastMCP server for the Gmail v1 API, proxied through a Databricks Unity Catalog HTTP-proxy connection (`http_request` external function). No raw OAuth tokens live on disk — credentials are resolved at runtime via the UC proxy.

This server owns the Gmail surface only. Drive (including the `about` identity endpoint), Calendar, Tasks, and Docs each have their own dedicated server.

## Setup

1. **Change to this server directory and create env files from `template.env`**:

   ```bash
   cd mcp-servers/google-gmail
   cp template.env dev.env
   cp template.env test.env
   cp template.env prod.env
   ```

   Required variables (populated by the `/mcp-setup` skill, or set manually):
   - `UC_PROXY_CONNECTION_NAME` (your Google UC HTTP-proxy connection name)
   - `UC_PROXY_PROFILE` (Databricks CLI profile name)

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

The server runs over stdio. Register in your MCP client using `google_gmail.mcp.json` — merge the `mcpServers` block.

## Test

```bash
uv run python -m unittest test_run_mcp_env -v
```

## Tools

| Tool | Description |
| ---- | ----------- |
| `google_gmail_search` | Search Gmail messages with Gmail search syntax |
| `google_gmail_get_message` | Get a Gmail message by ID (metadata / full / minimal / raw) |
| `google_gmail_send` | Send an email (supports cc/bcc) |
