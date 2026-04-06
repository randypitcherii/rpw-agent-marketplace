---
name: mcp-env-setup
description: Use when MCP servers fail due to missing .env, authentication errors, or env var issues. Provides tips for MCP environment setup when .env may be missing or incomplete.
version: 1.0.0
---

# MCP Environment Setup

Tips for setting up MCP server environments when `.env` may be missing or incomplete.

## When to Use

- MCP server fails with auth/credential errors
- `.env` file is missing or not found
- User asks how to configure MCP servers
- Cursor/Claude Desktop reports MCP connection failures

## Setup Checklist

1. **Locate `.env.example`** — every MCP server in this repo ships one. Copy it:
   ```bash
   cp .env.example .env
   ```

2. **Fill required variables** — open `.env` and replace placeholders with real values. Never commit `.env`.

3. **Verify `.env` location** — `run_mcp.py` typically loads from the server directory. Ensure `.env` is in the same directory as `run_mcp.py` or that the launcher's working directory is correct.

4. **Check Cursor MCP config** — Cursor reads MCP config from settings. Ensure:
   - Paths use `${CLAUDE_PLUGIN_ROOT}` or equivalent so they resolve on the user's machine
   - No secrets in the config; credentials come from `.env` at runtime

5. **Test manually** — from the MCP server directory:
   ```bash
   uv run python run_mcp.py
   ```
   If it fails, the error usually indicates which env var is missing.

## Common Issues

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| "API key not found" | `.env` missing or wrong path | Copy `.env.example` to `.env`, fill values |
| "Invalid credentials" | Wrong or expired token | Re-auth (e.g. `sf org login web` for Salesforce, OAuth for Google) |
| "Module not found" | Dependencies not installed | `uv sync` in the MCP server directory |
| MCP shows "disconnected" | Config path wrong | Use `${CLAUDE_PLUGIN_ROOT}` placeholders |

## No Hardcoded Paths

Never hardcode machine-specific paths (e.g. `/Users/foo/...`) in MCP config. Use `${CLAUDE_PLUGIN_ROOT}` or env-driven placeholders so configs work across machines.
