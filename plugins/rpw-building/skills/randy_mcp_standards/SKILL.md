---
name: randy_mcp_standards
description: Use when creating or modifying MCP servers in this repo. Enforces secret-free configs, uv/uvx entrypoints, and .env.example patterns.
version: 1.0.0
---

# Randy MCP Standards

Required standards for any MCP server in the `rpw-building` plugin and this repository. Apply when adding new servers or updating existing ones.

## Hard Rules

1. **Always include a sample MCP config JSON** — every server must ship a copy-pasteable config example.
2. **Never embed secrets in MCP config JSON** — no API keys, tokens, or credentials in config files.
3. **Use uvx/uv run as entrypoint** — secrets are loaded dynamically from `.env` at runtime by `run_mcp.py` or equivalent launcher.
4. **Never commit `.env`** — ensure `.gitignore` includes `.env` and `**/.env`.
5. **Provide `.env.example`** — document required env vars with placeholder values (no real secrets).
6. **Use server sample file naming** — `<server>.mcp.json` (e.g. `google_tasks.mcp.json`, `google_docs_with_subtabs.mcp.json`).
7. **plugin-root `.mcp.json`** — every plugin must ship a root `.mcp.json` at the repo/plugin root that wires all MCP servers.
8. **Use `${CLAUDE_PLUGIN_ROOT}` for paths** — MCP config args must use `${CLAUDE_PLUGIN_ROOT}` placeholders (not machine-specific absolute paths) for Claude portability.

## Per-Server Required Files

| File | Purpose |
| --- | --- |
| `run_mcp.py` | Loads `.env`, validates required vars, execs the MCP server with enriched env |
| `.env.example` | Template listing required variables (e.g. `GOOGLE_CLIENT_ID=`, `GOOGLE_CLIENT_SECRET=`) |
| `<server>.mcp.json` | Sample config for Claude Desktop / Cursor; command/args only, no secrets |
| `pyproject.toml` | Project metadata and dependencies |

## Sample MCP Config Pattern

```json
{
  "_comment": "Sample config for <server>. Merge into your MCP client config. No secrets.",
  "mcpServers": {
    "<server-name>": {
      "command": "uv",
      "args": ["run", "--project", "${CLAUDE_PLUGIN_ROOT}/mcp-servers/<server>", "python", "${CLAUDE_PLUGIN_ROOT}/mcp-servers/<server>/run_mcp.py"]
    }
  }
}
```

- Use `uv run` for local development; `uvx` for published packages.
- Paths in args must use `${CLAUDE_PLUGIN_ROOT}` placeholders for Claude portability.
- Auth/credentials come from `.env` loaded by `run_mcp.py`.

## Cursor Follow-on Config Generation

When generating MCP config for Cursor, derive from the plugin-root `.mcp.json` and `${CLAUDE_PLUGIN_ROOT}` pattern. Cursor reads MCP config from its settings; ensure generated config uses the same portable path placeholders so it works across machines.

## .gitignore Checklist

Ensure the repo `.gitignore` contains:

```text
.env
**/.env
```
