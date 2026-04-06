# Slack MCP: Direct UC Connection vs PEX Wrapper

**Date:** 2026-03-03
**Author:** Randy Pitcher (with AI assist)

## Background

The current Slack MCP setup uses a PEX wrapper (`slack_mcp_deploy.pex`) that runs as a local stdio MCP server. We investigated whether it's feasible to bypass this wrapper and connect directly to the Slack MCP through the Databricks Unity Catalog connection.

## Architecture of the Current PEX Wrapper

The PEX wrapper (`/Users/randy.pitcher/mcp/servers/slack_mcp/slack_mcp_deploy.pex`) does the following:

1. **Runs as a stdio MCP server** — Raycast connects via stdin/stdout
2. **Authenticates to Azure Databricks** (`adb-2548836972759138.18.azuredatabricks.net`) via OAuth U2M browser flow
3. **Proxies Slack API calls** through `ws.serving_endpoints.http_request(conn='slack', ...)` — the SDK's `POST /api/2.0/external-function` endpoint
4. **Routes all read responses** through `internal-safe-proxy.prod.databricks-corp.com` for privacy summarization/redaction (~7-10s per call)
5. **Defines its own MCP tool schemas** — it IS the MCP server, not a passthrough to a remote one

## Key Findings

### 1. The UC `slack` connection is NOT a remote MCP server
The UC connection (`connection_type: SLACK`) points to `https://slack.com/api` — the **Slack REST API**, not an MCP endpoint. The Databricks MCP proxy at `/api/2.0/mcp/external/slack` tries to forward MCP JSON-RPC to Slack's REST API, which doesn't understand it. The PEX wrapper implements MCP server logic locally and uses the UC connection **only for credential storage/token exchange**.

### 2. Two workspaces, different token states
- **AI DevTools** (`dbc-a5d4177a-49dc.cloud.databricks.com`) — Slack refresh token is **expired/invalid**. All calls return `invalid_refresh_token`.
- **Logfood** (`adb-2548836972759138.18.azuredatabricks.net`) — Slack refresh token is **valid**. The PEX wrapper authenticates here.

### 3. The SDK method that makes it work
```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod

ws = WorkspaceClient(profile="Logfood")
response = ws.serving_endpoints.http_request(
    conn="slack",
    method=ExternalFunctionRequestHttpMethod.GET,
    path="auth.test",
    headers={"Accept": "application/json"},
)
# Returns: {"ok":true, "user":"randy.pitcher", "team":"Databricks", ...}
```
This calls `POST /api/2.0/external-function` which handles the OAuth token exchange transparently. We never see the raw Slack token.

### 4. What the PEX wrapper adds (and costs)
| Feature | Wrapper Provides | Cost |
|---|---|---|
| Privacy summarization | Redacts sensitive content via `internal-safe-proxy` | 7-10s latency per read call |
| Tool curation | Curated subset of Slack API as MCP tools | Limits available operations |
| Caching | `use_cache`, `analysis_prompt`, `bash_query` params | Complexity |
| Attribution footer | Auto-appends "Sent with Slack MCP" to messages | Can't disable easily |
| Batch operations | `slack_batch_read_api_call` / `slack_batch_write_api_call` | N/A |

### 5. Available UC MCP connections (AI DevTools workspace)
| Connection | Type | Auth | Owner |
|---|---|---|---|
| confluence-mcp | HTTP | OAuth U2M | qiaochu.yang |
| glean-mcp | HTTP | OAuth U2M | qiaochu.yang |
| google-docs-mcp | HTTP | OAuth U2M | mark.tai |
| google-mcp | HTTP | OAuth U2M | mark.tai |
| google-sheets-mcp | HTTP | OAuth U2M | mark.tai |
| jira-mcp | HTTP | OAuth U2M | qiaochu.yang |
| pagerduty-mcp | HTTP | OAuth U2M | qiaochu.yang |
| slack | SLACK | OAuth U2M | darming.zhao |

### 6. Slack OAuth scopes on the UC connection
```
channels:write groups:write im:write mpim:write chat:write
channels:read groups:read channels:history groups:history
im:history mpim:history users:read users:read.email
files:read im:read mpim:read search:read
```

## Options

### Option A: Thin FastMCP wrapper over UC connection (recommended)
Same pattern as the `google-tasks` MCP server in `rpw-agent-marketplace`. Build a FastMCP server that:
1. Authenticates to the Logfood workspace via `WorkspaceClient(profile="Logfood")`
2. Proxies Slack API calls through `ws.serving_endpoints.http_request(conn="slack", ...)`
3. Exposes MCP tools that mirror the official Slack MCP server's tools

**Pros:**
- No raw tokens to manage — UC handles refresh automatically
- No privacy layer overhead (skip the 7-10s summarization latency)
- Full control over tool definitions and behavior
- Same auth model, just thinner

**Cons:**
- Still a custom wrapper (just much thinner)
- Every call routes through Databricks → Slack (extra hop)
- Tied to the Logfood workspace profile

**Reference implementation:** `rpw-agent-marketplace/plugins/rpw-working/mcp-servers/google-tasks/`

### Option B: Extract token from UC, pass to official Slack MCP server
The official `@modelcontextprotocol/server-slack` just needs `SLACK_BOT_TOKEN` (xoxb-) and `SLACK_TEAM_ID`. If we could extract the raw token:

```json
{
  "mcpServers": {
    "slack": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-slack"],
      "env": {
        "SLACK_BOT_TOKEN": "<extracted-from-UC>",
        "SLACK_TEAM_ID": "T02EPKPG3"
      }
    }
  }
}
```

**Problem:** The UC proxy never exposes the raw Slack token. The `POST /api/2.0/external-function` endpoint handles auth transparently and only returns the Slack API response body. There's no SDK method to retrieve the raw `xoxp-` token.

**Possible workaround:** Write a bootstrap script that:
1. Calls `ws.serving_endpoints.http_request(conn='slack', path='auth.test')` to verify the connection
2. Intercepts the token at the HTTP level (e.g., monkey-patch the SDK's HTTP client)
3. Passes the extracted token to the official Slack MCP server as an env var

**Pros:**
- Uses the battle-tested official Slack MCP server
- Direct Slack API calls (no Databricks hop)
- More tools out of the box (reactions, user profiles, etc.)

**Cons:**
- Token extraction is hacky and fragile
- Token expires (~10.5 hours) — need refresh logic
- May violate UC security model intentions

### Option C: Re-authorize the AI DevTools workspace and use the Databricks MCP proxy directly
The `/api/2.0/mcp/external/slack` endpoint on the AWS workspace would work if the Slack refresh token were valid. Re-consent through the Databricks UI (Agents > MCP Servers > Slack) to fix the `invalid_refresh_token` error.

**Problem:** The `SLACK` connection type doesn't expose an MCP server — it proxies raw REST API calls. The Databricks MCP proxy forwards MCP JSON-RPC to `https://slack.com/api`, which doesn't understand MCP protocol. This approach is fundamentally incompatible.

## Recommendation

**Option A** is the cleanest path. It follows the same proven pattern as the Google Tasks MCP server, avoids the privacy layer latency, and gives full control over the tool surface. The implementation would be ~200 lines of Python using FastMCP.

## Files

- `test_direct_mcp.py` — proof of concept showing UC connection → Slack API calls working
- PEX source extracted from: `/Users/randy.pitcher/mcp/servers/slack_mcp/slack_mcp_deploy.pex`
- Google Tasks reference: `rpw-agent-marketplace/plugins/rpw-working/mcp-servers/google-tasks/`
