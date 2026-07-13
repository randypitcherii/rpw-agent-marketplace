"""
Resolver that fetches credentials from a Unity Catalog connection and sets them as env vars.
"""

import json
import os
import subprocess

from lib.errors import (
    CredentialResolutionError,
    databricks_auth_expired,
    looks_like_databricks_auth_expired,
)


def _get_user_id(profile: str) -> str:
    result = subprocess.run(
        ["databricks", "current-user", "me", "--profile", profile],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        if looks_like_databricks_auth_expired(result.stderr):
            raise databricks_auth_expired(profile)
        raise CredentialResolutionError(
            f"Failed to get current Databricks user with profile '{profile}': "
            f"{result.stderr.strip()}",
            remediation=f"databricks auth login --profile {profile}",
            kind="databricks_auth_error",
            context={"profile": profile},
        )
    data = json.loads(result.stdout)
    return data["id"]


def _get_connection_credentials(connection_name: str, user_id: str, profile: str) -> dict:
    result = subprocess.run(
        [
            "databricks",
            "api",
            "get",
            f"/api/2.1/unity-catalog/connections/{connection_name}/user-credentials/{user_id}",
            "--profile",
            profile,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        if looks_like_databricks_auth_expired(result.stderr):
            raise databricks_auth_expired(profile)
        raise CredentialResolutionError(
            f"Cannot fetch credentials for UC connection '{connection_name}' "
            f"with profile '{profile}': {result.stderr.strip()}",
            kind="uc_connection_inaccessible",
            context={"connection_name": connection_name, "profile": profile},
        )
    return json.loads(result.stdout)


def resolve(
    connection_name: str,
    env_var_map: dict[str, str],
    databricks_profile: str = "DEFAULT",
) -> None:
    """
    Fetch credentials from a UC connection and set them as environment variables.

    Args:
        connection_name: Name of the UC connection (e.g. "slack")
        env_var_map: Mapping from credential field names to env var names
                     (e.g. {"access_token": "SLACK_BOT_TOKEN"})
        databricks_profile: Databricks CLI profile to use
    """
    user_id = _get_user_id(databricks_profile)
    response = _get_connection_credentials(connection_name, user_id, databricks_profile)

    credential = response.get("connection_user_credential", {})
    state = credential.get("state")
    if state != "ACTIVE":
        raise CredentialResolutionError(
            f"Connection '{connection_name}' credential state is '{state}', expected ACTIVE",
            kind="uc_connection_inactive",
            context={"connection_name": connection_name, "state": state},
        )

    options = credential.get("options_kvpairs", {}).get("options", {})

    for field, env_var in env_var_map.items():
        if field not in options:
            raise CredentialResolutionError(
                f"Field '{field}' not found in UC connection '{connection_name}' "
                f"credentials. Available fields: {list(options.keys())}",
                kind="uc_connection_field_missing",
                context={
                    "connection_name": connection_name,
                    "field": field,
                    "available_fields": list(options.keys()),
                },
            )
        os.environ[env_var] = options[field]
