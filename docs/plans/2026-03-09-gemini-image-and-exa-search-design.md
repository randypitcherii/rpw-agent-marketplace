# Design: Gemini Image Gen + Exa Search MCP Tools

**Date**: 2026-03-09
**Plugin**: rpw-building

## Goal

Add image generation and improved web/code search to Claude Code sessions via MCP servers in the rpw-building plugin.

## Components

### 1. Gemini Image Gen MCP Server (custom)

**Location**: `plugins/rpw-building/mcp-servers/gemini-image/`

**Tools**:
- `generate_image` — text prompt → image saved to disk, returns file path
- `edit_image` — image path + text instruction → edited image saved to disk

**API**: Google `google-genai` SDK, Gemini native image generation
- Default model: `gemini-2.5-flash-image` (GA/stable)
- Auth: `GEMINI_API_KEY` env var
- Uses `generate_content()` with `response_modalities=["IMAGE"]`

**Dependencies**: `google-genai`, `fastmcp>=3.0.0`, `python-dotenv>=1.2.1`

**Env pattern**: `template.env` checked in, `dev.env` gitignored, loaded via shared `env_loader.py`

### 2. Exa Search (config-only, hosted MCP)

**Config**: Add to `plugins/rpw-building/plugin.json` mcpServers

**Endpoint**: `https://mcp.exa.ai/mcp?tools=web_search_advanced_exa,code_search_exa`

**Tools provided**:
- `web_search_advanced_exa` — semantic web search
- `code_search_exa` — search open source code, docs, examples

**No API key required.** Free hosted MCP server.

## Decisions

- **Nano Banana over Imagen 4**: supports editing + generation, same API surface, GA model available
- **Exa over Perplexity**: no double-LLM tax, free, has code search
- **Gemini Grounded Search skipped**: can't be called standalone, requires Gemini model call
- **rpw-building for both**: dev-focused tools belong with dev plugin

## Out of Scope

- Imagen 4 batch endpoint
- Perplexity integration
- Gemini text/chat tools
