# Testing MCP Servers Locally — Approaches & Commands

Research date: 2026-03-10. Applies to FastMCP v3+, stdio transport, Claude Code plugins.

---

## 1. FastMCP CLI — `fastmcp dev inspector` (RECOMMENDED for interactive UI)

FastMCP v3 bundles a `dev inspector` subcommand that launches the official MCP Inspector web UI pointed at your server. No separate install needed.

```bash
# Launch inspector for a server file (opens browser UI)
fastmcp dev inspector plugins/rpw-building/mcp-servers/gemini-image/run_mcp.py

# With env vars and project deps
APP_ENV=dev fastmcp dev inspector \
  --project plugins/rpw-building/mcp-servers/gemini-image \
  plugins/rpw-building/mcp-servers/gemini-image/run_mcp.py

# Factory function pattern
fastmcp dev inspector server.py:create_server
```

**What you get:** Browser-based UI with tabs for Tools, Resources, Prompts. Fill in tool arguments in a form, click execute, see JSON results. Logs and notifications in a sidebar.

| Pros | Cons |
|------|------|
| Full interactive web UI | Requires Node.js (npx runs under the hood) |
| Zero config — just point at your .py file | `run_mcp.py` uses `if __name__` block which fastmcp ignores — use factory function or import pattern |
| Shows tool schemas, descriptions, metadata | |

**Gotcha for this repo:** The `run_mcp.py` files use `if __name__ == "__main__"` which `fastmcp run`/`dev` ignores. You'd need to either:
- Point at the `mcp_server.py` directly if it exposes a `FastMCP` instance at module level
- Or create a factory function entrypoint

---

## 2. FastMCP CLI — `fastmcp inspect` (quick smoke test)

Non-interactive. Loads the server and reports what it exposes — tool count, resource count, metadata. Good for CI or quick validation.

```bash
# Human-readable summary
fastmcp inspect plugins/rpw-building/mcp-servers/gemini-image/mcp_server.py

# Full JSON with tool schemas
fastmcp inspect plugins/rpw-building/mcp-servers/gemini-image/mcp_server.py --format fastmcp

# Low-level MCP protocol JSON
fastmcp inspect plugins/rpw-building/mcp-servers/gemini-image/mcp_server.py --format mcp
```

| Pros | Cons |
|------|------|
| Instant, no browser needed | Read-only — can't call tools |
| Good for CI checks ("does this server have 3 tools?") | |
| JSON output for scripting | |

---

## 3. FastMCP CLI — `fastmcp client` (call tools from terminal)

New in v3. CLI-based MCP client that connects to a server and lets you list/call tools directly from the command line.

```bash
# List all tools
fastmcp client list-tools plugins/rpw-building/mcp-servers/gemini-image/mcp_server.py

# Call a specific tool with arguments
fastmcp client call-tool plugins/rpw-building/mcp-servers/gemini-image/mcp_server.py \
  generate_image --arg prompt="a cat in a spacesuit"

# Complex JSON arguments
fastmcp client call-tool server.py my_tool --json-arg config='{"key": "value"}'

# Machine-readable JSON output
fastmcp client list-tools server.py --format json
fastmcp client call-tool server.py my_tool --format json --arg x=1
```

| Pros | Cons |
|------|------|
| Fastest way to call a single tool and see output | No UI — pure CLI |
| Scriptable, good for smoke tests | Must know exact tool names and arg shapes |
| No browser or Node.js needed | |

---

## 4. MCP Inspector (standalone) — `npx @modelcontextprotocol/inspector`

The official MCP Inspector from Anthropic. Same UI that `fastmcp dev inspector` wraps, but you invoke it directly. Useful if you're not using FastMCP or want more control.

```bash
# For a uv-managed Python server (matches your .mcp.json pattern)
npx @modelcontextprotocol/inspector \
  uv run --project plugins/rpw-building/mcp-servers/gemini-image \
  python plugins/rpw-building/mcp-servers/gemini-image/run_mcp.py

# Generic stdio server
npx @modelcontextprotocol/inspector <command> [args...]

# With environment variables (set in the UI's "Server connection pane")
```

Opens a web UI at `http://localhost:5173` (default) with:
- **Server connection pane** — configure transport, command, args, env vars
- **Tools tab** — list tools, see schemas, fill forms, execute, see results
- **Resources tab** — browse and read resources
- **Prompts tab** — test prompt templates
- **Notifications pane** — server logs and notifications

| Pros | Cons |
|------|------|
| Official tool, works with any MCP server (not just FastMCP) | Requires Node.js / npx |
| Full interactive web UI | Slightly more verbose command than `fastmcp dev inspector` |
| Can set env vars in the UI | |

---

## 5. Claude Code — `claude mcp add` (test as an actual MCP client)

