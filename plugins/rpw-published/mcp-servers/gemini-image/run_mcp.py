"""
Thin wrapper that loads APP_ENV-selected env files and runs the Gemini Image MCP server.
Keeps MCP config JSON secret-free.

Auth is Vertex AI via gcloud Application Default Credentials. Startup validates
that GOOGLE_CLOUD_PROJECT is set and an ADC session exists, so failures surface
in `claude mcp list` with an actionable fix.

Usage:
    APP_ENV=dev uv run python run_mcp.py
    uv run python run_mcp.py
"""

import os
import sys
from pathlib import Path

# Allow imports from the parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import launcher


def _adc_available() -> bool:
    """True if Application Default Credentials can be located (no network call)."""
    try:
        import google.auth

        google.auth.default()
        return True
    except Exception:
        return False


def _credential_error(env_name: str, app_env: str) -> str | None:
    """Return an actionable error message if Vertex AI auth isn't usable, else None."""
    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        return (
            f"GOOGLE_CLOUD_PROJECT not set in {env_name} (APP_ENV={app_env}) — "
            "required for Vertex AI"
        )
    if not _adc_available():
        return (
            "gcloud Application Default Credentials not found — "
            "run: gcloud auth application-default login"
        )
    return None


def main() -> None:
    launcher.run(Path(__file__).parent, precheck=_credential_error)


if __name__ == "__main__":
    main()
