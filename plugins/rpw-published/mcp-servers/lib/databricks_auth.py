"""Databricks profile/auth wrapper for MCP servers and setup helpers.

A small, publishable, importable API that hides Databricks CLI/SDK auth mechanics
behind stable functions so servers and setup helpers stop hand-rolling
``subprocess.run(["databricks", ...])`` auth calls and stop telling users to type
``databricks auth login --profile ...`` during recovery.

Design:

- **Validation goes through the SDK token cache.** ``validate_profile`` builds a
  ``WorkspaceClient(profile=...)`` and calls ``current_user.me()``. The SDK reuses
  the profile's cached OAuth tokens and auto-refreshes them — no browser flow, no
  secrets read or written by this module.
- **Host resolution is local.** ``get_workspace_host`` reads the profile's host from
  local config (``~/.databrickscfg`` via the SDK ``Config``) with no network call.
- **First-time / expired login is owned by the Databricks CLI.** ``launch_profile_login``
  invokes the *supported* ``databricks auth login`` browser/SSO flow ourselves, with
  ``stdin`` from ``/dev/null`` (the OAuth callback is a local HTTP server, not stdin),
  so users never have to know or type the command.

Browser interaction still required: the helper *initiates* the flow, but the user
must complete SSO / MFA / consent in the browser. In non-interactive/headless
contexts there is nothing to click, so ``ensure_profile_authenticated`` returns a
structured, actionable :class:`~lib.errors.CredentialResolutionError` instead of
attempting an impossible automatic re-login (out of scope per #97).

Import mechanism note: like the rest of ``lib/``, this is *not* a distributed
package. Servers put the sibling ``mcp-servers/`` dir on ``sys.path`` before
importing ``lib.databricks_auth``. See ADR-2026-06-22 for why the lib ships
duplicated per-plugin rather than extracted to repo-root ``libs/``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Optional

from lib.errors import (
    CredentialResolutionError,
    databricks_auth_error,
    databricks_auth_expired,
    databricks_auth_non_interactive,
    databricks_cli_unavailable,
    databricks_profile_missing,
    looks_like_databricks_auth_expired,
    looks_like_missing_profile,
)

# Auth-state labels. Stable strings so they can be surfaced in JSON error envelopes.
STATE_ACTIVE = "active"
STATE_EXPIRED = "expired"
STATE_MISSING_PROFILE = "missing_profile"
STATE_UNAUTHENTICATED = "unauthenticated"
STATE_CLI_UNAVAILABLE = "cli_unavailable"
STATE_NON_INTERACTIVE = "non_interactive"
STATE_LOGIN_FAILED = "login_failed"

# Map a typed error's ``kind`` to the AuthStatus state label.
_KIND_TO_STATE = {
    "databricks_auth_expired": STATE_EXPIRED,
    "databricks_profile_missing": STATE_MISSING_PROFILE,
    "databricks_cli_unavailable": STATE_CLI_UNAVAILABLE,
    "databricks_auth_non_interactive": STATE_NON_INTERACTIVE,
}

# Default ceiling for the interactive browser login. Long enough for a human to
# complete SSO/MFA, short enough that a wedged callback eventually gives up.
DEFAULT_LOGIN_TIMEOUT = 180


@dataclass(frozen=True)
class AuthStatus:
    """Outcome of a profile auth check or recovery attempt.

    Attributes:
        profile: The Databricks CLI profile this status is about.
        authenticated: True only when the profile has a usable, non-expired credential.
        state: One of the module ``STATE_*`` labels.
        host: Workspace host for the profile when known, else None.
        user: Resolved user identity (user_name or id) when authenticated, else None.
        error: Actionable typed error when not authenticated, else None.
    """

    profile: str
    authenticated: bool
    state: str
    host: Optional[str] = None
    user: Optional[str] = None
    error: Optional[CredentialResolutionError] = None

    @property
    def ok(self) -> bool:
        return self.authenticated

    def raise_if_unauthenticated(self) -> "AuthStatus":
        """Raise the underlying typed error if not authenticated; else return self."""
        if not self.authenticated and self.error is not None:
            raise self.error
        return self

    def as_dict(self) -> dict:
        """Serialize to a JSON-friendly dict for MCP error envelopes / logging."""
        payload: dict[str, Any] = {
            "profile": self.profile,
            "authenticated": self.authenticated,
            "state": self.state,
        }
        if self.host is not None:
            payload["host"] = self.host
        if self.user is not None:
            payload["user"] = self.user
        if self.error is not None:
            payload["error"] = {
                "message": self.error.message,
                "kind": self.error.kind,
                "remediation": self.error.remediation,
                "context": self.error.context,
            }
        return payload


# --- Indirection seams (patched in unit tests; never hit live Databricks in tests) ---

def _build_workspace_client(profile: str) -> Any:
    """Construct a WorkspaceClient bound to ``profile`` (lazy import for isolation)."""
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(profile=profile)


def _build_config(profile: str) -> Any:
    """Construct an SDK Config for ``profile`` — local host resolution, no network."""
    from databricks.sdk.core import Config

    return Config(profile=profile)


def _databricks_cli_path() -> Optional[str]:
    """Absolute path to the ``databricks`` CLI, or None when not on PATH."""
    return shutil.which("databricks")


def _state_for_error(error: CredentialResolutionError) -> str:
    return _KIND_TO_STATE.get(error.kind or "", STATE_UNAUTHENTICATED)


def _classify_exception(profile: str, exc: Exception) -> CredentialResolutionError:
    """Turn an SDK/config exception into a typed CredentialResolutionError."""
    text = str(exc)
    if looks_like_missing_profile(text):
        return databricks_profile_missing(profile)
    if looks_like_databricks_auth_expired(text):
        return databricks_auth_expired(profile)
    return databricks_auth_error(profile, text)


def classify_cli_error(
    profile: str,
    stderr: str,
    *,
    fallback: Optional[CredentialResolutionError] = None,
) -> CredentialResolutionError:
    """Turn a failed ``databricks`` CLI ``stderr`` into a typed error.

    Single source of truth for "what does an auth-related CLI failure look like",
    so resolvers stop re-implementing the ``looks_like_databricks_auth_expired``
    branch inline. Expired/revoked tokens map to ``databricks_auth_expired`` and a
    missing profile to ``databricks_profile_missing``; otherwise ``fallback`` (a
    caller-specific error such as ``uc_connection_inaccessible``) is returned, or a
    generic ``databricks_auth_error`` when no fallback is given.
    """
    if looks_like_databricks_auth_expired(stderr):
        return databricks_auth_expired(profile)
    if looks_like_missing_profile(stderr):
        return databricks_profile_missing(profile)
    if fallback is not None:
        return fallback
    return databricks_auth_error(profile, stderr or "")


def _safe_host(client: Any) -> Optional[str]:
    config = getattr(client, "config", None)
    host = (getattr(config, "host", None) or "").strip()
    return host.rstrip("/") or None


# --- Public API ---------------------------------------------------------------


def validate_profile(profile: str) -> AuthStatus:
    """Validate a profile against the SDK token cache without any browser flow.

    Constructs ``WorkspaceClient(profile=...)`` and calls ``current_user.me()``,
    which reuses (and auto-refreshes) the profile's cached OAuth tokens. Returns an
    :class:`AuthStatus`; failures are classified into ``expired`` / ``missing_profile``
    / ``unauthenticated`` rather than raised, so callers can branch on state.
    """
    try:
        client = _build_workspace_client(profile)
    except Exception as exc:  # noqa: BLE001 — classify any construction failure
        error = _classify_exception(profile, exc)
        return AuthStatus(
            profile=profile,
            authenticated=False,
            state=_state_for_error(error),
            error=error,
        )

    try:
        me = client.current_user.me()
    except Exception as exc:  # noqa: BLE001 — classify any auth/API failure
        error = _classify_exception(profile, exc)
        return AuthStatus(
            profile=profile,
            authenticated=False,
            state=_state_for_error(error),
            host=_safe_host(client),
            error=error,
        )

    user = getattr(me, "user_name", None) or getattr(me, "id", None)
    return AuthStatus(
        profile=profile,
        authenticated=True,
        state=STATE_ACTIVE,
        host=_safe_host(client),
        user=user,
    )


def get_workspace_host(profile: str) -> str:
    """Return the workspace host for ``profile`` from local config (no network).

    Raises a typed :class:`~lib.errors.CredentialResolutionError` when the profile
    is not configured or has no host — the caller surfaces its remediation directly.
    """
    try:
        cfg = _build_config(profile)
    except Exception as exc:  # noqa: BLE001 — classify config-resolution failure
        raise _classify_exception(profile, exc) from exc
    host = (getattr(cfg, "host", None) or "").rstrip("/")
    if not host:
        raise databricks_auth_error(
            profile, f"No workspace host configured for profile '{profile}'"
        )
    return host


def launch_profile_login(
    profile: str,
    *,
    host: Optional[str] = None,
    timeout: int = DEFAULT_LOGIN_TIMEOUT,
) -> AuthStatus:
    """Initiate the supported ``databricks auth login`` browser/SSO flow ourselves.

    Runs the CLI with ``stdin`` from ``/dev/null`` — the OAuth callback is served by
    a local HTTP server, so no stdin is needed and a stray prompt cannot hang us. The
    user completes SSO/MFA/consent in the browser; success is confirmed by
    re-validating the token cache via :func:`validate_profile`. On a missing CLI,
    non-zero exit, or timeout, returns an :class:`AuthStatus` carrying a typed error.
    """
    cli = _databricks_cli_path()
    if cli is None:
        error = databricks_cli_unavailable()
        return AuthStatus(
            profile=profile,
            authenticated=False,
            state=STATE_CLI_UNAVAILABLE,
            host=host,
            error=error,
        )

    cmd = [cli, "auth", "login", "--profile", profile]
    if host:
        cmd += ["--host", host]

    try:
        with open(os.devnull, "rb") as devnull:
            result = subprocess.run(cmd, stdin=devnull, timeout=timeout)
    except subprocess.TimeoutExpired:
        return AuthStatus(
            profile=profile,
            authenticated=False,
            state=STATE_LOGIN_FAILED,
            host=host,
            error=databricks_auth_error(
                profile, "databricks auth login timed out before completion"
            ),
        )
    except OSError as exc:
        return AuthStatus(
            profile=profile,
            authenticated=False,
            state=STATE_LOGIN_FAILED,
            host=host,
            error=databricks_auth_error(profile, str(exc)),
        )

    if result.returncode != 0:
        return AuthStatus(
            profile=profile,
            authenticated=False,
            state=STATE_LOGIN_FAILED,
            host=host,
            error=databricks_auth_error(
                profile,
                f"databricks auth login exited with code {result.returncode}",
            ),
        )

    # Confirm the login actually produced a usable credential.
    return validate_profile(profile)


def ensure_profile_authenticated(
    profile: str,
    *,
    interactive: bool = False,
    host: Optional[str] = None,
) -> AuthStatus:
    """Ensure ``profile`` has usable auth, recovering interactively when allowed.

    - Already authenticated -> returns the active :class:`AuthStatus`.
    - ``interactive=True`` and not authenticated -> launches the browser/SSO login
      (see :func:`launch_profile_login`) and returns the post-login status.
    - ``interactive=False`` and not authenticated -> returns a structured,
      actionable error (state ``non_interactive``); it does NOT attempt an automatic
      headless re-login, which is impossible without a browser (out of scope, #97).
    """
    status = validate_profile(profile)
    if status.authenticated:
        return status

    if not interactive:
        error = databricks_auth_non_interactive(profile, status.error)
        return AuthStatus(
            profile=profile,
            authenticated=False,
            state=STATE_NON_INTERACTIVE,
            host=status.host,
            error=error,
        )

    return launch_profile_login(profile, host=host or status.host)
