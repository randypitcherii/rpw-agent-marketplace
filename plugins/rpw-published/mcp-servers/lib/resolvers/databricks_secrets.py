"""Resolver that fetches credentials from a Databricks secrets scope.

Uses the Databricks CLI: `databricks secrets get-secret <scope> <key> --profile <p>`.
"""

import base64
import json
import os
import subprocess

from lib.errors import (
    CredentialResolutionError,
    databricks_auth_expired,
    looks_like_databricks_auth_expired,
)


def _looks_like_scope_missing(stderr: str) -> bool:
    if not stderr:
        return False
    lower = stderr.lower()
    return "resource_does_not_exist" in lower and "scope" in lower


def resolve(
    scope: str,
    secret_map: dict[str, str],
    databricks_profile: str,
) -> None:
    """Fetch secrets from a Databricks scope and set them as env vars.

    Args:
        scope: The secrets scope name (e.g. "my_project_secrets").
        secret_map: Mapping of secret key name -> env var name.
        databricks_profile: Databricks CLI profile to use.
    """
    if not secret_map:
        return

    for secret_key, env_var in secret_map.items():
        result = subprocess.run(
            [
                "databricks",
                "secrets",
                "get-secret",
                scope,
                secret_key,
                "--profile",
                databricks_profile,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            if looks_like_databricks_auth_expired(result.stderr):
                raise databricks_auth_expired(databricks_profile)
            if _looks_like_scope_missing(result.stderr):
                raise CredentialResolutionError(
                    f"Databricks secret scope '{scope}' does not exist",
                    remediation=(
                        f"databricks secrets create-scope {scope} "
                        f"--profile {databricks_profile}"
                    ),
                    kind="databricks_secret_scope_missing",
                    context={"scope": scope, "profile": databricks_profile},
                )
            raise CredentialResolutionError(
                f"Failed to fetch secret '{secret_key}' from scope '{scope}' "
                f"using profile '{databricks_profile}': {result.stderr.strip()}",
                kind="databricks_secret_fetch_failed",
                context={
                    "scope": scope,
                    "key": secret_key,
                    "profile": databricks_profile,
                },
            )
        payload = json.loads(result.stdout)
        raw = payload.get("value", "")
        try:
            value = base64.b64decode(raw).decode("utf-8")
        except Exception:
            value = raw
        os.environ[env_var] = value
