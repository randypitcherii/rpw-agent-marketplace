"""Shared utilities for marketplace scripts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable


def load_json(path: Path) -> dict:
    """Load and parse a JSON file, raising FileNotFoundError if missing."""
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict, indent: int = 2) -> None:
    """Write a dict to a JSON file with trailing newline."""
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent)
        f.write("\n")


def cli_entry(main_func: Callable[[], int]) -> None:
    """CLI entry point wrapper with consistent error handling."""
    try:
        raise SystemExit(main_func())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensive error boundary
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
