"""
Thin wrapper that loads APP_ENV-selected env files and runs the Google Docs MCP server.
Keeps MCP config JSON secret-free.

Usage (from this directory):
    APP_ENV=dev|test|prod uv run python run_mcp.py
    uv run python run_mcp.py
"""

import sys
from pathlib import Path

# Allow imports from the parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import launcher

REQUIRED = ["GDOCS_QUOTA_PROJECT", "GDOCS_TARGET_FOLDER_ID"]


def main() -> None:
    launcher.run(Path(__file__).parent, required=REQUIRED)


if __name__ == "__main__":
    main()
