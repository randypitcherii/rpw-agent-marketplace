---
name: mcp-setup
description: End-to-end MCP server setup — diagnoses servers, bootstraps gcloud + databricks CLIs, authenticates both the UC-connections workspace and the user's own secrets workspace, and writes reference-based config that resolves credentials at startup. No secrets stored on disk unless the user explicitly opts out of Databricks.
---

# MCP Setup

Unified setup for all MCP servers in this marketplace. Configures credentials once and leaves no secrets on disk by default — per-server `dev.env` files hold pointers to Databricks UC connections, Databricks secrets scopes, or gcloud ADC, and `env_loader.py` resolves them fresh at every server startup.

## Credential source priority

For each server the skill tries these in order, using the first that's available:

1. **UC connection** (shared, org-managed) — preferred when the server has a matching UC connection in the user's UC-connections workspace.
2. **Databricks secrets** (personal) — per-user secret scope in the user's own Databricks workspace. Scope name: `<user>_rpw_mcp` where `<user>` is derived from the user's Databricks email (local-part, dots→underscores).
3. **Manual env file** (last-resort) — user puts literal values in `dev.env`. Only used when the user explicitly declines Databricks.

The authoritative mapping lives in `server_registry.py`. Each server declares an ordered `sources` list. Adding a new server: update that file.

## Shared user-level config

Workspace URLs, profile names, and the derived scope prefix are stored once at:

```
~/.claude/mcp-servers/.shared.env
```

Example:
```
UC_CONNECTIONS_WORKSPACE_PROFILE=<your-uc-connections-profile>
DATABRICKS_SECRETS_WORKSPACE_PROFILE=DEFAULT
SCOPE_PREFIX=<your-secret-scope-prefix>
```

`env_loader.py` loads this first (before any per-server `dev.env`), so these values are available as env vars to every server subprocess.

## Per-server `dev.env` shapes

All written to `~/.claude/mcp-servers/<server>/<app_env>.env` — stable across plugin version bumps.

**uc_connection** (fetches field values from UC connection user-credentials — only works for connection types that expose tokens):
```
APP_ENV=dev
CREDENTIAL_SOURCE=uc_connection
DATABRICKS_PROFILE=<your-databricks-profile>
UC_CONNECTION_NAME=<name>
UC_FIELD_MAP=field_name:ENV_VAR
```

**uc_proxy** (server uses Databricks SDK to proxy API calls through UC; no tokens extracted):
```
APP_ENV=dev
CREDENTIAL_SOURCE=uc_proxy
DATABRICKS_PROFILE=<your-databricks-profile>
UC_CONNECTION_NAME=slack
```

**databricks_secrets:**
```
APP_ENV=dev
CREDENTIAL_SOURCE=databricks_secrets
DATABRICKS_PROFILE=DEFAULT
DATABRICKS_SECRET_SCOPE=<your-scope-prefix>_rpw_mcp
DATABRICKS_SECRET_MAP=slack_bot_token:SLACK_BOT_TOKEN
```

**gcloud_adc:** maps ADC fields to env vars; empty map = no-op (ADC used at runtime).
```
APP_ENV=dev
CREDENTIAL_SOURCE=gcloud_adc
GCLOUD_FIELD_MAP=client_id:GOOGLE_CLIENT_ID,refresh_token:GOOGLE_REFRESH_TOKEN
```

**manual (no CREDENTIAL_SOURCE):**
```
APP_ENV=dev
EXA_API_KEY=xoxb-...
```

## Flow

### 1. Diagnose

Run `claude mcp list`. Each plugin-hosted line is `plugin:<plugin>:<server>: <command> - <status>` where status is `✓ Connected` or `✗ Failed to connect`. Ignore `claude.ai <Name>:` lines (remote SaaS MCPs, not our concern) and `!` statuses. Strip `plugin:<plugin>:` to get short server names. Show a status table to the user. If all rpw servers are ✓ Connected, tell the user and exit. If the user's invocation says "diagnose only" or similar, stop here regardless.

### 2. Check toolchain

Required: `gcloud`, `databricks`. For each missing, ask whether to install via AskUserQuestion:

