---
name: mcp-standards
description: Use when creating or modifying MCP servers in this repo. Enforces secret-free configs, uv/uvx entrypoints, and the APP_ENV / template.env credential-loading pattern.
---

# MCP Standards

Required standards for any MCP server in the `rpw-published` and `rpw-private` plugins and this repository. Apply when adding new servers or updating existing ones.

## Hard Rules

1. **Always include a sample MCP config JSON** — every server must ship a copy-pasteable config example.
2. **Never embed secrets in MCP config JSON** — no API keys, tokens, or credentials in config files.
3. **Use uvx/uv run as entrypoint** — credentials are loaded dynamically at runtime by `run_mcp.py` (via the shared `lib.launcher` / `lib.env_loader`), never baked into config.
4. **Follow the APP_ENV / `template.env` convention** — commit a placeholder `template.env`; the launcher selects `<APP_ENV>.env` (`dev`/`test`/`prod`, default `dev`) at startup, checking the server dir first, then the stable user path `~/.claude/mcp-servers/<server-dir-name>/<APP_ENV>.env`. Mechanics live in the `env-preferences` skill — defer to it rather than restating.
5. **Never commit real env files** — `.gitignore` must exclude `dev.env`/`test.env`/`prod.env` (and the legacy `.env`). Only `template.env`, with placeholders and no real secrets, is committed.
6. **Use server sample file naming** — `<server>.mcp.json` (e.g. `google_tasks.mcp.json`, `google_docs.mcp.json`).
7. **plugin-root `.mcp.json`** — every plugin must ship a root `.mcp.json` at the repo/plugin root that wires all MCP servers.
8. **Use `${CLAUDE_PLUGIN_ROOT}` for paths** — MCP config args must use `${CLAUDE_PLUGIN_ROOT}` placeholders (not machine-specific absolute paths) for Claude portability.

## Per-Server Required Files

| File | Purpose |
| --- | --- |
| `run_mcp.py` | Thin launcher: declares this server's `REQUIRED` vars / hint and calls `lib.launcher.run(...)`, which loads the selected `<APP_ENV>.env`, validates required vars, runs an optional credential precheck, then execs the server's `main()` |
| `template.env` | Committed placeholder listing required/optional variables (e.g. `CREDENTIAL_SOURCE=`, `GDOCS_QUOTA_PROJECT=your-gcp-project-id`) — copied to `dev.env`/`test.env`/`prod.env` locally |
| `<server>.mcp.json` | Sample config for Claude Desktop / Cursor; command/args only, no secrets |
| `pyproject.toml` | Project metadata and dependencies |

## `run_mcp.py` — declaration + one launcher call

APP_ENV-selected env loading, required-var validation, and the actionable missing-var
stderr hint are shared in `mcp-servers/lib/launcher.py` (which delegates file resolution
to `lib/env_loader.py`). Each server's `run_mcp.py` is just a declaration plus one
`launcher.run(...)` call — no per-server boilerplate:

```python
import sys
from pathlib import Path

# Allow imports from the parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import launcher

REQUIRED = ["UC_PROXY_CONNECTION_NAME", "UC_PROXY_PROFILE"]
MISSING_HINT = "Set CREDENTIAL_SOURCE=uc_proxy with ... or set the vars directly."


def main() -> None:
    launcher.run(Path(__file__).parent, required=REQUIRED, missing_hint=MISSING_HINT)


if __name__ == "__main__":
    main()
```

`launcher.run(base_dir, *, required=None, missing_hint=None, precheck=None, server_module="mcp_server")`:
- `required` — env vars that must be set; missing ones abort with exit 1.
- `missing_hint` — a str, or a callable of the resolved `app_env` (e.g. imessage's
  "copy template.env to `<env>`.env"), appended after the missing-vars list.
- `precheck` — an optional `(env_name, app_env) -> error | None` for auth checks that
  aren't a simple env-var presence test (e.g. gemini-image's gcloud ADC probe).

The lib ships **duplicated** into both `plugins/rpw-published/mcp-servers/lib/` and
`plugins/rpw-private/mcp-servers/lib/` (kept byte-identical by a repo-validation test).
It is intentionally *not* extracted to repo-root `libs/`: the plugin cache and the
public mirror ship only the plugin dir, so a repo-root path dependency would not
resolve at runtime. See ADR-2026-06-22.

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
- Auth/credentials come from the selected `<APP_ENV>.env` loaded by `run_mcp.py` (see the `env-preferences` and `mcp-setup` skills).

