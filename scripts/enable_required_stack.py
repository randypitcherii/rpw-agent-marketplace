#!/usr/bin/env python3
"""Enable the required plugin stack with no profile customization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import cli_entry  # noqa: E402

DEFAULT_SETTINGS_PATH = ".claude/settings.local.json"

# Single required stack. Do not add profiles/options here.
REQUIRED_PLUGINS = (
    "superpowers",
    "beads",
    "code-context",
    "context-mode",
    "rpw-building",
    "rpw-working",
    "rpw-databricks",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enable the required plugin stack in local Claude settings."
    )
    parser.add_argument(
        "--settings-path",
        default=DEFAULT_SETTINGS_PATH,
        help=f"Target settings file (default: {DEFAULT_SETTINGS_PATH}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resulting JSON without writing changes.",
    )
    return parser.parse_args()


def _load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Settings file must contain a JSON object: {path}")
    return data


def _apply_required_stack(settings: dict) -> dict:
    enabled = settings.get("enabledPlugins")
    if not isinstance(enabled, dict):
        enabled = {}
    for plugin in REQUIRED_PLUGINS:
        enabled[plugin] = True
    settings["enabledPlugins"] = enabled
    return settings


def _write_settings(path: Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(settings, indent=2, sort_keys=True) + "\n"
    path.write_text(serialized, encoding="utf-8")


def main() -> int:
    args = parse_args()
    path = Path(args.settings_path)
    settings = _load_settings(path)
    updated = _apply_required_stack(settings)

    if args.dry_run:
        print(json.dumps(updated, indent=2, sort_keys=True))
        return 0

    _write_settings(path, updated)
    print(f"Enabled required stack in {path}")
    return 0


if __name__ == "__main__":
    cli_entry(main)
