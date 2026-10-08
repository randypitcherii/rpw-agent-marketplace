"""Shared UC-proxy client for MCP servers that route external APIs through UC connections.

Consolidates the duplicated trio (`_require_proxy_env`, `_get_workspace_client`,
`_<vendor>_request`) that lived in each FastMCP server. The lib is minimal:

- `require_proxy_env()` reads UC_PROXY_CONNECTION_NAME / UC_PROXY_PROFILE and
  **raises RuntimeError** when either is missing.
- `get_workspace_client(profile)` returns a cached WorkspaceClient per-process.
- `request(...)` takes an injected `workspace_client` and performs the http_request,
  returning the same JSON-string contract servers used:
    happy path -> upstream dict serialized as JSON
    empty body -> {"ok": true, "data": null}
    non-dict data -> {"ok": true, "data": <data>}
    4xx/5xx -> {"ok": false, "error": "http_status", "status_code": N, "body": "..."}
    non-JSON body -> {"ok": false, "error": "invalid_json", "raw": "..."}
    SDK exception -> {"ok": false, "error": "<str(exc)>"}
- `request_via_env(...)` is the env-driven convenience wrapper used by google MCP servers.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any
from urllib.parse import quote, urlparse

from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod

from lib.errors import looks_like_keyring_race

_MAX_BODY_CHARS = 2000
_UC_OAUTH_FAILURE_MARKERS = (
    "oauth token exchange failed",
    "invalid_client",
    "invalid_grant",
    "expired_grant",
    "expired token",
    "token is expired",
    "token has expired",
)

# Module-level cache. Each MCP server runs as its own process, so this is
# effectively per-server: the WorkspaceClient — and the OAuth token source the
# SDK hangs off its Config — is resolved once and reused for the server's
# lifetime rather than rebuilt per call. The test-hook reset is here so server
# tests don't have to import private state.
_workspace_client: Any | None = None

# Serialization + retry around the macOS keyring token-cache race (#428).
#
# The Databricks SDK refreshes OAuth tokens lazily inside the request path; on
# macOS that refresh writes the token cache through the keychain, and two
# concurrent refreshes (parallel tool calls in one server session) collide as
# "forced token refresh: cache update: exit status 45". `_call_lock` guards that
# refresh so at most one runs per process at a time; the bounded retry below
# covers races with *other* processes (e.g. a second MCP server refreshing the
# same profile).
#
# The lock covers the REFRESH ONLY, not the upstream HTTP call. Holding it across
# the request serialized every tool call in a server, so one slow call (a Glean
# assistant answer, a broad Slack search — tens of seconds each) starved every
# other call behind it. Queued calls then burned their whole client-side budget
# waiting and failed having never issued a request. `config.authenticate()` is
# the racing step and is sub-millisecond when the token is still valid, so the
# lock is now held for microseconds instead of the length of the request.
_client_lock = threading.Lock()
_call_lock = threading.Lock()

_KEYRING_RETRY_ATTEMPTS = 3
_KEYRING_RETRY_BASE_DELAY = 0.25  # seconds; grows linearly per attempt

# Ceiling on waiting for the refresh lock. Reaching it means another thread is
# wedged inside a token refresh; failing fast with an actionable envelope beats
# blocking until the MCP client's own timeout kills the call with no explanation.
_LOCK_ACQUIRE_TIMEOUT_SECONDS = 30.0

# Ceiling on the upstream request itself. The SDK defaults to no timeout, so a
# hung proxy or upstream would block a server thread until the client gave up.
# Generous enough for slow upstream searches, but bounded to surface a hang.
_DEFAULT_HTTP_TIMEOUT_SECONDS = 150.0


def require_proxy_env() -> tuple[str, str]:
    """Return (connection_name, profile) from env, or raise RuntimeError.

    Both UC_PROXY_CONNECTION_NAME and UC_PROXY_PROFILE must be set and
    non-empty (after stripping whitespace).
    """
    conn = (os.environ.get("UC_PROXY_CONNECTION_NAME") or "").strip()
    profile = (os.environ.get("UC_PROXY_PROFILE") or "").strip()
    if not conn or not profile:
        raise RuntimeError(
            "UC_PROXY_CONNECTION_NAME and UC_PROXY_PROFILE must be set"
        )
    return conn, profile


def reset_workspace_client() -> None:
    """Test hook: clear the cached WorkspaceClient."""
    global _workspace_client
    _workspace_client = None


def get_workspace_client(profile: str) -> Any:
    """Return a cached WorkspaceClient bound to `profile`, constructing on first use.

    Construction is serialized: the first build resolves the profile's OAuth
    token (a keychain access on macOS), and two threads racing it would hit the
    same keyring contention the per-call lock exists to prevent (#428).

    The client carries an explicit `http_timeout_seconds`; the SDK's own default
    is unbounded, which lets a hung upstream pin a server thread indefinitely.
    """
    global _workspace_client
    with _client_lock:
        if _workspace_client is None:
            from databricks.sdk import WorkspaceClient  # lazy import for test isolation

            try:
                from databricks.sdk.core import Config

                _workspace_client = WorkspaceClient(
                    config=Config(
                        profile=profile,
                        http_timeout_seconds=_DEFAULT_HTTP_TIMEOUT_SECONDS,
                    )
                )
            except Exception:
                # The timeout is a defensive bound, not a correctness
                # requirement, so it must never be the reason a server fails to
                # build a client — an SDK without `Config`, or a patched
                # WorkspaceClient under test, falls back to plain construction.
                # A genuinely bad profile still raises, from the same call that
                # raised before this bound existed.
                _workspace_client = WorkspaceClient(profile=profile)
        return _workspace_client


def _refresh_auth_locked(workspace_client: Any) -> None:
    """Force the SDK's lazy OAuth refresh while holding `_call_lock`.

    This is the step that races on the macOS keychain (#428). Doing it here,
    under the lock, means the refresh is still serialized while the upstream
    request that follows is not. Raises so the caller's keyring-race retry and
    OAuth-reauth handling see the failure exactly as they did when the refresh
    happened implicitly inside the request.

    A client without a usable `config.authenticate` (older SDK, or a test
    double) is left alone: the refresh then happens inside the request as
    before, which is correct, just not de-raced.
    """
    config = getattr(workspace_client, "config", None)
    authenticate = getattr(config, "authenticate", None)
    if callable(authenticate):
        authenticate()


def _busy_envelope() -> str:
    """Returned when the refresh lock could not be acquired in time."""
    return json.dumps(
        {
            "ok": False,
            "error": "auth_refresh_busy",
            "detail": (
                "Timed out waiting for the OAuth refresh lock after "
                f"{_LOCK_ACQUIRE_TIMEOUT_SECONDS:.0f}s; another call in this "
                "server is stuck refreshing credentials. Retry, or reconnect "
                "the server if it persists."
            ),
            "retryable": True,
        }
    )


_DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _looks_like_uc_oauth_failure(status_code: int | None, detail: str) -> bool:
    """Return True for UC OAuth token-exchange failures, not all upstream 401s."""
    if not detail:
        return False
    lower = detail.lower()
    if "oauth token exchange failed" in lower:
        return True
    return status_code == 401 and any(
        marker in lower for marker in _UC_OAUTH_FAILURE_MARKERS
    )


def _status_code_from_detail(detail: str) -> int | None:
    match = re.search(r"http status code\s+(\d{3})", detail, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _workspace_host(workspace_client: Any | None = None) -> str | None:
    proxy_url = (os.environ.get("UC_PROXY_URL") or "").strip()
    if proxy_url:
        parsed = urlparse(proxy_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"

    config = getattr(workspace_client, "config", None)
    host = (
        getattr(config, "host", None)
        or os.environ.get("DATABRICKS_HOST")
        or ""
    ).strip()
    return host.rstrip("/") or None


def _service_label(conn: str) -> str:
    if "glean" in conn.lower():
        return "Glean"
    return f"'{conn}'"


def _uc_oauth_reauth_response(
    *,
    conn: str,
    workspace_client: Any | None,
    detail: str,
    status_code: int | None,
) -> str:
    host = _workspace_host(workspace_client)
    reauth_url = (
        f"{host}/explore/connections/{quote(conn, safe='')}"
        if host
        else None
    )
    profile = (os.environ.get("UC_PROXY_PROFILE") or "").strip() or None
    target = _service_label(conn)
    if reauth_url:
        remediation = (
            f"Your Unity Catalog connection for {target} needs to be "
            f"reauthenticated. Open {reauth_url}, complete OAuth, then retry "
            f"the original request."
        )
    else:
        remediation = (
            f"Your Unity Catalog connection for {target} needs to be "
            "reauthenticated in Databricks, then retry the original request."
        )

    payload: dict[str, Any] = {
        "ok": False,
        "error": "uc_oauth_reauthentication_required",
        "connection_name": conn,
        "remediation": remediation,
        "retryable_after_reauth": True,
        "body": detail[:_MAX_BODY_CHARS],
    }
    if status_code is not None:
        payload["status_code"] = status_code
    if profile:
        payload["profile"] = profile
    if reauth_url:
        payload["reauth_url"] = reauth_url
    return json.dumps(payload, ensure_ascii=False)


def request(
    *,
    workspace_client: Any,
    conn: str,
    method: ExternalFunctionRequestHttpMethod,
    path: str,
    json_body: dict[str, Any] | None = None,
    query_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    treat_empty_as_error: bool = False,
) -> str:
    """Proxy an HTTP call through a UC connection; return JSON string per contract.

    The leading slash on `path` is stripped.

    headers: if None, uses Accept/Content-Type application/json defaults.
      If provided, used as-is (replaces defaults entirely).

    treat_empty_as_error: if True, empty response body returns
      {"ok": false, "error": "empty_response"} instead of {"ok": true, "data": null}.
      Useful for APIs (like Slack) where empty 200s indicate a proxy/upstream bug.

    The OAuth refresh is serialized per-process (`_call_lock`) and retried a
    bounded number of times when the failure matches the macOS keyring
    token-cache race ("... cache update: exit status 45"), so a transient
    refresh collision costs a sub-second retry instead of a failed tool call
    (#428). The upstream request runs OUTSIDE that lock, so a slow call no
    longer blocks every other call in the same server.
    """
    for attempt in range(1, _KEYRING_RETRY_ATTEMPTS + 1):
        try:
            if not _call_lock.acquire(timeout=_LOCK_ACQUIRE_TIMEOUT_SECONDS):
                return _busy_envelope()
            try:
                _refresh_auth_locked(workspace_client)
            finally:
                _call_lock.release()

            resp = workspace_client.serving_endpoints.http_request(
                conn=conn,
                method=method,
                path=path.lstrip("/"),
                headers=headers if headers is not None else _DEFAULT_HEADERS,
                json=json_body,
                params=query_params,
            )
        except Exception as exc:
            detail = str(exc)
            if looks_like_keyring_race(detail) and attempt < _KEYRING_RETRY_ATTEMPTS:
                time.sleep(_KEYRING_RETRY_BASE_DELAY * attempt)
                continue
            status_code = _status_code_from_detail(detail)
            if _looks_like_uc_oauth_failure(status_code, detail):
                return _uc_oauth_reauth_response(
                    conn=conn,
                    workspace_client=workspace_client,
                    detail=detail,
                    status_code=status_code,
                )
            return json.dumps({"ok": False, "error": str(exc)})

        if resp.status_code and resp.status_code >= 400:
            body = (resp.text or "")[:_MAX_BODY_CHARS]
            if _looks_like_uc_oauth_failure(resp.status_code, body):
                return _uc_oauth_reauth_response(
                    conn=conn,
                    workspace_client=workspace_client,
                    detail=body,
                    status_code=resp.status_code,
                )
            return json.dumps(
                {
                    "ok": False,
                    "error": "http_status",
                    "status_code": resp.status_code,
                    "body": body,
                }
            )
        if not resp.content:
            if treat_empty_as_error:
                return json.dumps({"ok": False, "error": "empty_response"})
            return json.dumps({"ok": True, "data": None})
        try:
            data: Any = resp.json()
        except Exception:
            return json.dumps(
                {
                    "ok": False,
                    "error": "invalid_json",
                    "raw": (resp.text or "")[:_MAX_BODY_CHARS],
                }
            )
        if isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False)
        return json.dumps({"ok": True, "data": data}, ensure_ascii=False)

    # Unreachable: every loop iteration returns or continues, and the final
    # attempt always returns. Kept for type-checkers.
    return json.dumps({"ok": False, "error": "retries_exhausted"})


def request_via_env(
    method: ExternalFunctionRequestHttpMethod,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    query_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    treat_empty_as_error: bool = False,
) -> str:
    """Env-driven proxy call: read UC_PROXY_* env, get cached client, call request().

    On missing env, returns the literal `missing_env` JSON envelope used by the
    google MCP servers today — DO NOT change the existing keys or `detail` string,
    other tooling depends on these exact bytes. When the launcher degraded startup
    (#428), an additional `startup_error` key carries the pre-flight failure so a
    registered-but-degraded server returns the *root cause* per call instead of a
    bare missing-env message.

    headers: forwarded to request(). If None, defaults to Accept/Content-Type.
    treat_empty_as_error: forwarded to request(). If True, empty body is an error.
    """
    try:
        conn, profile = require_proxy_env()
    except RuntimeError:
        envelope: dict[str, Any] = {
            "ok": False,
            "error": "missing_env",
            "detail": "UC_PROXY_CONNECTION_NAME and UC_PROXY_PROFILE must be set",
        }
        startup_error = (os.environ.get("MCP_STARTUP_ERROR") or "").strip()
        if startup_error:
            envelope["startup_error"] = startup_error
        return json.dumps(envelope)
    return request(
        workspace_client=get_workspace_client(profile),
        conn=conn,
        method=method,
        path=path,
        json_body=json_body,
        query_params=query_params,
        headers=headers,
        treat_empty_as_error=treat_empty_as_error,
    )
