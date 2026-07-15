"""Actionable credential errors raised by resolvers.

When a resolver detects a known failure mode (expired refresh token, missing
scope, missing field, no ADC, etc.), it raises CredentialResolutionError with
an exact remediation command so each MCP server's run_mcp.py can surface a
single clear stderr line that Claude Code shows in `claude mcp list`.
"""


# Common stderr substrings that indicate the Databricks CLI refresh token
# is expired/revoked. Compared case-insensitively.
_DATABRICKS_AUTH_EXPIRED_MARKERS = (
    "refresh token is invalid",
    "invalid_grant",
    "token has been revoked",
    "token is expired",
)


class CredentialResolutionError(Exception):
    """Actionable failure during credential resolution.

    Attributes:
        message: Short human-readable summary of what failed.
        remediation: Exact shell command the user should run, or None.
        kind: Short machine-readable category (e.g. "databricks_auth_expired").
        context: Optional dict of additional context (profile, scope, etc.).
    """

    def __init__(
        self,
        message: str,
        *,
        remediation: str | None = None,
        kind: str | None = None,
        context: dict | None = None,
    ) -> None:
        self.message = message
        self.remediation = remediation
        self.kind = kind
        self.context = context or {}
        if remediation:
            rendered = f"{message} — run: {remediation}"
        else:
            rendered = message
        super().__init__(rendered)


# Substrings that indicate the named Databricks profile is not configured at all
# (distinct from an expired token). The SDK/CLI phrase these as "no <profile>
# profile configured" or "no such profile". Compared case-insensitively.
_DATABRICKS_MISSING_PROFILE_MARKERS = (
    "profile configured",
    "no such profile",
)


def looks_like_databricks_auth_expired(stderr: str) -> bool:
    """True if stderr matches a known expired/revoked refresh-token signature."""
    if not stderr:
        return False
    lower = stderr.lower()
    return any(marker in lower for marker in _DATABRICKS_AUTH_EXPIRED_MARKERS)


def looks_like_missing_profile(text: str) -> bool:
    """True if the CLI/SDK message indicates the profile is not configured."""
    if not text:
        return False
    lower = text.lower()
    return any(marker in lower for marker in _DATABRICKS_MISSING_PROFILE_MARKERS)


def databricks_auth_expired(profile: str) -> CredentialResolutionError:
    return CredentialResolutionError(
        f"Auth expired for Databricks profile '{profile}'",
        remediation=f"databricks auth login --profile {profile}",
        kind="databricks_auth_expired",
        context={"profile": profile},
    )


def databricks_auth_error(profile: str, detail: str) -> CredentialResolutionError:
    """Generic Databricks CLI failure. Recommend re-login as the first move
    because that's the most common root cause for users hitting this path."""
    return CredentialResolutionError(
        f"Databricks CLI failed for profile '{profile}': {detail.strip()}",
        remediation=f"databricks auth login --profile {profile}",
        kind="databricks_auth_error",
        context={"profile": profile, "detail": detail},
    )


def databricks_profile_missing(profile: str) -> CredentialResolutionError:
    """The named Databricks profile is not configured on this machine."""
    return CredentialResolutionError(
        f"Databricks profile '{profile}' is not configured",
        remediation=f"databricks auth login --profile {profile}",
        kind="databricks_profile_missing",
        context={"profile": profile},
    )


def databricks_cli_unavailable() -> CredentialResolutionError:
    """The Databricks CLI is required for the browser login flow but not on PATH."""
    return CredentialResolutionError(
        "Databricks CLI not found on PATH",
        remediation=(
            "Install the Databricks CLI: "
            "https://docs.databricks.com/dev-tools/cli/install.html"
        ),
        kind="databricks_cli_unavailable",
        context={},
    )


def databricks_auth_non_interactive(
    profile: str,
    underlying: CredentialResolutionError | None = None,
) -> CredentialResolutionError:
    """Profile auth is missing/expired but no interactive browser flow is available.

    Returned by ``ensure_profile_authenticated(profile, interactive=False)`` when
    the token cache is unusable. Automated OAuth re-login cannot run headlessly —
    SSO/MFA needs a human at a browser — so the remediation is to run the login in
    an interactive shell. The ``underlying`` error (expired vs missing profile) is
    folded into the message and context so callers keep the precise auth state.
    """
    detail = f" ({underlying.message})" if underlying is not None else ""
    return CredentialResolutionError(
        f"Databricks profile '{profile}' needs interactive browser login, but this "
        f"environment is non-interactive{detail}",
        remediation=f"Run in an interactive shell: databricks auth login --profile {profile}",
        kind="databricks_auth_non_interactive",
        context={
            "profile": profile,
            "underlying_kind": getattr(underlying, "kind", None),
        },
    )


def uc_connection_not_authorized(
    connection_name: str,
    host: str,
    profile: str,
    state: str | None = None,
) -> CredentialResolutionError:
    """User has USE_CONNECTION but no ACTIVE OAuth credential for the connection.

    Returned when the user-credentials endpoint reports state != ACTIVE or is
    missing entirely. The remediation is the Databricks UI URL where the user
    can click "Authenticate" / "Re-authenticate" to start the OAuth flow.
    """
    url = f"{host.rstrip('/')}/explore/connections/{connection_name}"
    state_msg = f" (state={state})" if state else ""
    return CredentialResolutionError(
        f"UC connection '{connection_name}' is not authenticated for your user{state_msg}",
        remediation=f"Authenticate in the Databricks UI: {url}",
        kind="uc_connection_not_authorized",
        context={
            "connection_name": connection_name,
            "profile": profile,
            "host": host,
            "state": state,
            "url": url,
        },
    )
