"""Validate scopes on gcloud Application Default Credentials (ADC).

The scope registry itself lives in :mod:`server_registry`.  This module is a
small, dependency-free command-line check so the setup skill can validate the
same grant that ADC-backed MCP servers use.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

from server_registry import GOOGLE_ADC_SCOPES, SERVERS, adc_scope_union

TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"


class IncompleteAdcScopesError(RuntimeError):
    """A valid ADC token does not include scopes required by enabled servers."""

    def __init__(self, missing_scopes: Iterable[str], enabled_servers: Iterable[str]):
        self.missing_scopes = tuple(sorted(missing_scopes))
        self.enabled_servers = tuple(sorted(enabled_servers))
        command = remediation_command(self.enabled_servers)
        super().__init__(
            "gcloud Application Default Credentials are valid but missing required "
            f"scopes: {', '.join(self.missing_scopes)}.\n"
            f"Re-authenticate with the full enabled ADC scope union:\n{command}\n"
            "Warning: `gcloud auth application-default login --scopes=...` replaces "
            "the existing ADC grant; use this full union rather than a single-server list."
        )


def enabled_adc_consumers(server_names: Iterable[str] | None = None) -> tuple[str, ...]:
    """Return enabled gcloud-ADC consumer names, rejecting non-ADC consumers."""
    available = tuple(
        name for name, entry in GOOGLE_ADC_SCOPES.items() if entry["credential_source"] == "gcloud_adc"
    )
    if server_names is None:
        return available
    requested = tuple(server_names)
    unknown = set(requested).difference(GOOGLE_ADC_SCOPES).difference(SERVERS)
    if unknown:
        raise ValueError(f"Unknown Google ADC consumer(s): {', '.join(sorted(unknown))}")
    wrong_source = [
        name
        for name in requested
        if name not in GOOGLE_ADC_SCOPES
        or GOOGLE_ADC_SCOPES[name]["credential_source"] != "gcloud_adc"
    ]
    if wrong_source:
        raise ValueError(
            "Not gcloud ADC consumers (do not add their scopes to ADC): "
            f"{', '.join(sorted(wrong_source))}"
        )
    return requested


def remediation_command(server_names: Iterable[str] | None = None) -> str:
    """Return the one replacement-safe login command for enabled ADC consumers."""
    scopes = adc_scope_union(enabled_adc_consumers(server_names))
    return "gcloud auth application-default login --scopes=" + ",".join(scopes)


def missing_scopes(granted_scopes: Iterable[str], server_names: Iterable[str] | None = None) -> tuple[str, ...]:
    """Return required enabled-ADC scopes absent from a token-info scope set."""
    return tuple(sorted(set(adc_scope_union(enabled_adc_consumers(server_names))).difference(granted_scopes)))


def token_scopes(
    access_token: str,
    opener: Callable[..., object] = urlopen,
) -> set[str]:
    """Query Google's token-info endpoint and return its space-delimited scopes."""
    url = f"{TOKEN_INFO_URL}?{urlencode({'access_token': access_token})}"
    with opener(url, timeout=10) as response:  # nosec B310 -- fixed Google endpoint
        payload = json.loads(response.read().decode("utf-8"))
    return set(payload.get("scope", "").split())


def active_adc_scopes(run: Callable[..., object] = subprocess.run) -> set[str]:
    """Read the active *ADC* token, never the separate gcloud user credential."""
    completed = run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        check=True,
        capture_output=True,
        text=True,
    )
    return token_scopes(completed.stdout.strip())


def validate_active_adc(server_names: Iterable[str] | None = None) -> None:
    """Raise an actionable error unless active ADC covers every enabled consumer."""
    consumers = enabled_adc_consumers(server_names)
    missing = missing_scopes(active_adc_scopes(), consumers)
    if missing:
        raise IncompleteAdcScopesError(missing, consumers)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate required gcloud ADC OAuth scopes.")
    parser.add_argument(
        "--enabled-server",
        action="append",
        dest="servers",
        help="ADC-backed server to validate; repeat for each configured server (default: all ADC consumers)",
    )
    args = parser.parse_args()
    try:
        validate_active_adc(args.servers)
    except (subprocess.CalledProcessError, OSError) as error:
        print(
            "gcloud Application Default Credentials are unavailable — run: "
            + remediation_command(args.servers),
            file=sys.stderr,
        )
        raise SystemExit(1) from error
    except IncompleteAdcScopesError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
    print("gcloud Application Default Credentials include all required enabled scopes.")


if __name__ == "__main__":
    main()
