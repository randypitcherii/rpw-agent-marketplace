"""
Load APP_ENV-selected env, resolve uc_proxy, validate UC proxy env, then run FastMCP.

Usage:
    APP_ENV=dev uv run python run_mcp.py
    uv run python run_mcp.py
"""

import sys
from pathlib import Path

# Allow imports from the parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import launcher

REQUIRED = ["UC_PROXY_CONNECTION_NAME", "UC_PROXY_PROFILE"]
MISSING_HINT = (
    "Set CREDENTIAL_SOURCE=uc_proxy with UC_CONNECTION_NAME=<your-jira-uc-connection> and DATABRICKS_PROFILE, "
    "or set UC_PROXY_CONNECTION_NAME and UC_PROXY_PROFILE directly in the env file."
)


def main() -> None:
    launcher.run(Path(__file__).parent, required=REQUIRED, missing_hint=MISSING_HINT)


if __name__ == "__main__":
    main()