- gcloud: `brew install google-cloud-sdk`
- databricks: `brew tap databricks/tap && brew install databricks`

If the user declines a tool, skip servers that depend on it. Make skips explicit in the final report.

### 3. Authenticate gcloud

Check `gcloud auth application-default print-access-token 2>&1`. If it fails, confirm with the user and run `gcloud auth application-default login` (opens browser).

### 4. Bootstrap shared Databricks config

Read `~/.claude/mcp-servers/.shared.env` if it exists. For any of `UC_CONNECTIONS_WORKSPACE_PROFILE`, `DATABRICKS_SECRETS_WORKSPACE_PROFILE`, or `SCOPE_PREFIX` that's missing:

- Run `databricks auth profiles` (skip the header row; each data row is `<name> <host> <valid>`). Show the user the available profiles.
- Ask via AskUserQuestion: "Which profile hosts your UC connections?" and "Which profile hosts your personal secrets?" Offer profile names as options plus "Enter a new workspace URL" plus "I don't use Databricks for this".
  - If they pick an existing profile, validate with `databricks auth env --profile <name>`; re-auth if expired.
  - If they enter a URL, run `databricks auth login --host <url> --profile <derived-name>` and persist.
  - If they decline both, skip to the manual .env flow for every server.
- Once a profile is picked for `DATABRICKS_SECRETS_WORKSPACE_PROFILE`, derive `SCOPE_PREFIX` by running `databricks current-user me --profile <secrets-profile>`, reading `userName`, taking the local-part (before `@`), lowercasing, replacing dots with underscores. Example: `jane.doe@example.com` → `jane_doe`.
- Write all three values to `~/.claude/mcp-servers/.shared.env` (create parent dir with `mkdir -p` first).

### 5. Discover available credentials

Before any discovery command, re-check tokens: for `<uc-profile>` and `<secrets-profile>`, run `databricks auth env --profile <p> 2>&1`. If output contains `invalid`/`not found`/`expired`/`Refresh token is invalid`, re-auth with `databricks auth login --profile <p>` (confirm with user; opens browser).

> The MCP servers also self-diagnose expired tokens at startup. If a user sees `❌ Auth expired for Databricks profile 'X' — run: databricks auth login --profile X` in `claude mcp list`, that single command fixes every UC-proxy server (CLI token is cached centrally). No need to re-run `/mcp-setup` for token expiry.

For the UC workspace: `databricks connections list --profile <uc-profile> --output json` → list of connections.
For the secrets workspace: `databricks secrets list-scopes --profile <secrets-profile> --output json` → list of scopes. Confirm `<SCOPE_PREFIX>_rpw_mcp` exists. If not, ask the user whether to skip the secrets fallback or create the scope (`databricks secrets create-scope <name> --profile <p>`).

### 6. Pick the source per server and write dev.env

> When picking a UC connection name, see the `databricks-uc-connections` skill — UC connections have two wire-protocol flavors and the `-mcp` suffix is unreliable.

For each server in `server_registry.py`:

