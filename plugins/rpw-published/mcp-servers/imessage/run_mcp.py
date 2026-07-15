"""
Load APP_ENV-selected env, validate the notify-me handle, then run FastMCP.

No Databricks/UC credentials needed — `imsg` is a local CLI authorized by macOS
Full Disk Access + Automation permission. The only required config is the
NOTIFY_ME_HANDLE used by the send-only alert tool.

Usage:
    APP_ENV=dev uv run python run_mcp.py
    uv run python run_mcp.py
"""

import sys
from pathlib import Path

# Allow imports from the parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import launcher

REQUIRED = ["NOTIFY_ME_HANDLE"]


def _missing_hint(app_env: str) -> str:
    return (
        "Set NOTIFY_ME_HANDLE to your own phone number or iMessage email "
        f"(copy template.env to {app_env}.env)."
    )


def main() -> None:
    launcher.run(Path(__file__).parent, required=REQUIRED, missing_hint=_missing_hint)


if __name__ == "__main__":
    main()