Add a local MCP server directly to Claude Code without installing the full plugin. This tests the server in its real runtime context — Claude's LLM actually calls the tools.

```bash
# Add a local stdio server (session/project scope)
claude mcp add gemini-image-test \
  -s project \
  -- uv run --project ./plugins/rpw-building/mcp-servers/gemini-image \
  python ./plugins/rpw-building/mcp-servers/gemini-image/run_mcp.py

# Verify it's registered
claude mcp list

# Remove when done
claude mcp remove gemini-image-test

# Use -e for env vars
claude mcp add my-server -e API_KEY=xxx -- uv run python server.py
```

Then start a Claude Code session and ask Claude to use the tools. You'll see tool calls in the conversation.

| Pros | Cons |
|------|------|
| Tests the full plugin experience (LLM picks tools, formats args) | Not deterministic — LLM decides when/how to call tools |
| Catches real integration issues (env vars, paths, permissions) | Uses API credits |
| No code changes needed | Can't test specific edge cases reliably |

**Scopes:** `-s user` (all projects), `-s project` (this project only, saved to `.claude/settings.json`)

---

## 6. Claude Desktop — `claude_desktop_config.json`

Add the server to Claude Desktop's config for GUI-based testing with Claude's chat interface.

```bash
# Open/create the config file
# macOS: ~/Library/Application Support/Claude/claude_desktop_config.json

# Add your server entry:
```

```json
{
  "mcpServers": {
    "gemini-image-test": {
      "command": "uv",
      "args": [
        "run", "--project",
        "/absolute/path/to/plugins/rpw-building/mcp-servers/gemini-image",
        "python",
        "/absolute/path/to/plugins/rpw-building/mcp-servers/gemini-image/run_mcp.py"
      ],
      "env": {
        "APP_ENV": "dev"
      }
    }
  }
}
```

After editing, restart Claude Desktop. Use Command-R to reload after server code changes.

Debug logs: `tail -n 20 -F ~/Library/Logs/Claude/mcp*.log`

Enable DevTools: `echo '{"allowDevTools": true}' > ~/Library/Application\ Support/Claude/developer_settings.json` then Command-Option-Shift-i.

| Pros | Cons |
|------|------|
| Full GUI chat experience | Must restart Desktop on config changes |
| Good for demoing to stakeholders | Requires absolute paths (no ${CLAUDE_PLUGIN_ROOT}) |
| Can inspect via DevTools | Same LLM-nondeterminism issue as Claude Code |

---

## 7. Python REPL — `fastmcp.Client` (programmatic, scriptable)

Import the server directly in Python and call tools with the FastMCP Client. Best for automated tests and precise input/output validation.

```python
import asyncio
from fastmcp import Client, FastMCP

# Option A: In-memory (import server object directly)
from mcp_server import mcp  # your FastMCP instance
client = Client(mcp)

async def test():
    async with client:
        # List tools
        tools = await client.list_tools()
        for t in tools:
            print(f"  {t.name}: {t.description}")

        # Call a tool
        result = await client.call_tool("generate_image", {"prompt": "a cat"})
        print(result.data)

asyncio.run(test())

# Option B: Subprocess/stdio (matches production behavior)
client = Client("path/to/mcp_server.py")

# Option C: With env vars for subprocess
from fastmcp.client.transports import StdioTransport
transport = StdioTransport(
    command="uv",
    args=["run", "--project", ".", "python", "run_mcp.py"],
    env={"APP_ENV": "dev", "GEMINI_API_KEY": "..."}
)
client = Client(transport=transport)
```

| Pros | Cons |
|------|------|
| Fully deterministic — exact inputs, assert on outputs | No UI |
| In-memory option is fastest (no subprocess) | Requires writing async Python |
| Perfect for unit/integration tests | In-memory skips env loading in run_mcp.py |
| Can test error cases, edge cases precisely | |

---

## Summary: Which approach when?

| Scenario | Best approach |
|----------|--------------|
| "Does my server even start? What tools does it expose?" | `fastmcp inspect` |
| "Let me manually poke at tools in a browser" | `fastmcp dev inspector` or `npx @modelcontextprotocol/inspector` |
| "Quick CLI smoke test of one tool" | `fastmcp client call-tool` |
| "Test the full LLM integration before merging" | `claude mcp add` (Claude Code) |
| "Automated test suite" | Python `fastmcp.Client` with in-memory transport |
| "Demo to someone non-technical" | Claude Desktop |

## Recommended pre-merge review workflow

1. **`fastmcp inspect server.py`** — verify tool count, names, schemas (5 seconds)
2. **`fastmcp client call-tool server.py <tool> --arg ...`** — call each tool once, verify output shape (30 seconds per tool)
3. **`fastmcp dev inspector server.py`** — open browser, test edge cases interactively (2-5 minutes)
4. **`claude mcp add`** — optional, test real LLM integration in a Claude Code session