1. Walk its `sources` list in order.
2. For a `uc_connection` source: is its `connection_name` in the UC workspace's list? If yes, select it.
3. For a `uc_proxy` source: is its `connection_name` in the UC workspace's list AND does the user have USE_CONNECTION privilege (confirmed by a successful `databricks api get /api/2.1/unity-catalog/connections/<name> --profile <uc-profile>`)? If yes, select it.
4. For a `databricks_secrets` source: are all keys in `secret_map` present under `<SCOPE_PREFIX>_rpw_mcp`? Run `databricks secrets list-secrets <scope> --profile <p> --output json` and check. If yes, select it.
5. For a `gcloud_adc` source: is gcloud ADC authed? If yes, select it.
6. If nothing resolves, ask the user whether to skip this server or use manual .env (prompt for each required env var from the server's `REQUIRED` list).

Compose the dev.env contents per the "Per-server dev.env shapes" section above (using the `extra_env_prompts` values if present). Run `mkdir -p ~/.claude/mcp-servers/<server>` and write `<app_env>.env`. Before overwriting an existing file, show a diff and ask to confirm.

### 7. Validate

Discover the installed plugin path:

```bash
ls -d ~/.claude/plugins/cache/rpw-agent-marketplace/rpw-{published,private}/*/mcp-servers/ 2>&1 | tail -2
```

MCP servers live under two plugin caches (`rpw-published`, `rpw-private`). If neither path ends in `/mcp-servers/`, the plugins aren't installed — report that and stop. Otherwise, for each configured server:

```bash
SERVER_DIR="<discovered-path>/<server>"
(cd "$SERVER_DIR" && timeout 3 uv run python run_mcp.py 2>&1 | head -20)
```

Success = no `❌`, `RuntimeError`, `FileNotFoundError`, or `EnvironmentError` before the timeout. Failure = any of those appearing. Collect results. Print the final status table. Suggest restarting Claude Code so MCP servers pick up the new config.

## Final status table format

```
MCP Setup Results
═════════════════

Toolchain:
  ✓ gcloud CLI (<version>)
  ✓ databricks CLI (<version>)

Workspaces:
  ✓ UC connections  — profile '<uc-profile>' @ <host>
  ✓ Personal secrets — profile '<secrets-profile>' @ <host>, scope '<scope>'

Server Setup:
  ✓ slack                    (uc_proxy: slack)
  ✓ glean                    (uc_proxy: system_ai_agent_glean_mcp)
  ✓ gemini-image             (gcloud_adc: Vertex AI via ADC)
  ✓ google-tasks             (gcloud_adc)
  ⚠ jira                     (no source resolved — manual .env written)
  ...

Next steps:
  • Restart Claude Code to pick up new config
  • <any skipped servers / known issues>
```

## Troubleshooting

Servers self-diagnose. Their stderr (visible in `claude mcp list` and via `timeout 3 uv run python run_mcp.py 2>&1`) names the cause and the exact fix command. Common cases:

- **`❌ Auth expired for Databricks profile 'X' — run: databricks auth login --profile X`** — one re-auth fixes every UC-proxy server. Don't re-run `/mcp-setup`.
- **`❌ Cannot access UC connection 'X' ...`** — missing USE_CONNECTION privilege or wrong name. Verify in Databricks UI or update `server_registry.py`.
- **`{"code": 32600, "message": "Session terminated"}` from `uc-mcp-proxy`** — pointing it at an HTTP-proxy UC connection (not MCP-native). Classify via the `databricks-uc-connections` skill and re-point or rewrite the server to call REST directly.
- **`❌ Field 'X' not found in UC connection 'Y'. Available fields: [...]`** — `server_registry.py` field_map doesn't match the UC options. Update the registry.
- **`❌ Databricks secret scope 'X' does not exist — run: databricks secrets create-scope X --profile Y`** — create the scope or skip the source.
- **`❌ Failed to fetch secret 'X' from scope 'Y' ...`** — key missing. `databricks secrets put-secret <scope> <key> --profile <p>` or skip.
- **`❌ gcloud ADC not found ... — run: gcloud auth application-default login`** — user did `gcloud auth login` (workspace) instead of `application-default`. Run the suggested command.

## Notes

- No secrets are written to disk unless the user explicitly chooses manual .env. If you see a literal API key in a generated dev.env, that's a bug — report it.
- Running the skill twice is safe. It detects healthy servers and skips them.
- `chrome-devtools` needs no setup. `exa` is registered as a URL-based MCP in `rpw-published`'s `.mcp.json` (`https://mcp.exa.ai/mcp`) and needs no credentials — the free tier covers ~1000 requests/month. See #46 if the URL entry isn't registering in `claude mcp list`.
- All rpw servers are native FastMCP — no PEX binaries needed. `slack`, `jira`, and `google` proxy through Databricks UC connections (`slack`, `jira-mcp`, `google-mcp`); the rest use other credential sources per `server_registry.py`.

## Verifying this skill works

After any change to the skill or registry, verify manually — each check names what must hold:

1. `claude mcp list` — lists current server status (the baseline).
2. `/mcp-setup --diagnose-only` — status table matches (1); modifies no file.
3. `/mcp-setup` — walks all steps to completion, or reports what's blocking.
4. `claude mcp list` — all rpw servers show ✓ Connected.
