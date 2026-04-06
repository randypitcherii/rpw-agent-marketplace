# MCP Live Integration Tests & Dynamic Credential Pipeline

## Problem

All rpw MCP servers fail silently at startup. Existing tests only validate file structure — no test verifies a server can start, authenticate, or call a tool. Credentials are managed via static `.env` files that go stale.

## Goals

1. Dynamic credential resolution — eliminate static `.env` dependency for servers with programmatic auth
2. Live integration tests that fail hard when credentials are missing or broken
3. Tests exercise real tool calls (read + write with cleanup) against live services

## Credential Pipeline

### Layered Resolver

Extend `plugins/rpw-working/mcp-servers/lib/env_loader.py` (and rpw-building's copy) with a credential resolver chain. Each server declares its source type; the resolver populates `os.environ` before the MCP server launches.

**Resolution order per source type:**

| Source Type | Resolution | Servers |
|---|---|---|
| `uc_connection` | Fetch access_token from Databricks UC connection API → map to expected env var name | slack, glean, jira |
| `gcloud_adc` | Read `~/.config/gcloud/application_default_credentials.json` → extract client_id, client_secret, refresh_token | google, google-tasks, google-docs-with-subtabs |
| `env_file` | Existing behavior — load from `{APP_ENV}.env` | gemini-image |

No fallback chain. Each server declares exactly one source type. If resolution fails, crash with a clear error message.

### UC Connection Resolver

```
databricks api get /api/2.1/unity-catalog/connections/<name>/user-credentials/<user_id> --profile logfood
```

- Extract `access_token` from response
- Map to server's expected env var (e.g., `access_token` → `SLACK_BOT_TOKEN`)
- Fail if connection state is not `ACTIVE`
- User ID obtained from `databricks current-user me --profile logfood`

**Env var mapping:**

| UC Connection | Env Var |
|---|---|
| `slack` | `SLACK_BOT_TOKEN` |
| `glean-mcp` | `GLEAN_API_TOKEN` |
| `jira-mcp` | `JIRA_API_TOKEN` |

### gcloud ADC Resolver

- Read `~/.config/gcloud/application_default_credentials.json`
- Map: `client_id` → `GOOGLE_CLIENT_ID`, `client_secret` → `GOOGLE_CLIENT_SECRET`, `refresh_token` → `GOOGLE_REFRESH_TOKEN`
- Fail if file missing or fields absent

### Wrapper Changes

Each `run_mcp.py` changes from:

```python
REQUIRED = ["SLACK_BOT_TOKEN"]
load_selected_env(BASE_DIR)
missing = validate_required_env(REQUIRED)
```

To:

```python
CREDENTIAL_SOURCE = "uc_connection"
CREDENTIAL_CONFIG = {
    "connection_name": "slack",
    "env_var_map": {"access_token": "SLACK_BOT_TOKEN"},
}
resolve_credentials(CREDENTIAL_SOURCE, CREDENTIAL_CONFIG, BASE_DIR)
```

The `resolve_credentials` function lives in `lib/env_loader.py` and dispatches to the appropriate resolver. After resolution, it runs the existing `validate_required_env()` check to confirm all vars are set.

## Integration Tests

### Structure

```
tests/
  integration/
    __init__.py
    conftest.py              # shared MCP client helpers, credential checks
    test_slack_mcp.py
    test_glean_mcp.py
    test_jira_mcp.py
    test_google_mcp.py
    test_google_tasks_mcp.py
    test_google_docs_mcp.py
    test_gemini_image_mcp.py
```

### Test Pattern (per server)

Each test module:

1. **`test_server_starts`** — Launch server as subprocess, send JSON-RPC `initialize` + `tools/list`, assert tools returned
2. **`test_read_operation`** — Call a read-only tool, assert valid response
3. **`test_write_operation`** — Call a write tool, assert success, clean up in teardown

### Test Operations Per Server

| Server | Read Test | Write Test | Cleanup |
|---|---|---|---|
| slack | List channels | Post message to a DM-to-self channel | Delete the message |
| glean | Search for "databricks" | _(read-only only — no write API)_ | N/A |
| jira | List projects | Create a ticket in a personal/test project | Delete the ticket |
| google | List recent Drive files | Create a test doc named `_mcp_integration_test_<timestamp>` | Delete the doc |
| google-tasks | List task lists | Create a task in default list | Delete the task |
| google-docs-with-subtabs | List recent docs | Create a test doc | Delete the doc |
| gemini-image | _(no read-only tool)_ | Generate a small test image | Delete output file |

### Shared Test Infrastructure (`conftest.py`)

- `McpTestClient` class — starts MCP server subprocess, sends JSON-RPC messages over stdio, collects responses
- `resolve_test_credentials(source_type, config)` — same resolver used by production wrappers, ensures tests use identical credential path
- Fixtures for server lifecycle (start in setup, kill in teardown)
- Hard failure (not skip) when credentials unavailable

### Test Execution

```bash
# Run all integration tests
make test-integration

# Run specific server
uv run python -m pytest tests/integration/test_slack_mcp.py -v
```

Add `test-integration` target to Makefile.

### CI Behavior

- Tests **fail** (not skip) when credentials are missing
- This is intentional — broken auth is a broken deployment

## Files Modified

| File | Change |
|---|---|
| `plugins/rpw-working/mcp-servers/lib/env_loader.py` | Add `resolve_credentials()`, UC resolver, gcloud ADC resolver |
| `plugins/rpw-working/mcp-servers/*/run_mcp.py` | Switch to `resolve_credentials()` with declared source type |
| `tests/integration/*.py` | New — live integration tests per server |
| `tests/integration/conftest.py` | New — shared MCP test client and fixtures |
| `Makefile` | Add `test-integration` target |

## Out of Scope

- Removing PEX approach (coming soon, separate work)
- rpw-building MCP servers (cmux, chrome-devtools, exa) — different credential patterns
- Token caching/pooling — UC tokens are fetched fresh each startup for now
