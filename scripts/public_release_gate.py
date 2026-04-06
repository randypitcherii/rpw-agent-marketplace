#!/usr/bin/env python3
"""Public-release guardrails to reduce accidental secret leaks."""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import cli_entry  # noqa: E402

REQUIRED_ACK_VALUE = "I_ACKNOWLEDGE_PUBLIC_REPO_RELEASE"
CONFIRM_ENV_VAR = "PUBLIC_REPO_RELEASE_CONFIRM"

BLOCKED_PATH_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.p12",
    "*.pfx",
    "*.key",
    "**/id_rsa",
    "**/id_ed25519",
    "**/credentials*.json",
)

ALLOWED_PATH_PATTERNS = (
    ".env.example",
    "*.env.example",
    "*.local.example.md",
)

LEAK_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
)

SKIP_DIRS = {".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "venv"}
MAX_BYTES = 2 * 1024 * 1024


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _is_allowed_path(relative_path: str) -> bool:
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in ALLOWED_PATH_PATTERNS)


def _is_blocked_path(relative_path: str) -> bool:
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in BLOCKED_PATH_PATTERNS)


def _check_files(root: Path) -> tuple[list[str], list[str]]:
    """Single-pass check for blocked paths and secret-like content."""
    path_issues: list[str] = []
    content_issues: list[str] = []
    for path in _iter_files(root):
        rel = path.relative_to(root).as_posix()
        if _is_allowed_path(rel):
            continue
        if _is_blocked_path(rel):
            path_issues.append(f"Blocked file path pattern matched: {rel}")
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in LEAK_PATTERNS:
            if pattern.search(content):
                content_issues.append(f"Secret-like pattern '{pattern.pattern}' found in {rel}")
    return path_issues, content_issues


def _flag_path_leaks(root: Path) -> list[str]:
    path_issues, _ = _check_files(root)
    return path_issues


def _flag_content_leaks(root: Path) -> list[str]:
    _, content_issues = _check_files(root)
    return content_issues


def _validate_confirmation(require_confirmation: bool, confirmation_value: str) -> None:
    if not require_confirmation:
        return
    if confirmation_value.strip() != REQUIRED_ACK_VALUE:
        raise ValueError(
            f"{CONFIRM_ENV_VAR} must equal '{REQUIRED_ACK_VALUE}' to run a public release"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run public-repo release checks and optional manual confirmation gate."
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root to scan (default: current directory).",
    )
    parser.add_argument(
        "--require-confirmation",
        action="store_true",
        help=f"Require explicit {CONFIRM_ENV_VAR} acknowledgement value.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    confirmation_value = os.environ.get(CONFIRM_ENV_VAR, "")
    _validate_confirmation(
        require_confirmation=args.require_confirmation,
        confirmation_value=confirmation_value,
    )

    path_issues, content_issues = _check_files(repo_root)
    issues = path_issues + content_issues

    if issues:
        print("Public release gate failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Public release gate passed: no blocked paths or secret-like content found.")
    return 0


if __name__ == "__main__":
    cli_entry(main)
