"""
Shared FastMCP application instance for the Google Docs MCP server.

Both ``mcp_server`` (core CRUD/tab tools) and ``tools_media`` (media + collab
tools) register their ``@mcp.tool`` functions on this single instance. Keeping
it in its own module lets both import it without a circular dependency.
"""

from fastmcp import FastMCP

mcp = FastMCP(name="google-docs")
