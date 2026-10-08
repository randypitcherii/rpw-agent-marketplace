"""Shared launcher for MCP server ``run_mcp.py`` wrappers.

Collapses the per-server boilerplate — APP_ENV-selected env loading, required-var
validation with an actionable stderr hint, an optional credential precheck, then the
hand-off to the server module's ``main()`` — into a single ``run(...)`` call. Each
server's ``run_mcp.py`` shrinks to a declaration (its ``REQUIRED`` list / hint) plus
one call.

Reliability contract (#428): pre-flight failures must never kill the process before
the stdio loop starts. A server that dies pre-registration is absent for the whole
client session ("no such tool" on every call); a server that registers *degraded*
costs one actionable error per call instead. So:

- **Transient** pre-flight failures (macOS keyring token-cache race, subprocess
  timeouts) get a small bounded retry — attempts stay cheap so registration still
  beats the client's startup timeout.
- **Any** persistent pre-flight failure degrades instead of exiting: the failure is
  logged to stderr, exported as ``MCP_STARTUP_ERROR`` (surfaced by
  ``lib.uc_proxy_client`` in per-call error envelopes), and the server is started
  anyway so it registers and stays diagnosable.
- A one-line readiness / degraded log is always emitted to stderr so a registration
  miss is diagnosable rather than silent.
- ``--selfcheck`` (or ``selfcheck=True``) runs the same pre-flight and exits 0/1
  *without* serving — a classifier-safe health probe (no credential env vars on the
  command line; everything comes from the server's env file).
- When configured, lifecycle events and root-logger warnings are mirrored to the shared
  log table via ``lib.telemetry`` (#891), and each native tool call adds one
  ``mcp.tool_call`` row (#1969). Opt-in; selfcheck never sends.

Import mechanism note: this lib is *not* a distributed package. Servers put the
sibling ``mcp-servers/`` dir on ``sys.path`` (``sys.path.insert(0, parent)``) before
importing ``lib.launcher``, so the ``from lib.env_loader import ...`` below resolves
the same sibling ``lib/`` the caller is importing us from. See ADR-2026-06-22 for why
the lib ships duplicated per-plugin rather than extracted to ``libs/rpw_mcp_lib`` (the
plugin cache and public mirror ship only the plugin dir, not repo-root ``libs/``).
"""

import importlib
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Optional, Union

from lib.env_loader import load_selected_env, validate_required_env
from lib.errors import CredentialResolutionError, looks_like_keyring_race
from lib import telemetry

# A missing-vars hint is either a static string or a callable of the resolved app_env
# (imessage's hint interpolates the env name into its "copy template.env to <env>.env").
Hint = Union[str, Callable[[str], str]]
# A precheck returns an actionable error string when auth is unusable, else None.
Precheck = Callable[[str, str], Optional[str]]

# Env var carrying the degraded-startup reason into the server process, read by
# lib.uc_proxy_client to enrich per-call error envelopes.
STARTUP_ERROR_ENV = "MCP_STARTUP_ERROR"

# Bounded retry for *transient* pre-flight failures only. Kept short on purpose:
# the whole point of degrading is to reach the stdio loop before the MCP client's
# registration timeout, so we must not burn that window on retries.
TRANSIENT_RETRY_ATTEMPTS = 3
TRANSIENT_RETRY_BASE_DELAY = 0.3  # seconds; grows linearly per attempt

_TRANSIENT_EXTRA_MARKERS = ("timed out", "timeout expired")

# Prefix of lib.env_loader._resolve_env_file's not-found message: the one
# FileNotFoundError ``env_optional`` servers tolerate.
ENV_FILE_MISSING_PREFIX = "Env file not found"


def _is_transient(detail: str) -> bool:
    """True for failures worth a quick retry: keyring race or a subprocess timeout."""
    if looks_like_keyring_race(detail):
        return True
    lower = (detail or "").lower()
    return any(marker in lower for marker in _TRANSIENT_EXTRA_MARKERS)


