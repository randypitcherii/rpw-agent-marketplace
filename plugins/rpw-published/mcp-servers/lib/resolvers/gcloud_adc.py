"""Resolver that loads credentials from gcloud Application Default Credentials."""

import json
import os
from pathlib import Path

from lib.errors import CredentialResolutionError

ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def resolve(env_var_map: dict[str, str], adc_path: Path = ADC_PATH) -> None:
    """Read gcloud ADC JSON and set env vars per env_var_map.

    An empty env_var_map is a no-op — use this for servers that call gcloud at runtime
    instead of reading the JSON directly.
    """
    if not env_var_map:
        return

    if not adc_path.exists():
        raise CredentialResolutionError(
            f"gcloud Application Default Credentials not found at {adc_path}",
            remediation="gcloud auth application-default login",
            kind="gcloud_adc_missing",
            context={"adc_path": str(adc_path)},
        )

    with open(adc_path) as f:
        adc = json.load(f)

    for field, env_var in env_var_map.items():
        if field not in adc:
            raise CredentialResolutionError(
                f"Field '{field}' not found in gcloud ADC file: {adc_path}. "
                f"Available fields: {list(adc.keys())}",
                remediation="gcloud auth application-default login",
                kind="gcloud_adc_field_missing",
                context={
                    "field": field,
                    "available_fields": list(adc.keys()),
                    "adc_path": str(adc_path),
                },
            )
        os.environ[env_var] = adc[field]
