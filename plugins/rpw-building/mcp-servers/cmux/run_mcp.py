"""
Thin wrapper that validates cmux socket availability and runs the cmux MCP server.
No secrets needed — cmux uses a local Unix socket.

Usage:
    uv run python run_mcp.py
    CMUX_SOCKET_PATH=/custom/path.sock uv run python run_mcp.py
"""

import os
import sys
from pathlib import Path


def main() -> None:
    socket_path = os.environ.get("CMUX_SOCKET_PATH", "/tmp/cmux.sock")

    if not Path(socket_path).exists():
        print(
            f"\u274c cmux socket not found at {socket_path}. "
            "Is cmux running? Start it or set CMUX_SOCKET_PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

    from mcp_server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
