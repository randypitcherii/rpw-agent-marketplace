---
name: databricks-uc-connections
description: Classify Databricks Unity Catalog (UC) connections as MCP-native vs HTTP-proxy and pick the right one for a given MCP server. Use when wiring a UC connection into an MCP server, creating a new MCP server that needs Databricks auth, troubleshooting "Session terminated" or 32600 errors from `uc-mcp-proxy`, or deciding which UC connection name to point at on a workspace where multiple connections target the same upstream service.
---

# Databricks UC Connections

A Databricks Unity Catalog connection is a workspace-level OAuth-injection proxy to an upstream service. On the wire, two flavors exist — **each served at a different URL path**:

| Flavor | URL path | Wire protocol | Use it when |
|---|---|---|---|
| **MCP_NATIVE** | `<host>/api/2.0/mcp/external/<name>` | Streamable HTTP MCP (JSON-RPC) | Falling back to a hosted, pre-built MCP server when our own custom MCP server doesn't exist yet or isn't working |
| **HTTP_PROXY** | `<host>/api/2.0/unity-catalog/connections/<name>/proxy/<upstream-path>` | Pass-through HTTP — Databricks injects the user's upstream OAuth credential and forwards `METHOD path` to the upstream REST API rooted at `options.base_path` | Building a custom MCP server we control — our FastMCP tools call the upstream REST API via this URL |

`connection_type` is `HTTP` for both (and `SLACK` for the bespoke Slack proxy). `options.is_mcp_connection: "true"` signals *additional* serving at `/api/2.0/mcp/external/<name>` — it does NOT disable the `/proxy/<path>` HTTP-pass-through path. So an MCP-native connection can also be used as a plain HTTP-proxy. Empirically verified against a `system_ai_agent_glean_mcp` connection on a Databricks workspace (returns HTTP 200 with real Glean REST data at `/proxy/search`).

**Critical:** `uc-mcp-proxy` must be pointed at `/api/2.0/mcp/external/<name>` — pointing it at `/proxy/` returns a misleading `32600 Session terminated` error because that path doesn't speak JSON-RPC.

## Classifier

A single field on the connection JSON determines the flavor:

```python
# uc_connection_classify.py — canonical implementation
def classify(connection_json: dict) -> str:
    """Return 'MCP_NATIVE' or 'HTTP_PROXY' for a UC connection JSON.

    The discriminator is `options.is_mcp_connection` — a *string* "true",
    not a boolean. Anything else (absent, "false", null) is HTTP_PROXY.
    """
    is_mcp = connection_json.get("options", {}).get("is_mcp_connection")
    return "MCP_NATIVE" if is_mcp == "true" else "HTTP_PROXY"
```

Bash one-liner to enumerate every UC connection on a workspace:

```bash
databricks connections list --profile <profile> -o json | \
  jq -r '.[] | [.name, (if .options.is_mcp_connection=="true" then "MCP_NATIVE" else "HTTP_PROXY" end)] | @tsv'
```

A test for the classifier lives at `test_uc_connection_classify.py` in this skill directory.

## Preference: HTTP_PROXY first for our own MCP servers

**When this plugin ships a custom MCP server for a service, point that server at the HTTP_PROXY connection — not the hosted MCP_NATIVE one.**

Why:
- The MCP server we ship is what we test against. If we route through an MCP_NATIVE connection, the user gets whatever surface Databricks' hosted MCP proxy exposes — which may differ from ours in tool names, schemas, error semantics, or coverage. Subtle behavior drift between dev and runtime is hard to debug.
- HTTP_PROXY connections give us OAuth-injection only; the wire surface our MCP tools speak is entirely our code, end-to-end controllable, and end-to-end testable.

**Fall back to MCP_NATIVE only if:**
- We haven't built a custom MCP server for this service yet (use the hosted one in the meantime), or
- The custom server is broken / behind on features and we need an immediate-term workaround.

When you DO fall back to MCP_NATIVE, prefer a connection name that's explicitly hosted-managed (typically the `system_ai_agent_*_mcp` cohort — see naming trap below). Don't rely on the connection's own name to tell you what flavor it is.

## The `-mcp` naming trap

