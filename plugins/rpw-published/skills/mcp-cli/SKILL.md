---
name: mcp-cli
description: Call any installed RPW MCP server from the shell through the generic rpw MCP CLI, the one shell surface over them all. Use in Pi, Codex, or any harness without native MCP tools, or when a task chains calls or bulk-edits Google Docs/Sheets/Slides or Slack. Trigger on "use an MCP tool from pi", "list my MCP tools", "call MCP from the shell", "gdocs-cli", "slack-cli", or "script this doc edit".
---

# RPW MCP CLI

Use the MCP implementations already shipped by the installed RPW plugins from a
harness that has `bash` but no native MCP client. The wrapper starts the real MCP
server, so its auth, policy, schemas, and implementation remain authoritative.

## Invoke

Resolve the executable `rpw-mcp-cli` relative to this `SKILL.md`, then run it directly:

```bash
MCP_CLI="<this-skill-directory>/rpw-mcp-cli"
"$MCP_CLI" servers
"$MCP_CLI" tools exa
"$MCP_CLI" call exa <tool-from-schema> \
  --json '{"query":"Qwen model release timeline"}'
```

Never guess a tool name or its arguments. Follow **servers → tools → call**. The
`tools` result includes each tool's `inputSchema`. If the same short server name
exists in two plugins, use the qualified name reported by the command.

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
rules this generic bridge cannot infer. Before any write or send, load and follow
that service's skill and obtain whatever confirmation it requires.

Outbound tools are gated in the server. A refusal is an `ok: false` envelope
(e.g. `send_not_confirmed`) with a preview. Show it to the user, and only after
they approve re-run with the opt-out it names (e.g. `SLACK_SEND_CONFIRM=0 "$MCP_CLI"
call ...`). Only `*_SEND_CONFIRM` variables are forwarded to the server.

## Output and composition

This bridge implements the house CLI output contract:
`docs/process/cli-output-contract.md` in `rpw-agent-marketplace`.

Output is JSON. Pipe it through `jq` when only a few fields are useful so large
intermediate payloads stay out of model context. The default inline ceiling is
8 KiB. Above that, the wrapper returns a bounded preview plus an owner-only
`full` path (aliased `output_file`) holding the complete response. Read or filter
that file instead of printing it wholesale. A failing call reports the first 40
lines of the failure inline, so no second read is needed. Override only when needed:

```bash
"$MCP_CLI" --max-bytes 100000 call ...   # a bigger cap
"$MCP_CLI" --full call ...               # no cap, no spill file
```

Each invocation cold-starts the selected MCP server and can take several seconds; combine downstream filtering in the same shell call where useful.

## Authentication and recovery

The wrapper writes no credentials. Installed servers continue to resolve their
existing `~/.claude/mcp-servers/<server>/dev.env` pointers.

- Missing plugin cache: install/update the RPW plugins, or set
  `RPW_MCP_CACHE_ROOT` to a test/custom plugin-cache root.
- Missing `mcp-inspector`: run
  `npm install -g @modelcontextprotocol/inspector`, then retry.
- Expired Databricks profile: run `databricks auth login --profile <profile>`.
- Missing per-user OAuth: open the connection URL reported by the server and
  complete browser consent.
- Server/tool error: preserve its stderr and report the selected server, tool,
  and remediation; do not bypass the server by calling its upstream API directly.
