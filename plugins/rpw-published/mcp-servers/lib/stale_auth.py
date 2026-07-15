"""Provider-agnostic stale/expired-credential detection + short-circuit for MCP tools.

Provider SDKs surface expired keys / revoked tokens / unauthenticated sessions as
raw error strings that leak straight to the agent (issue #195: the Gemini image
tool returned ``400 INVALID_ARGUMENT ... API key expired. Please renew the API
key.``). This module gives every MCP server ONE way to:

1. **Detect** the common stale-auth signatures across providers (Google/Gemini
   expired API key, Google ``401 / UNAUTHENTICATED`` OAuth token, Databricks
   token expiry) — :func:`looks_like_stale_auth`.
2. **Normalize** them into a consistent, actionable JSON error envelope — *what
   happened* plus *the exact next action for the user* — :class:`StaleAuthError`.
3. **Short-circuit** repeated calls once a connection is known stale, so the
   server stops re-hitting the provider on every subsequent tool call —
   :class:`StaleAuthGuard`.

It composes with :mod:`lib.errors` / :mod:`lib.databricks_auth` (the
Databricks-specific auth machinery from #297) rather than duplicating them: the
Databricks expired-token markers are reused via
:func:`lib.errors.looks_like_databricks_auth_expired`, and :class:`StaleAuthError`
subclasses :class:`~lib.errors.CredentialResolutionError` so the ``message`` /
``remediation`` / ``kind`` / ``context`` fields stay uniform across the codebase.

Import mechanism note: like the rest of ``lib/``, this is *not* a distributed
package — servers put the sibling ``mcp-servers/`` dir on ``sys.path`` before
``from lib.stale_auth import ...``. The lib ships duplicated per-plugin
(byte-identical, guarded by a repo-validation test). See ADR-2026-06-22.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from lib.errors import (
    CredentialResolutionError,
    looks_like_databricks_auth_expired,
)

# Stable machine-readable category for the normalized envelope. One string so
# agents/log pipelines can branch on "is this a re-auth situation" uniformly.
STALE_AUTH_KIND = "stale_auth"


# Substrings that indicate a provider rejected the request because the credential
# is expired / invalid / not authenticated (as opposed to a transient outage or a
# genuine authorization/permission denial). Compared case-insensitively. Kept
# deliberately specific — a bare "401" or "invalid" is too loose and would
# misclassify unrelated failures — so each marker is a phrase providers actually
# emit for stale credentials.
_STALE_AUTH_MARKERS = (
    # --- Google / Gemini API-key expiry & invalidity ---
    "api key expired",
    "api_key_invalid",
    "api key not valid",
    "invalid api key",
    "renew the api key",
    # --- OAuth / bearer-token expiry & unauthenticated sessions (Google + generic) ---
    "unauthenticated",
    "invalid authentication credentials",
    "invalid_grant",
    "token has expired",
    "token is expired",
    "token has been expired or revoked",
    "access token has expired",
    "expired access token",
    "credential was not sent",
    "401 unauthorized",
)


def looks_like_stale_auth(text: str) -> bool:
    """True if ``text`` matches a known stale/expired/invalid-credential signature.

    Covers the provider-agnostic markers in this module plus the Databricks
    expired/revoked refresh-token signatures owned by :mod:`lib.errors`, so a
    single call classifies Gemini, Google-OAuth, and Databricks auth expiry.
    """
    if not text:
        return False
    lower = text.lower()
    if any(marker in lower for marker in _STALE_AUTH_MARKERS):
        return True
    return looks_like_databricks_auth_expired(text)


class StaleAuthError(CredentialResolutionError):
    """A normalized stale/expired-credential failure with an actionable next step.

    Subclasses :class:`~lib.errors.CredentialResolutionError` so it carries the
    same ``message`` / ``remediation`` / ``kind`` / ``context`` contract, and adds
    a JSON envelope (:meth:`as_dict`) and a tool-return string (:meth:`as_message`)
    for MCP servers whose tools return text rather than raise.

    Attributes (beyond the base error):
        provider: Short label for the upstream that rejected the credential
            (e.g. ``"vertex-ai"``, ``"databricks"``).
        detail: The raw provider error text that was classified, for debugging.
        short_circuited: True when this envelope was returned WITHOUT re-hitting
            the provider because the connection was already known stale.
    """

    def __init__(
        self,
        *,
        provider: str,
        remediation: str,
        detail: str = "",
        message: Optional[str] = None,
        short_circuited: bool = False,
    ) -> None:
        self.provider = provider
        self.detail = detail
        self.short_circuited = short_circuited
        rendered_message = message or (
            f"Authentication for {provider} is stale or expired"
        )
        super().__init__(
            rendered_message,
            remediation=remediation,
            kind=STALE_AUTH_KIND,
            context={
                "provider": provider,
                "detail": detail,
                "short_circuited": short_circuited,
            },
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize to the consistent stale-auth JSON envelope.

        Shape is stable across every MCP server so the agent can branch on it:
        ``error`` (the category), ``message`` (what happened), ``next_action``
        (the exact remediation), plus ``provider`` / ``short_circuited`` / ``detail``.
        """
        return {
            "error": STALE_AUTH_KIND,
            "provider": self.provider,
            "message": self.message,
            "next_action": self.remediation,
            "short_circuited": self.short_circuited,
            "detail": self.detail,
        }

    def as_message(self) -> str:
        """Render the envelope as a JSON string for a tool that returns text.

        MCP tools in this repo return a string to the agent; emitting the JSON
        envelope keeps the surface both human-actionable (message + next_action)
        and machine-parseable (stable ``error`` category) across servers.
        """
        return json.dumps(self.as_dict(), indent=2)


