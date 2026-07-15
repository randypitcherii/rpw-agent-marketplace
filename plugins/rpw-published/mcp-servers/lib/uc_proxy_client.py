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
from typing import Any
from urllib.parse import quote, urlparse

from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod

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
# effectively per-server. The test-hook reset is here so server tests don't
# have to import private state.
_workspace_client: Any | None = None


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
    """Return a cached WorkspaceClient bound to `profile`, constructing on first use."""
    global _workspace_client
    if _workspace_client is None:
        from databricks.sdk import WorkspaceClient  # lazy import for test isolation
        _workspace_client = WorkspaceClient(profile=profile)
    return _workspace_client


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
    """
    try:
        resp = workspace_client.serving_endpoints.http_request(
            conn=conn,
            method=method,
            path=path.lstrip("/"),
            headers=headers if headers is not None else _DEFAULT_HEADERS,
            json=json_body,
            params=query_params,
        )
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
    except Exception as exc:
        detail = str(exc)
        status_code = _status_code_from_detail(detail)
        if _looks_like_uc_oauth_failure(status_code, detail):
            return _uc_oauth_reauth_response(
                conn=conn,
                workspace_client=workspace_client,
                detail=detail,
                status_code=status_code,
            )
        return json.dumps({"ok": False, "error": str(exc)})


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
    google MCP servers today — DO NOT change the envelope shape or `detail` string,
    other tooling depends on these exact bytes.

    headers: forwarded to request(). If None, defaults to Accept/Content-Type.
    treat_empty_as_error: forwarded to request(). If True, empty body is an error.
    """
    try:
        conn, profile = require_proxy_env()
    except RuntimeError:
        return json.dumps(
            {
                "ok": False,
                "error": "missing_env",
                "detail": "UC_PROXY_CONNECTION_NAME and UC_PROXY_PROFILE must be set",
            }
        )
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
