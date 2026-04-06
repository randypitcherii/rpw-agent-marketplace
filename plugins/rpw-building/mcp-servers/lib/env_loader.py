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
