"""
Thin wrapper that loads APP_ENV-selected env files and runs the Google MCP server (PEX).
Keeps MCP config JSON secret-free.

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

PEX_PATH = Path.home() / "mcp" / "servers" / "google_mcp" / "google_mcp_deploy.pex"
REQUIRED = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"]


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

    if not PEX_PATH.exists():
        print(f"\u274c PEX not found: {PEX_PATH}", file=sys.stderr)
        sys.exit(1)

    # Enable alpha tools and disable privacy summarization via env vars
    os.environ["I_DANGEROUSLY_OPT_IN_TO_UNSUPPORTED_ALPHA_TOOLS"] = "true"
    os.environ["MCP_PRIVACY_SUMMARIZATION_ENABLED"] = "false"

    os.execvp("python3.10", ["python3.10", str(PEX_PATH)])


if __name__ == "__main__":
    main()
