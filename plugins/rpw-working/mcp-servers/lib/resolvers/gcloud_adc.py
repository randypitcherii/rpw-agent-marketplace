"""Resolver that loads credentials from gcloud Application Default Credentials."""

import json
import os
from pathlib import Path

ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def resolve(env_var_map: dict[str, str], adc_path: Path = ADC_PATH) -> None:
    """Read gcloud ADC JSON and set env vars per env_var_map.

    Args:
        env_var_map: Mapping of ADC JSON field name -> environment variable name.
        adc_path: Path to the ADC JSON file (default: ~/.config/gcloud/application_default_credentials.json).

    Raises:
        RuntimeError: If the ADC file does not exist or a mapped field is missing.
    """
    if not adc_path.exists():
        raise RuntimeError(f"gcloud ADC file not found: {adc_path}")

    with open(adc_path) as f:
        adc = json.load(f)

    for field, env_var in env_var_map.items():
        if field not in adc:
            raise RuntimeError(f"Field '{field}' not found in gcloud ADC file: {adc_path}")
        os.environ[env_var] = adc[field]
