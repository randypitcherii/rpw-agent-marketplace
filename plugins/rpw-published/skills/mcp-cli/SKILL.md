---
name: mcp-cli
description: Call any installed RPW MCP server from the shell with `rpw mcp`, the one shell surface over them all. Use in Pi, Codex, or any harness without native MCP tools, or when a task chains calls or bulk-edits Google Docs/Sheets/Slides or Slack. Trigger on "use an MCP tool from pi", "list my MCP tools", "call MCP from the shell", "gdocs-cli", "slack-cli", or "script this doc edit".
---

# RPW MCP CLI

Call the MCP servers shipped by the installed RPW plugins from a harness with `bash`
but no native MCP client. The wrapper drives a pinned
[mcporter](https://github.com/openclaw/mcporter) (Node 24+), whose daemon keeps each
real server warm and shares it with the `rpw` MCP entry: a warm call takes ~1s.

## Invoke

Use `rpw mcp` (Claude Code puts the plugin's `bin/rpw` on `PATH`). Without
`rpw`, run the `rpw-mcp-cli` launcher next to this `SKILL.md`, same arguments:

```bash
rpw mcp servers
rpw mcp tools exa
rpw mcp call exa <tool-from-schema> \
  --json '{"query":"Qwen model release timeline"}'
```

Never guess a tool name or its arguments. Follow **servers → tools → call**. The
`tools` result includes each tool's `inputSchema`. `rpw-private` servers appear only
when that plugin is installed.

Long or quote-heavy string values go in a file: `--arg-file content=body.md`
(repeatable; `--json` defaults to `{}`).

## Common routes

- Public web research: discover `exa`, inspect its tools, then call the matching
  search/fetch tool.
- Jira, Google, and other services: discover the server and inspect its
  live schema before invoking it.
- Composition (read → transform → write, bulk edits): chain calls in one shell
  call. Recipe, result unwrapping, and `--arg-file` detail:
  [references/composition.md](references/composition.md).

Prefer service-specific skills when one exists; they carry domain and safety
rules this generic bridge cannot infer. Before any write or send, show the user
what will go out and get an explicit yes. The bridge does not ask for you.

A server that requires its own confirmation refuses with an `ok: false` envelope
naming a `<NAME>_SEND_CONFIRM` opt-out. Re-run with it only after the user approves;
the server receives it (the CLI forwards an allowlisted env that includes it).

## Output and composition

This bridge implements the house CLI output contract:
`docs/process/cli-output-contract.md` in `rpw-agent-marketplace`.

Output is the full MCP result (`.result`; a tool's own JSON is the string at
`.result.structuredContent.result`). Pipe it through `jq` when only a few fields are
useful so large intermediate payloads stay out of model context. The default inline ceiling is
8 KiB. Above that, the wrapper returns a bounded preview plus an owner-only
`full` path (aliased `output_file`) holding the complete response. Read or filter
that file instead of printing it wholesale. A failing call reports the first 40
lines of the failure inline, so no second read is needed. Override only when needed:

```bash
rpw mcp --max-bytes 100000 call ...   # a bigger cap
rpw mcp --full call ...               # no cap, no spill file
```

A server's first call starts it (seconds); later calls reuse it. Calls wait up to
120s (`--timeout SECONDS`): [references/timeouts.md](references/timeouts.md).

## Authentication and recovery

The wrapper writes no credentials. Installed servers continue to resolve their
existing `~/.claude/mcp-servers/<server>/dev.env` pointers.

- Missing plugin cache: install/update the RPW plugins, or set
  `RPW_MCP_CACHE_ROOT` to a test/custom plugin-cache root.
- Missing Node: install Node 24+ (`brew install node`); mcporter installs itself.
- Expired Databricks profile: run `databricks auth login --profile <profile>`.
- Missing per-user OAuth: open the connection URL reported by the server and
  complete browser consent.
- Server/tool error: preserve its stderr and report the server, tool, and
  remediation; never call its upstream API directly.
