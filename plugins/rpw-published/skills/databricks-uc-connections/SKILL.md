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

`connection_type` alone does not distinguish the two flavors. `options.is_mcp_connection: "true"` signals serving at `/api/2.0/mcp/external/<name>`; do not infer the wire protocol from the connection name.

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

When you fall back to MCP_NATIVE, use a connection the workspace administrator documents as hosted-managed. Do not rely on a connection's name or an old inventory: classify the current workspace response every time.

## Picking a UC connection: decision flow

1. Run the enumerator. Note the classification for each connection that targets your upstream service.
2. If we ship (or are building) a custom MCP server for this service → pick the **HTTP_PROXY** connection. Wire our FastMCP tools to call the upstream REST API via `<host>/api/2.0/unity-catalog/connections/<name>/proxy/<upstream-path>` with REST verbs. `uc-mcp-proxy` is not in the chain.
3. If no custom server exists yet → pick the **MCP_NATIVE** connection and route through `uc-mcp-proxy --url <host>/api/2.0/mcp/external/<name>`. Track the gap as a TODO for a custom impl.
4. If multiple connections of the same flavor exist, check each connection's `options.base_path` and administrator documentation. Pick the one that covers the required tool surface.

## Common failure mode this skill prevents

`uc-mcp-proxy` returning `{"code": 32600, "message": "Session terminated"}` almost always means one of:

1. **Wrong URL** — `uc-mcp-proxy` was pointed at `/api/2.0/unity-catalog/connections/<name>/proxy/` instead of `/api/2.0/mcp/external/<name>`. MCP-native connections return 404 at the `/proxy/` path; the proxy reports that as a terminated session.
2. **HTTP_PROXY connection mistakenly passed to `uc-mcp-proxy`** — HTTP_PROXY connections don't speak JSON-RPC at any path. Use REST verbs through `/proxy/` directly, not `uc-mcp-proxy`.
3. **Misconfigured `options.base_path` on a managed MCP_NATIVE connection** — the connection redirects to an upstream REST path instead of its MCP path. A workspace administrator or Databricks support must update a read-only managed connection.

Auth is rarely the bug at this point. Classify the connection first, then verify the URL path.

### Two 401s that look like broken connections but are not

- **`UNAUTHENTICATED … Credential for user identity(N) is not found`** — an `OAUTH_U2M_MAPPING` connection with no credential for *you* yet. The message carries the exact `<host>/explore/connections/<name>` login URL; a human completes that browser OAuth once, per user. Nothing to fix in code.
- **`401 Invalid Secret / Not allowed`** — the upstream service can reject a forwarded token when a service-specific header is missing. Check the upstream API's documented auth-header requirements before concluding the connection is dead.

## Related

- `mcp-setup` skill — uses this classifier when picking the source per server in `server_registry.py`.
- `mcp-standards` skill — when creating a new MCP server that needs Databricks auth, follow the HTTP_PROXY-first preference here.
- The resolver under `mcp-servers/lib/resolvers/uc_proxy.py` must use a flavor-aware path: `/proxy/` for HTTP_PROXY and `/api/2.0/mcp/external/<name>` for MCP_NATIVE.