def _retry_transient(fn: Callable[[], object], label: str) -> object:
    """Run ``fn``, retrying up to TRANSIENT_RETRY_ATTEMPTS on transient failures.

    Non-transient failures propagate immediately (no pointless retry latency in
    the registration window). The last transient failure also propagates.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — classified below, re-raised
            if attempt >= TRANSIENT_RETRY_ATTEMPTS or not _is_transient(str(exc)):
                raise
            delay = TRANSIENT_RETRY_BASE_DELAY * attempt
            print(
                f"⚠️ {label} failed transiently (attempt {attempt}/"
                f"{TRANSIENT_RETRY_ATTEMPTS}), retrying in {delay:.1f}s: {exc}",
                file=sys.stderr,
            )
            time.sleep(delay)


def _log_ready(server: str, app_env: str, env_path: Optional[Path]) -> None:
    file_label = env_path.name if env_path is not None else "none (built-in defaults)"
    print(
        f"[{server}] ready: env={app_env} file={file_label}",
        file=sys.stderr,
    )


def _log_tool_telemetry(server: str, *, sink_live: bool, installed: bool) -> None:
    """Say whether ``mcp.tool_call`` rows will actually be emitted.

    Its own line rather than a field on ``ready:`` because the readiness line prints before
    the server module imports, and the middleware install needs that module's ``mcp``
    object. Discarding the boolean made "telemetry is on" unfalsifiable: a moved
    ``fastmcp.server.middleware`` or an ``mcp`` without ``add_middleware`` returns False,
    ``ready:`` still prints, and the rows simply stop — #1969's original symptom reproduced
    by the fix for it (#1972). ``off`` is the expected state with no sink configured;
    ``failed`` is the registration miss worth chasing.
    """
    if installed:
        state = "on"
    elif not sink_live:
        state = "off"
    else:
        state = "failed"
    print(f"[{server}] tool_telemetry={state}", file=sys.stderr)


def _log_degraded(server: str, reason: str) -> None:
    print(
        f"[{server}] degraded: {reason} — server will register; tool calls will "
        f"return this error until the underlying issue is fixed (see README, #428)",
        file=sys.stderr,
    )


def run(
    base_dir: Path,
    *,
    required: Optional[Sequence[str]] = None,
    missing_hint: Optional[Hint] = None,
    precheck: Optional[Precheck] = None,
    server_module: str = "mcp_server",
    selfcheck: Optional[bool] = None,
    env_optional: bool = False,
) -> None:
    """Load env, validate, optionally precheck, then run the server's ``main()``.

    Pre-flight failures never kill the process (#428): transient ones are retried,
    persistent ones degrade — the reason is logged, exported as
    ``MCP_STARTUP_ERROR``, and the server still starts so it registers with the
    MCP client and returns actionable per-call errors.

    Args:
        base_dir: The server directory (``Path(__file__).parent`` in the caller).
        required: Env vars that must be set; missing ones degrade the server.
        missing_hint: Appended after the missing-vars list — a str, or a callable
            taking the resolved app_env and returning the hint str.
        precheck: Optional ``(env_name, app_env) -> error | None`` run after the
            required-var check; a returned message degrades the server.
        server_module: Module whose ``main()`` is the server entrypoint.
        selfcheck: Run pre-flight only and exit 0 (ready) / 1 (degraded) without
            serving. Defaults to ``"--selfcheck" in sys.argv`` so wrappers get the
            probe for free.
        env_optional: A server whose every setting has a safe built-in default
            (no secret, no per-user value) may run with no env file at all. When
            True, a missing env file is not a failure: the server starts on its
            defaults and the readiness line says so. Any other env-load error
            still degrades. Default False keeps the env file mandatory.
    """
    server = base_dir.name
    if selfcheck is None:
        selfcheck = "--selfcheck" in sys.argv[1:]

    failure: Optional[str] = None
    app_env = "unknown"
    env_path: Optional[Path] = None

    try:
        app_env, env_path = _retry_transient(
            lambda: load_selected_env(base_dir), f"[{server}] env load"
        )
    except FileNotFoundError as exc:
        # Only the env file's own absence is optional; a FileNotFoundError from a
        # credential resolver (a missing CLI binary, say) still degrades.
        if env_optional and str(exc).startswith(ENV_FILE_MISSING_PREFIX):
            app_env = os.getenv("APP_ENV", "dev").strip().lower() or "dev"
            print(f"[{server}] no env file; using built-in defaults", file=sys.stderr)
        else:
            failure = str(exc)
    except (ValueError, CredentialResolutionError) as exc:
        failure = str(exc)

    if failure is None:
        missing = validate_required_env(list(required or []))
        if missing:
            env_name = env_path.name if env_path is not None else "env file"
            message = (
                f"Missing env vars in {env_name} for APP_ENV={app_env}: {missing}"
            )
            if missing_hint is not None:
                hint = missing_hint(app_env) if callable(missing_hint) else missing_hint
                message = f"{message}. {hint}"
            failure = message

    if failure is None and precheck is not None:
        env_name = env_path.name if env_path is not None else "env file"
        try:
            error = _retry_transient(
                lambda: precheck(env_name, app_env), f"[{server}] precheck"
            )
        except Exception as exc:  # noqa: BLE001 — degrade, never die pre-registration
            error = str(exc)
        if error:
            failure = str(error)

    if failure is not None:
        print(f"❌ {failure}", file=sys.stderr)
        _log_degraded(server, failure)
        os.environ[STARTUP_ERROR_ENV] = failure
        if selfcheck:
            sys.exit(1)
    else:
        os.environ.pop(STARTUP_ERROR_ENV, None)
        assert env_path is not None or env_optional
        _log_ready(server, app_env, env_path)
        if selfcheck:
            print(f"[{server}] selfcheck ok", file=sys.stderr)
            sys.exit(0)

    # After env load, so a server env file can carry RPW_LOGGING_* settings. Off unless
    # configured (#891); never raises.
    sink_live = telemetry.install(server)
    if sink_live:
        telemetry.event(
            server,
            "mcp.server.degraded" if failure else "mcp.server.start",
            severity="WARN" if failure else "INFO",
            message=failure,
            app_env=app_env,
        )

    # Imported before the middleware install so the server's own `mcp` object exists, and
    # after env load so a module that binds env at import time still sees the right values.
    module = importlib.import_module(server_module)
    installed = telemetry.install_tool_telemetry(getattr(module, "mcp", None), server)
    _log_tool_telemetry(server, sink_live=sink_live, installed=installed)
    module.main()