class StaleAuthGuard:
    """In-process latch that classifies stale-auth failures and short-circuits them.

    Instantiate one guard per credential/connection in a server process (usually a
    module-level singleton). Wrap each provider call with the two-step pattern:

    1. :meth:`short_circuit` first — if the connection is already known stale, it
       returns the cached :class:`StaleAuthError` immediately, so the tool never
       re-hits the provider.
    2. On a provider failure, pass the exception/text to :meth:`classify` — if it
       looks like stale auth, the guard latches and returns a fresh
       :class:`StaleAuthError`; otherwise it returns ``None`` and the caller
       handles the error normally.

    **Reset behavior.** The latch is process-local and has NO time-based expiry: it
    stays tripped until :meth:`reset` is called or the server process restarts. A
    restart is the natural reset point because ``run_mcp.py`` reloads the selected
    ``<APP_ENV>.env`` at startup — which is exactly where refreshed credentials
    land — so bouncing the MCP server (or the client that spawns it) clears the
    latch and picks up the new credential. ``since_monotonic`` / ``age_seconds``
    are exposed only for diagnostics/logging, not for auto-expiry.
    """

    def __init__(self, *, provider: str, remediation: str) -> None:
        self.provider = provider
        self.remediation = remediation
        self._error: Optional[StaleAuthError] = None
        self._since: Optional[float] = None

    @property
    def is_stale(self) -> bool:
        """True once a stale-auth failure has latched this guard."""
        return self._error is not None

    @property
    def since_monotonic(self) -> Optional[float]:
        """``time.monotonic()`` reading when the guard latched, else ``None``."""
        return self._since

    @property
    def age_seconds(self) -> Optional[float]:
        """Seconds since the guard latched (diagnostics only), else ``None``."""
        if self._since is None:
            return None
        return max(0.0, time.monotonic() - self._since)

    def short_circuit(self) -> Optional[StaleAuthError]:
        """Return the latched stale-auth error (marked short-circuited) if stale.

        Returns ``None`` when the connection is not known stale, so the caller
        proceeds with the real provider call.
        """
        if self._error is None:
            return None
        # Return a short-circuited view so the agent can tell a re-hit-avoiding
        # response apart from the first detection, without re-hitting the provider.
        return StaleAuthError(
            provider=self._error.provider,
            remediation=self._error.remediation,
            detail=self._error.detail,
            message=self._error.message,
            short_circuited=True,
        )

    def classify(self, error: Any) -> Optional[StaleAuthError]:
        """If ``error`` looks like stale auth, latch the guard and return the envelope.

        Accepts an exception or a raw string. Returns ``None`` (without latching)
        when the failure is not a stale-auth signature, so unrelated errors flow
        through the caller's normal handling.
        """
        text = error if isinstance(error, str) else str(error)
        if not looks_like_stale_auth(text):
            return None
        err = StaleAuthError(
            provider=self.provider,
            remediation=self.remediation,
            detail=text,
        )
        self._error = err
        self._since = time.monotonic()
        return err

    def reset(self) -> None:
        """Clear the latch so the next call re-attempts the provider.

        Call after a credential refresh within the same process. A process
        restart clears it implicitly (see class docstring).
        """
        self._error = None
        self._since = None
