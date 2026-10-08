# `rpw` — the one MCP entry for `rpw-published`

The plugin's `.mcp.json` declares only this server. It fronts every backend listed
in [`servers.json`](servers.json) (#2215), so harness configs, Codex tables and
permission allowlists name one server per plugin.

- **Add a server:** add its entry to `servers.json`, in the shape `.mcp.json` uses.
  Never add it to `.mcp.json`.
- **Tool names are not prefixed**, so in Claude Code a tool is
  `mcp__plugin_rpw-published_rpw__<tool>`.
- **Diagnose:** call the `rpw_backends` tool. It reports each backend as `ok`,
  `starting` or `failed`, with the reason. stderr carries one `[rpw-mcp]` line per backend.
- **Startup:** backends connect in parallel. Their tool lists are cached in
  `~/.cache/rpw-mcp/`, so after a backend's first successful start its tools are
  listed at once and calls wait for it. A backend never seen before holds the first
  list for at most `RPW_MCP_INITIAL_WAIT` seconds (default 25).
- **Without the plugin:** `uvx --from "git+https://github.com/randypitcherii/rpw-agent-marketplace#subdirectory=plugins/rpw-published" rpw-mcp`
  runs this same aggregator on any host with `uv` (#2242). The launcher copies the
  tree to `~/.cache/rpw-mcp/trees/` first, because uv will not sync a project inside
  its own cache.
- **One server from the shell:** `rpw-mcp-cli` reads `servers.json` and starts only
  the backend you call.

Behavior and the reasons for it: `lib/aggregator.py` (source: `libs/rpw_mcp_lib/lib/aggregator.py`).
