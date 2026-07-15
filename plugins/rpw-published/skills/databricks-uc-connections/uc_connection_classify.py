"""Classify a Databricks Unity Catalog connection as MCP-native or HTTP-proxy.

The discriminator is `options.is_mcp_connection` on the connection JSON.
Both flavors expose the same URL (`/api/2.0/unity-catalog/connections/<name>/proxy/`)
but speak different wire protocols at that path. See SKILL.md for full context
and the HTTP_PROXY-first preference for custom MCP server implementations.
"""

MCP_NATIVE = "MCP_NATIVE"
HTTP_PROXY = "HTTP_PROXY"


def classify(connection_json: dict) -> str:
    """Return 'MCP_NATIVE' or 'HTTP_PROXY' for a UC connection JSON.

    The Databricks API returns `options.is_mcp_connection` as the *string*
    "true" when the connection speaks MCP at its proxy URL. Any other value
    (absent, "false", None) means the connection is a plain HTTP OAuth-injection
    proxy that forwards arbitrary HTTP to the upstream service's REST API.
    """
    is_mcp = connection_json.get("options", {}).get("is_mcp_connection")
    return MCP_NATIVE if is_mcp == "true" else HTTP_PROXY


def proxy_url(workspace_host: str, connection_name: str) -> str:
    """Build the canonical /proxy/ URL for a UC connection.

    Shared across MCP_NATIVE and HTTP_PROXY — only the wire protocol differs.
    """
    return f"{workspace_host.rstrip('/')}/api/2.0/unity-catalog/connections/{connection_name}/proxy/"
