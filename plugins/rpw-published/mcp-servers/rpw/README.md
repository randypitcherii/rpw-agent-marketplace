# `rpw` — the one MCP entry across the rpw plugins

`rpw-published`'s `.mcp.json` declares only this server, and `rpw-private` declares
none. It fronts every backend in every installed plugin's
[`servers.json`](servers.json) through [mcporter](https://github.com/openclaw/mcporter)'s
per-user keep-alive daemon (#2623, ADR-2026-10-28), so harness configs, Codex tables
and permission allowlists name one server.

- **Add a server:** add its entry to the plugin's `servers.json`, in the shape
  `.mcp.json` uses. Never add it to `.mcp.json`.
- **Tool names are not prefixed**, so in Claude Code a tool is
  `mcp__plugin_rpw-published_rpw__<tool>`.
- **Needs Node 24+.** The pinned mcporter installs itself once under
  `~/.rpw/mcp/runtime/`; the generated config is `~/.rpw/mcp/mcporter.json`.
- **Diagnose:** call the `rpw_backends` tool. It reports each backend as `ok`,
  `starting` or `failed`, with the reason. stderr carries `[rpw-mcp]` lines.
  `mcporter daemon status` (with the same config) shows the warm connections.
- **Startup:** tool lists are cached in `~/.cache/rpw-mcp/`, so the first `tools/list`
  answers at once and a background refresh lists every backend in parallel. A backend
  never seen before holds the first list for at most `RPW_MCP_INITIAL_WAIT` seconds
  (default 25).
- **Without the plugin:** `uvx --from "git+https://github.com/randypitcherii/rpw-agent-marketplace#subdirectory=plugins/rpw-published" rpw-mcp`
  runs this same front (#2242). The launcher copies the tree to
  `~/.cache/rpw-mcp/trees/` first, because uv will not sync a project inside its own
  cache.
- **From the shell:** `rpw mcp` (or the `mcp-cli` skill's launcher) calls the same warm backends.

Behavior and the reasons for it: [`front.py`](front.py) and
[`mcp_runtime.py`](mcp_runtime.py).