On some workspaces, connection names ending in `-mcp` are misleading. Most of them are HTTP_PROXY despite the suffix; the actually-MCP-native ones are namespaced `system_ai_agent_*_mcp` and `system_ai_genie_*_mcp`. Always classify before assuming.

| Service | HTTP_PROXY connection (prefer for custom impl) | MCP_NATIVE connection (fallback) |
|---|---|---|
| Glean | `glean-mcp`, **`system_ai_agent_glean_mcp` works as HTTP_PROXY too** | `system_ai_agent_glean_mcp` (⚠️ MCP-native serving has been seen broken — `base_path` misconfigured as `/rest/api/v1`; should be `/mcp/default`. HTTP_PROXY usage of the same connection is fine — only the MCP path is broken.) |
| Atlassian (Jira + Confluence) | `jira-mcp`, `confluence-mcp` | `system_ai_agent_atlassian_mcp` (verified responding) |
| GitHub | — (none yet) | `system_ai_agent_github_mcp` (verified responding), `github-uc` |
| Google Drive / Docs / Sheets / Gmail | `google-mcp`, `google-docs-mcp`, `google-sheets-mcp`, `system_ai_agent_gmail`, `system_ai_agent_google_drive` | none — HTTP only |
| Slack | `slack` (connection_type=SLACK) | none — HTTP only |
| PagerDuty | `pagerduty-mcp` | none — HTTP only |

Always re-run the enumerator before trusting this table — Databricks workspace state changes.

## Picking a UC connection: decision flow

1. Run the enumerator. Note the classification for each connection that targets your upstream service.
2. If we ship (or are building) a custom MCP server for this service → pick the **HTTP_PROXY** connection. Wire our FastMCP tools to call the upstream REST API via `<host>/api/2.0/unity-catalog/connections/<name>/proxy/<upstream-path>` with REST verbs. `uc-mcp-proxy` is not in the chain.
3. If no custom server exists yet → pick the **MCP_NATIVE** connection and route through `uc-mcp-proxy --url <host>/api/2.0/mcp/external/<name>`. Track the gap as a TODO for a custom impl.
4. If multiple of the same flavor exist (e.g. a workspace exposing `google-mcp`, `google-docs-mcp`, `system_ai_agent_google_drive` all HTTP_PROXY for Google) → check each connection's `options.base_path` to see which upstream REST root it lands on, and pick the one that covers your tools' surface area.

## Common failure mode this skill prevents

`uc-mcp-proxy` returning `{"code": 32600, "message": "Session terminated"}` almost always means one of:

1. **Wrong URL** — `uc-mcp-proxy` was pointed at `/api/2.0/unity-catalog/connections/<name>/proxy/` instead of `/api/2.0/mcp/external/<name>`. MCP-native connections return 404 at the `/proxy/` path; the proxy reports that as a terminated session.
2. **HTTP_PROXY connection mistakenly passed to `uc-mcp-proxy`** — HTTP_PROXY connections don't speak JSON-RPC at any path. Use REST verbs through `/proxy/` directly, not `uc-mcp-proxy`.
3. **Misconfigured `options.base_path` on a system-managed MCP_NATIVE connection** — e.g. a `system_ai_agent_glean_mcp` connection with `base_path=/rest/api/v1` (Glean's REST root) instead of the documented `/mcp/default`, so the proxy 307-redirects to the wrong upstream path. This is a Databricks-side fix; the connection is read-only and system-owned, so a workspace admin or Databricks support must update it (or create a non-system replacement).

Auth is rarely the bug at this point. Classify the connection first, then verify the URL path.

## Related

- `mcp-setup` skill — uses this classifier when picking the source per server in `server_registry.py`.
- `mcp-standards` skill — when creating a new MCP server that needs Databricks auth, follow the HTTP_PROXY-first preference here.
- `lib/resolvers/uc_proxy.py` in `rpw-published/mcp-servers/` and `rpw-private/mcp-servers/` — runtime resolver. **Currently constructs the wrong URL for MCP_NATIVE connections** (it always uses `/api/2.0/unity-catalog/connections/<name>/proxy/`). Needs a flavor-aware path: `/proxy/` for HTTP_PROXY, `/api/2.0/mcp/external/<name>` for MCP_NATIVE. Tracked in epic #113.
