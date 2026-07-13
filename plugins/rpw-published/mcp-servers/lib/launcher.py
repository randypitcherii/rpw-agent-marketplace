"""Shared launcher for MCP server ``run_mcp.py`` wrappers.

Collapses the per-server boilerplate — APP_ENV-selected env loading, required-var
validation with an actionable stderr hint, an optional credential precheck, then the
hand-off to the server module's ``main()`` — into a single ``run(...)`` call. Each
server's ``run_mcp.py`` shrinks to a declaration (its ``REQUIRED`` list / hint) plus
one call.

Import mechanism note: this lib is *not* a distributed package. Servers put the
sibling ``mcp-servers/`` dir on ``sys.path`` (``sys.path.insert(0, parent)``) before
importing ``lib.launcher``, so the ``from lib.env_loader import ...`` below resolves
the same sibling ``lib/`` the caller is importing us from. See ADR-2026-06-22 for why
the lib ships duplicated per-plugin rather than extracted to ``libs/rpw_mcp_lib`` (the
plugin cache and public mirror ship only the plugin dir, not repo-root ``libs/``).
"""

import importlib
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Optional, Union

from lib.env_loader import load_selected_env, validate_required_env
from lib.errors import CredentialResolutionError

# A missing-vars hint is either a static string or a callable of the resolved app_env
# (imessage's hint interpolates the env name into its "copy template.env to <env>.env").
Hint = Union[str, Callable[[str], str]]
# A precheck returns an actionable error string when auth is unusable, else None.
Precheck = Callable[[str, str], Optional[str]]


def run(
    base_dir: Path,
    *,
    required: Optional[Sequence[str]] = None,
    missing_hint: Optional[Hint] = None,
    precheck: Optional[Precheck] = None,
    server_module: str = "mcp_server",
) -> None:
    """Load env, validate, optionally precheck, then run the server's ``main()``.

    Args:
        base_dir: The server directory (``Path(__file__).parent`` in the caller).
        required: Env vars that must be set; missing ones abort with exit 1.
        missing_hint: Appended after the missing-vars list — a str, or a callable
            taking the resolved app_env and returning the hint str.
        precheck: Optional ``(env_name, app_env) -> error | None`` run after the
            required-var check; a returned message aborts with exit 1.
        server_module: Module whose ``main()`` is the server entrypoint.
    """
    try:
        app_env, env_path = load_selected_env(base_dir)
    except (ValueError, FileNotFoundError, CredentialResolutionError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)

    missing = validate_required_env(list(required or []))
    if missing:
        message = (
            f"❌ Missing env vars in {env_path.name} for APP_ENV={app_env}: {missing}"
        )
        if missing_hint is not None:
            hint = missing_hint(app_env) if callable(missing_hint) else missing_hint
            message = f"{message}. {hint}"
        print(message, file=sys.stderr)
        sys.exit(1)

    if precheck is not None:
        error = precheck(env_path.name, app_env)
        if error:
            print(f"❌ {error}", file=sys.stderr)
            sys.exit(1)

    server_main = importlib.import_module(server_module).main
    server_main()
