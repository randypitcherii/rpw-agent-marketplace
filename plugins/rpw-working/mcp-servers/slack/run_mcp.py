"""
Thin wrapper that loads APP_ENV-selected env files and runs the Slack MCP server (PEX).
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

PEX_PATH = Path.home() / "mcp" / "servers" / "slack_mcp" / "slack_mcp_deploy.pex"
REQUIRED = ["SLACK_BOT_TOKEN"]


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

    # Enable alpha tools via env var (matches global settings pattern)
    os.environ["I_DANGEROUSLY_OPT_IN_TO_UNSUPPORTED_ALPHA_TOOLS"] = "true"

    os.execvp("python3.10", ["python3.10", str(PEX_PATH)])


if __name__ == "__main__":
    main()
