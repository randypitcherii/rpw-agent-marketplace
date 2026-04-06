"""
Shared env-loading logic for MCP server wrappers.

Provides APP_ENV selection (dev/test/prod), env file resolution,
dotenv loading, and required-variable validation.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

VALID_APP_ENVS = {"dev", "test", "prod"}


def get_app_env() -> str:
    app_env = os.getenv("APP_ENV", "dev").strip().lower()
    if app_env not in VALID_APP_ENVS:
        raise ValueError(
            f"Invalid APP_ENV '{app_env}'. Expected one of: {sorted(VALID_APP_ENVS)}"
        )
    return app_env


def resolve_env_path(base_dir: Path, app_env: str) -> Path:
    return base_dir / f"{app_env}.env"


def load_selected_env(base_dir: Path) -> tuple[str, Path]:
    app_env = get_app_env()
    env_path = resolve_env_path(base_dir, app_env)
    if not env_path.exists():
        raise FileNotFoundError(
            f"Env file not found at {env_path}. Copy template.env to {app_env}.env first."
        )
    load_dotenv(env_path)
    return app_env, env_path


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
            databricks_profile=config.get("databricks_profile", "logfood"),
        )
    elif source == "gcloud_adc":
        from lib.resolvers.gcloud_adc import resolve
        resolve(
            env_var_map=config["env_var_map"],
        )
    else:
        raise ValueError(
            f"Unknown credential source '{source}'. "
            f"Expected one of: env_file, uc_connection, gcloud_adc"
        )
