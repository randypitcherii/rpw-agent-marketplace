"""
Resolver that fetches credentials from a Unity Catalog connection and sets them as env vars.
"""

import json
import os
import subprocess


def _get_user_id(profile: str) -> str:
    result = subprocess.run(
        ["databricks", "current-user", "me", "--profile", profile],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get current user: {result.stderr}")
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
        raise RuntimeError(
            f"Failed to get credentials for connection '{connection_name}': {result.stderr}"
        )
    return json.loads(result.stdout)


def resolve(
    connection_name: str,
    env_var_map: dict[str, str],
    databricks_profile: str = "logfood",
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
        raise RuntimeError(
            f"Connection '{connection_name}' credential state is '{state}', expected ACTIVE"
        )

    options = credential.get("options_kvpairs", {}).get("options", {})

    for field, env_var in env_var_map.items():
        if field not in options:
            raise RuntimeError(
                f"Field '{field}' not found in connection '{connection_name}' credentials. "
                f"Available fields: {list(options.keys())}"
            )
        os.environ[env_var] = options[field]
