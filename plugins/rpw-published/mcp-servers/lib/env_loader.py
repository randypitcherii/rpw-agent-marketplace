"""
Shared env-loading logic for MCP server wrappers.

Provides APP_ENV selection (dev/test/prod), env file resolution,
dotenv loading, and required-variable validation.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

VALID_APP_ENVS = {"dev", "test", "prod"}

STABLE_CONFIG_ROOT = Path.home() / ".claude" / "mcp-servers"
SHARED_CONFIG_FILE = STABLE_CONFIG_ROOT / ".shared.env"


def _parse_field_map(raw: str | None) -> dict[str, str]:
    """Parse a comma-separated field map like 'api_key:EXA_API_KEY,base_url:EXA_URL'.

    Returns {} for None or empty string. Raises ValueError on malformed entries.
    """
    if not raw:
        return {}
    result: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise ValueError(
                f"Malformed field map entry '{pair}' — expected 'field:ENV_VAR'"
            )
        field, env_var = pair.split(":", 1)
        result[field.strip()] = env_var.strip()
    return result


def get_app_env() -> str:
    app_env = os.getenv("APP_ENV", "dev").strip().lower()
    if app_env not in VALID_APP_ENVS:
        raise ValueError(
            f"Invalid APP_ENV '{app_env}'. Expected one of: {sorted(VALID_APP_ENVS)}"
        )
    return app_env


def resolve_env_path(base_dir: Path, app_env: str) -> Path:
    return base_dir / f"{app_env}.env"


def _resolve_env_file(base_dir: Path, app_env: str) -> Path:
    """Locate the env file, checking base_dir first then the stable user-level path.

    The stable path survives plugin cache invalidation and version bumps. When
    Claude Code runs the server from a cached plugin path, base_dir won't contain
    a dev.env — fall back to ~/.claude/mcp-servers/<server>/<app_env>.env.
    """
    local = resolve_env_path(base_dir, app_env)
    if local.exists():
        return local

    stable = STABLE_CONFIG_ROOT / base_dir.name / f"{app_env}.env"
    if stable.exists():
        return stable

    raise FileNotFoundError(
        f"Env file not found at {local} or {stable}. "
        f"Run /mcp-setup in a Claude session to configure this server."
    )


def _emit_credential_log(server_name: str, source: str, config: dict) -> None:
    """Emit a single-line credential-source log to stderr (does not pollute MCP stdio JSON).

    Format: [<server-name>] credential source=<source>[, profile=<profile>][, connection=<conn>]
    """
    parts = [f"credential source={source}"]
    profile = config.get("databricks_profile")
    if profile:
        parts.append(f"profile={profile}")
    connection = config.get("connection_name")
    if connection:
        parts.append(f"connection={connection}")
    line = f"[{server_name}] {', '.join(parts)}\n"
    sys.stderr.write(line)


def load_selected_env(base_dir: Path) -> tuple[str, Path]:
    app_env = get_app_env()

    # Load shared user-level config first if it exists. Per-server env can override.
    if SHARED_CONFIG_FILE.exists():
        load_dotenv(SHARED_CONFIG_FILE)

    env_path = _resolve_env_file(base_dir, app_env)
    load_dotenv(env_path, override=True)

    source = os.getenv("CREDENTIAL_SOURCE")
    if source:
        config = _build_resolver_config(source)
        _emit_credential_log(base_dir.name, source, config)
        resolve_credentials(source, config)

    return app_env, env_path


def _build_resolver_config(source: str) -> dict:
    """Build the config dict expected by resolve_credentials() from env vars."""
    if source == "uc_connection":
        return {
            "connection_name": os.environ["UC_CONNECTION_NAME"],
            "databricks_profile": os.getenv("DATABRICKS_PROFILE", "DEFAULT"),
            "env_var_map": _parse_field_map(os.getenv("UC_FIELD_MAP")),
        }
    if source == "gcloud_adc":
        return {
            "env_var_map": _parse_field_map(os.getenv("GCLOUD_FIELD_MAP")),
        }
    if source == "databricks_secrets":
        return {
            "scope": os.environ["DATABRICKS_SECRET_SCOPE"],
            "databricks_profile": os.environ["DATABRICKS_PROFILE"],
            "secret_map": _parse_field_map(os.getenv("DATABRICKS_SECRET_MAP")),
        }
    if source == "uc_proxy":
        return {
            "connection_name": os.environ["UC_CONNECTION_NAME"],
            "databricks_profile": os.environ["DATABRICKS_PROFILE"],
        }
    raise ValueError(
        f"Unknown CREDENTIAL_SOURCE '{source}'. "
        f"Expected one of: uc_connection, gcloud_adc, databricks_secrets, uc_proxy"
    )


def validate_required_env(required: list[str]) -> list[str]:
    return [v for v in required if not os.getenv(v)]


def resolve_credentials(source: str, config: dict) -> None:
    """Dispatch to the appropriate credential resolver.

    Args:
        source: One of "env_file", "uc_connection", "gcloud_adc"
        config: Source-specific configuration dict passed to the resolver
    """
    if source == "env_file":
        from lib.resolvers.env_file import resolve
        resolve(
            base_dir=config["base_dir"],
            env_var_map=config.get("env_var_map", {}),
            required=config.get("required", []),
        )
    elif source == "uc_connection":
        from lib.resolvers.uc_connection import resolve
        resolve(
            connection_name=config["connection_name"],
            env_var_map=config["env_var_map"],
            databricks_profile=config.get("databricks_profile", "DEFAULT"),
        )
    elif source == "gcloud_adc":
        from lib.resolvers.gcloud_adc import resolve
        resolve(
            env_var_map=config["env_var_map"],
        )
    elif source == "databricks_secrets":
        from lib.resolvers.databricks_secrets import resolve
        resolve(
            scope=config["scope"],
            secret_map=config["secret_map"],
            databricks_profile=config["databricks_profile"],
        )
    elif source == "uc_proxy":
        from lib.resolvers.uc_proxy import resolve
        resolve(
            connection_name=config["connection_name"],
            databricks_profile=config["databricks_profile"],
        )
    else:
        raise ValueError(
            f"Unknown credential source '{source}'. "
            f"Expected one of: env_file, uc_connection, gcloud_adc, databricks_secrets, uc_proxy"
        )
