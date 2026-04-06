"""
cmux MCP Server — wraps the cmux Unix socket API for AI agent control.

Provides tools for workspace management, surface/split control, text input,
and notifications via cmux's JSON-RPC socket at /tmp/cmux.sock.
"""

import json
import os
import socket
from typing import Any

from fastmcp import FastMCP

CMUX_SOCKET_PATH = os.environ.get("CMUX_SOCKET_PATH", "/tmp/cmux.sock")

mcp = FastMCP(
    "cmux",
    instructions="Control cmux terminal multiplexer — workspaces, splits, input, notifications",
)


def _send_rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a JSON-RPC request to cmux socket and return the result."""
    request = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        request["params"] = params

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(CMUX_SOCKET_PATH)
        sock.sendall((json.dumps(request) + "\n").encode())

        # Read response (newline-terminated JSON)
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
    finally:
        sock.close()

    response = json.loads(data.decode().strip())
    if "error" in response:
        raise RuntimeError(f"cmux error: {response['error']}")
    return response.get("result", {})


# --- System ---


@mcp.tool()
def ping() -> str:
    """Check if cmux is running and responsive."""
    result = _send_rpc("system.ping")
    return json.dumps(result)


# --- Workspace tools ---


@mcp.tool()
def workspace_list() -> str:
    """List all cmux workspaces."""
    result = _send_rpc("workspace.list")
    return json.dumps(result, indent=2)


@mcp.tool()
def workspace_current() -> str:
    """Get the currently active workspace."""
    result = _send_rpc("workspace.current")
    return json.dumps(result, indent=2)


@mcp.tool()
def workspace_create(name: str | None = None, directory: str | None = None) -> str:
    """Create a new cmux workspace.

    Args:
        name: Optional workspace name
        directory: Optional starting directory
    """
    params: dict[str, Any] = {}
    if name:
        params["name"] = name
    if directory:
        params["directory"] = directory
    result = _send_rpc("workspace.create", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def workspace_select(workspace_id: str) -> str:
    """Switch to a specific workspace.

    Args:
        workspace_id: The workspace ID to switch to
    """
    result = _send_rpc("workspace.select", {"id": workspace_id})
    return json.dumps(result, indent=2)


@mcp.tool()
def workspace_close(workspace_id: str) -> str:
    """Close a workspace.

    Args:
        workspace_id: The workspace ID to close
    """
    result = _send_rpc("workspace.close", {"id": workspace_id})
    return json.dumps(result, indent=2)


# --- Surface/split tools ---


@mcp.tool()
def surface_list() -> str:
    """List all surfaces (terminal panes) in the current workspace."""
    result = _send_rpc("surface.list")
    return json.dumps(result, indent=2)


@mcp.tool()
def surface_split(direction: str, surface_id: str | None = None) -> str:
    """Split a surface to create a new terminal pane.

    Args:
        direction: Split direction — one of: left, right, up, down
        surface_id: Optional surface to split (defaults to focused surface)
    """
    if direction not in ("left", "right", "up", "down"):
        return f"Error: direction must be one of: left, right, up, down (got '{direction}')"
    params: dict[str, Any] = {"direction": direction}
    if surface_id:
        params["id"] = surface_id
    result = _send_rpc("surface.split", params)
    return json.dumps(result, indent=2)


@mcp.tool()
def surface_focus(surface_id: str) -> str:
    """Focus a specific surface (terminal pane).

    Args:
        surface_id: The surface ID to focus
    """
    result = _send_rpc("surface.focus", {"id": surface_id})
    return json.dumps(result, indent=2)


# --- Input tools ---


@mcp.tool()
def send_text(text: str, surface_id: str | None = None) -> str:
    """Send text input to a cmux surface (terminal pane).

    Args:
        text: The text to send (e.g., a command to run)
        surface_id: Optional target surface (defaults to focused surface)
    """
    params: dict[str, Any] = {"text": text}
    if surface_id:
        params["id"] = surface_id
    result = _send_rpc("surface.send_text", params)
    return json.dumps(result, indent=2)


# --- Notification tools ---


@mcp.tool()
def notify(title: str, body: str | None = None) -> str:
    """Create a cmux notification.

    Args:
        title: Notification title
        body: Optional notification body text
    """
    params: dict[str, Any] = {"title": title}
    if body:
        params["body"] = body
    result = _send_rpc("notification.create", params)
    return json.dumps(result, indent=2)


def main() -> None:
    """Run the cmux MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
