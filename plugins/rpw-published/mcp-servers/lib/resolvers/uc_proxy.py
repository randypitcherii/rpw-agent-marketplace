"""Resolver that validates UC connection is accessible and sets proxy env vars.

Unlike `uc_connection` which extracts tokens, this resolver just confirms
the user has access to the connection and exports:
- UC_PROXY_CONNECTION_NAME (passed through)
- UC_PROXY_PROFILE (passed through)
- UC_PROXY_FLAVOR (mcp_native | http_proxy — derived from connection metadata)
- UC_PROXY_URL (constructed from workspace host + connection name, shaped per flavor)

The MCP server uses the Databricks SDK at runtime to proxy calls. Profile auth
handling (host resolution, classifying expired/missing-profile failures) is
delegated to `lib.databricks_auth` so this resolver no longer hand-rolls the
`databricks auth env` CLI call or the expired-token detection inline. If the
Databricks refresh token is expired, a typed CredentialResolutionError is raised
with the exact `databricks auth login --profile X` command so each MCP server can
surface a clear stderr line.

Flavor-awareness (#115): a connection's metadata carries `options.is_mcp_connection`
when it is a genuine MCP-native securable (e.g. `system_ai_agent_*`). When set, the
resolver emits the MCP-native proxy URL (`/api/2.0/mcp/external/<name>`) and
`UC_PROXY_FLAVOR=mcp_native`; otherwise it keeps the historical HTTP_PROXY shape
(`/api/2.0/unity-catalog/connections/<name>/proxy/`) and `UC_PROXY_FLAVOR=http_proxy`.
The default is http_proxy whenever the flag is absent or the metadata is
unparseable, so every pre-existing HTTP_PROXY server keeps its exact behavior.
Note: request routing is driven by the SDK `conn=` argument, not UC_PROXY_URL —
UC_PROXY_URL only supplies the workspace host for reauth URLs — so this reshaping
is backward-compatible for servers that call `serving_endpoints.http_request`.
"""

import json
import os
import subprocess
from datetime import datetime, timezone

from lib import databricks_auth
from lib.errors import (
    CredentialResolutionError,
    uc_connection_not_authorized,
)


def _parse_expiration(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_expired(value: str | None) -> bool:
    parsed = _parse_expiration(value)
    return parsed is not None and parsed <= datetime.now(timezone.utc)


def _verify_user_credential_active(
    connection_name: str,
    host: str,
    databricks_profile: str,
) -> None:
    """Confirm the calling user has an ACTIVE OAuth credential for the connection.

    For OAuth-backed UC connections, USE_CONNECTION privilege is necessary but
    not sufficient — each user must also authenticate themselves. Without an
    ACTIVE credential, proxy calls succeed at startup but fail at runtime with
    opaque "Session terminated" errors. Catching it here gives the user the
    Databricks UI URL to fix it.
    """
    me_result = subprocess.run(
        ["databricks", "current-user", "me", "--profile", databricks_profile],
        capture_output=True, text=True, timeout=30,
    )
    if me_result.returncode != 0:
        # Auth issues here are caught by the earlier metadata call; treat as soft fail.
        return
    user_id = json.loads(me_result.stdout).get("id")
    if not user_id:
        return

    cred_result = subprocess.run(
        ["databricks", "api", "get",
         f"/api/2.1/unity-catalog/connections/{connection_name}/user-credentials/{user_id}",
         "--profile", databricks_profile],
        capture_output=True, text=True, timeout=30,
    )
    if cred_result.returncode != 0:
        # Most likely: user has never authenticated this connection.
        raise uc_connection_not_authorized(
            connection_name, host, databricks_profile, state="MISSING",
        )

    credential = json.loads(cred_result.stdout).get("connection_user_credential", {})
    state = credential.get("provisioning_info", {}).get("state")
    if state != "ACTIVE":
        raise uc_connection_not_authorized(
            connection_name, host, databricks_profile, state=state,
        )
    refresh_token_expiration = (
        credential
        .get("options_kvpairs", {})
        .get("options", {})
        .get("refresh_token_expiration")
    )
    if _is_expired(refresh_token_expiration):
        raise uc_connection_not_authorized(
            connection_name, host, databricks_profile, state="EXPIRED",
        )


def _is_mcp_native(metadata_stdout: str) -> bool:
    """Return True when the connection metadata marks it as MCP-native.

    Reads `options.is_mcp_connection` from the JSON the metadata `databricks api
    get` call already returned. The UC API serializes option values as strings,
    so `"true"` (any casing) is the truthy signal. Absent/unparseable metadata
    or any other value falls back to False (HTTP_PROXY), preserving the historical
    behavior for every pre-existing server.
    """
    try:
        metadata = json.loads(metadata_stdout or "")
    except (ValueError, TypeError):
        return False
    if not isinstance(metadata, dict):
        return False
    options = metadata.get("options") or {}
    if not isinstance(options, dict):
        return False
    return str(options.get("is_mcp_connection", "")).strip().lower() == "true"


def resolve(
    connection_name: str,
    databricks_profile: str,
) -> None:
    """Validate UC connection access and export proxy env vars.

    Args:
        connection_name: UC connection name (e.g. "slack", "system_ai_agent_glean_mcp").
        databricks_profile: Databricks CLI profile to use.
    """
    # Validate: fetch connection metadata to confirm user has USE_CONNECTION privilege.
    result = subprocess.run(
        [
            "databricks", "api", "get",
            f"/api/2.1/unity-catalog/connections/{connection_name}",
            "--profile", databricks_profile,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise databricks_auth.classify_cli_error(
            databricks_profile,
            result.stderr,
            fallback=CredentialResolutionError(
                f"Cannot access UC connection '{connection_name}' with profile "
                f"'{databricks_profile}': {result.stderr.strip()}",
                remediation=f"databricks auth login --profile {databricks_profile}",
                kind="uc_connection_inaccessible",
                context={"connection_name": connection_name, "profile": databricks_profile},
            ),
        )

    # Workspace host for the profile — needed for proxy URL construction. Resolved
    # from the profile's local config; raises a typed error if it's not configured.
    host = databricks_auth.get_workspace_host(databricks_profile)

    _verify_user_credential_active(connection_name, host, databricks_profile)

    os.environ["UC_PROXY_CONNECTION_NAME"] = connection_name
    os.environ["UC_PROXY_PROFILE"] = databricks_profile
    if _is_mcp_native(result.stdout):
        os.environ["UC_PROXY_FLAVOR"] = "mcp_native"
        os.environ["UC_PROXY_URL"] = f"{host}/api/2.0/mcp/external/{connection_name}"
    else:
        os.environ["UC_PROXY_FLAVOR"] = "http_proxy"
        os.environ["UC_PROXY_URL"] = (
            f"{host}/api/2.0/unity-catalog/connections/{connection_name}/proxy/"
        )
