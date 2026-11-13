"""
Thin wrapper that loads APP_ENV-selected env files and runs the Gemini Image MCP server.
Keeps MCP config JSON secret-free.

Auth depends on GEMINI_IMAGE_BACKEND (#2563). The default, ``vertex``, is Vertex AI
via gcloud Application Default Credentials: startup validates that
GOOGLE_CLOUD_PROJECT is set and an ADC session exists. ``databricks`` uses a
Databricks CLI profile's OAuth tokens: startup validates the profile exists in
~/.databrickscfg (locally, no network). Either way a failure surfaces in
`claude mcp list` with an actionable fix.

``GEMINI_IMAGE_BACKEND`` / ``GEMINI_IMAGE_DATABRICKS_PROFILE`` already set in the
process environment win over the env file (#2611); every other key keeps the
file-wins rule.

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


_BACKENDS = ("vertex", "databricks")


def _databricks_profile_exists(profile: str) -> bool:
    """True if ``profile`` is a section of the Databricks config file (no network call)."""
    import configparser

    path = Path(os.getenv("DATABRICKS_CONFIG_FILE") or Path.home() / ".databrickscfg")
    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error:
        return False
    # configparser never reports DEFAULT as a section; the SDK treats it as always present.
    return (profile == "DEFAULT" and path.is_file()) or parser.has_section(profile)


def _credential_error(env_name: str, app_env: str) -> str | None:
    """Return an actionable error message if the backend's auth isn't usable, else None."""
    backend = (os.getenv("GEMINI_IMAGE_BACKEND") or "vertex").strip().lower()
    if backend not in _BACKENDS:
        return f"GEMINI_IMAGE_BACKEND={backend!r} in {env_name} must be one of {', '.join(_BACKENDS)}"
    if backend == "databricks":
        profile = (
            os.getenv("GEMINI_IMAGE_DATABRICKS_PROFILE") or os.getenv("DATABRICKS_CONFIG_PROFILE") or "DEFAULT"
        ).strip()
        if not _databricks_profile_exists(profile):
            return (
                f"Databricks profile '{profile}' not found (GEMINI_IMAGE_BACKEND=databricks) — "
                f"run: databricks auth login --profile {profile}"
            )
        return None
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


# Backend-selection keys a launching process may pin (#2611). The env file loads with
# ``override=True``, so without this a caller such as darkroom exporting
# ``GEMINI_IMAGE_BACKEND=databricks`` would be silently overwritten by ``dev.env``.
# For these keys only, a value already in the process environment beats the file.
PINNABLE_KEYS = ("GEMINI_IMAGE_BACKEND", "GEMINI_IMAGE_DATABRICKS_PROFILE")


def explicit_pins(environ=None) -> dict[str, str]:
    """The pinnable keys set (non-empty) in ``environ`` before any env file loads."""
    environ = os.environ if environ is None else environ
    return {k: environ[k] for k in PINNABLE_KEYS if (environ.get(k) or "").strip()}


def pinned_precheck(pins: dict[str, str]):
    """A precheck that re-applies ``pins`` over the loaded env file, then validates.

    The launcher runs the precheck after the env file loads and before the server
    module imports, so this is the point where the process-supplied value wins.
    """

    def precheck(env_name: str, app_env: str) -> str | None:
        os.environ.update(pins)
        if pins:
            print(
                "[gemini-image] process env pins " + ", ".join(f"{k}={v}" for k, v in sorted(pins.items())),
                file=sys.stderr,
            )
        return _credential_error(env_name, app_env)

    return precheck


def main() -> None:
    launcher.run(Path(__file__).parent, precheck=pinned_precheck(explicit_pins()))


if __name__ == "__main__":
    main()
