"""
Thin wrapper that loads APP_ENV-selected env files and runs the Glean MCP server.
Uses the glean-mcp PyPI package (no PEX dependency).

Usage:
    APP_ENV=dev uv run python run_mcp.py
    uv run python run_mcp.py
"""

import os
import sys
from pathlib import Path

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.env_loader import load_selected_env, validate_required_env

REQUIRED = ["GLEAN_API_TOKEN", "GLEAN_BASE_URL"]


def main() -> None:
    base_dir = Path(__file__).parent
    try:
        app_env, env_path = load_selected_env(base_dir)
    except (ValueError, FileNotFoundError) as exc:
        print(f"\u274c {exc}", file=sys.stderr)
        sys.exit(1)

    missing = validate_required_env(REQUIRED)
    if missing:
        print(
            f"\u274c Missing env vars in {env_path.name} for APP_ENV={app_env}: {missing}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Run the glean-mcp server module directly
    from glean_mcp.server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
