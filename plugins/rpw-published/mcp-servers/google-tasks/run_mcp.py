"""
Thin wrapper that loads APP_ENV-selected env files and runs the Google Tasks MCP server.
Keeps MCP config JSON secret-free. Launches local Python MCP server.

Usage (from this directory):
    APP_ENV=dev|test|prod uv run python run_mcp.py
    uv run python run_mcp.py
"""

import sys
from pathlib import Path

# Allow imports from the parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import launcher

REQUIRED = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"]


def main() -> None:
    launcher.run(Path(__file__).parent, required=REQUIRED)


if __name__ == "__main__":
    main()
