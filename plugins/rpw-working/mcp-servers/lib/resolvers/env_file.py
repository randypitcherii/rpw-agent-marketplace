"""
Env-file credential resolver.

Reads APP_ENV from os.environ (default "dev"), loads {APP_ENV}.env from
base_dir using python-dotenv, then validates all required vars are present.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def resolve(base_dir: Path, env_var_map: dict, required: list[str]) -> None:
    """
    Load credentials from an env file and validate required vars are present.

    Args:
        base_dir: Directory containing the .env files (e.g. dev.env, prod.env).
        env_var_map: Reserved for future use (e.g. remapping var names).
        required: List of env var names that must be present after loading.

    Raises:
        FileNotFoundError: If the {APP_ENV}.env file does not exist.
        EnvironmentError: If any required vars are missing after loading.
    """
    app_env = os.environ.get("APP_ENV", "dev").strip().lower()
    env_path = base_dir / f"{app_env}.env"

    if not env_path.exists():
        raise FileNotFoundError(
            f"Env file not found: {env_path}. "
            f"Copy template.env to {app_env}.env first."
        )

    load_dotenv(env_path)

    missing = [var for var in required if not os.getenv(var)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables after loading {env_path}: "
            f"{', '.join(missing)}"
        )