## Cursor Follow-on Config Generation

When generating MCP config for Cursor, derive from the plugin-root `.mcp.json` and `${CLAUDE_PLUGIN_ROOT}` pattern. Cursor reads MCP config from its settings; ensure generated config uses the same portable path placeholders so it works across machines.

## Databricks UC connections as a credential source

When a new MCP server needs to call an upstream service (Slack, Glean, Jira, Google, etc.) that's reachable through a Databricks Unity Catalog connection on the user's workspace, **prefer the HTTP-proxy flavor of the UC connection** and have your FastMCP tools call the upstream's REST API directly against `<workspace>/api/2.0/unity-catalog/connections/<name>/proxy/` with REST verbs. Don't route through `uc-mcp-proxy` unless you're explicitly falling back to a hosted, MCP-native UC connection because no custom implementation exists yet.

Rationale: the wire surface our server exposes is what we test and what the user runs. Routing through a hosted MCP-native proxy means the user gets whatever Databricks' hosted proxy exposes — schemas, tool names, error semantics may differ from ours.

See the `databricks-uc-connections` skill for the classifier (`options.is_mcp_connection == "true"`), the naming-trap table (`-mcp`-named connections are mostly HTTP-proxy), and the decision flow for which connection name to point at.

## Stale-auth handling (expired keys / revoked tokens)

Credentials expire mid-workflow (an API key is rotated, a gcloud ADC session
lapses, a Databricks OAuth token is revoked). Left unhandled, the provider's raw
error leaks straight to the agent (issue #195: the gemini-image tool surfaced
`400 INVALID_ARGUMENT ... API key expired`). Every server that calls an upstream
must instead detect stale auth, return a consistent actionable envelope, and stop
re-hitting the provider once the connection is known stale.

Use `lib/stale_auth.py` — do **not** hand-roll per-server string matching:

- `looks_like_stale_auth(text)` — classifies the common Gemini / Google-OAuth /
  Databricks expiry+invalid-credential signatures (reuses the Databricks markers
  from `lib.errors`). Extend the marker list there if a new provider needs it, so
  every server benefits and stays consistent.
- `StaleAuthError` — the normalized envelope: `as_dict()` yields
  `{error: "stale_auth", provider, message, next_action, short_circuited, detail}`;
  `as_message()` renders it as a JSON string for tools that return text.
- `StaleAuthGuard(provider=..., remediation=...)` — a process-local latch. Create
  one module-level guard per credential, then wrap each tool:

```python
from lib.stale_auth import StaleAuthGuard

_STALE_AUTH = StaleAuthGuard(
    provider="vertex-ai",
    remediation="Re-authenticate: gcloud auth application-default login",
)

@mcp.tool()
def my_tool(...):
    stale = _STALE_AUTH.short_circuit()          # 1. known stale? return now, no provider call
    if stale is not None:
        return stale.as_message()
    try:
        ...                                       # real provider call
    except Exception as e:
        stale = _STALE_AUTH.classify(e)          # 2. stale? latch + normalized envelope
        if stale is not None:
            return stale.as_message()
        return f"Error: {e}"                     # non-auth errors flow through unchanged
```

The `remediation` must be the *exact next action* for that server's auth mode
(the login command, or the Databricks UI URL for a UC connection). **Reset:** the
latch has no time expiry — it clears on `reset()` or a process restart, and a
restart re-reads the `<APP_ENV>.env`/ADC where refreshed credentials land, so
bouncing the MCP server is the normal recovery. Cover detection, the normalized
shape, and the short-circuit with fully-mocked regression tests (see
gemini-image's `test_stale_auth.py`).

## .gitignore Checklist

Real env files hold resolved credentials and must never be committed — only the
placeholder `template.env` is. Ensure the repo `.gitignore` contains the per-env
files (and the legacy `.env`, retained for older layouts):

```text
.env
**/.env
dev.env
test.env
prod.env
**/dev.env
**/test.env
**/prod.env
```
