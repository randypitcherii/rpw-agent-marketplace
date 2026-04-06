#!/usr/bin/env python3
"""Bump changed plugin versions in .claude-plugin/marketplace.json.

Version format: YYYY.MM.DDNN
- YYYY is the current year
- MM/DD are zero-padded month/day
- NN is a zero-padded, monotonic intra-day counter
"""

from __future__ import annotations

import argparse
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Iterable

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import cli_entry, load_json, save_json  # noqa: E402


VERSION_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})(\d{2})$")
MARKETPLACE_PATH = Path(".claude-plugin/marketplace.json")
PLUGIN_ROOT = Path("plugins")


def _run_git_diff_names(diff_range: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", diff_range],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"git diff failed for range '{diff_range}'"
            + (f": {stderr}" if stderr else "")
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _default_pr_field() -> str:
    def _git_stdout(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], check=False, capture_output=True, text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    remotes = _git_stdout("remote")
    if not remotes:
        return "Unavailable (no remote configured)"

    commit_id = _git_stdout("rev-parse", "--short", "HEAD")
    if commit_id:
        return f"`{commit_id}`"

    return "Unavailable (no remote configured)"


def _load_marketplace(path: Path) -> dict:
    return load_json(path)


def _save_marketplace(path: Path, data: dict) -> None:
    save_json(path, data)


def _append_release_log(
    path: Path,
    version: str,
    plugin_names: list[str],
    pr_field: str,
    checks_field: str,
) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Release log file not found: {path}")

    content = path.read_text(encoding="utf-8")
    marker = "## Releases"
    if marker not in content:
        raise ValueError(f"Release log missing required section header: {marker}")

    day = version[:10].replace(".", "-")
    scope = ", ".join(f"`{name}`" for name in sorted(plugin_names))
    entry = (
        f"\n## {day} - {version}\n\n"
        f"- **Type:** release\n"
        f"- **Scope:** {scope}\n"
        f"- **PR:** {pr_field}\n"
        f"- **Summary:** Automated production merge version bump.\n"
        f"- **Checks:** {checks_field}\n"
    )
    updated = content.replace(marker, marker + entry, 1)
    path.write_text(updated, encoding="utf-8")


def _sync_plugin_json_version(plugin_name: str, version: str) -> Path | None:
    """Write the version into the plugin's own plugin.json manifest."""
    plugin_json = PLUGIN_ROOT / plugin_name / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return None
    data = load_json(plugin_json)
    data["version"] = version
    save_json(plugin_json, data)
    return plugin_json


def _normalize_source_dir(source: str) -> str:
    return source.removeprefix("./").removesuffix("/")


def _changed_plugin_names(plugins: list[dict], changed_files: Iterable[str]) -> list[str]:
    files = [p.lstrip("./") for p in changed_files]
    changed = []
    for plugin in plugins:
        name = plugin.get("name")
        source = plugin.get("source", "")
        source_dir = _normalize_source_dir(source)
        if not name or not source_dir:
            continue
        prefix = f"{source_dir}/"
        if any(path == source_dir or path.startswith(prefix) for path in files):
            changed.append(name)
    return sorted(set(changed))


def _next_versions(existing_versions: Iterable[str], bumps_needed: int, today: date) -> list[str]:
    day_prefix = f"{today.year:04d}.{today.month:02d}.{today.day:02d}"
    max_counter = 0
    for version in existing_versions:
        match = VERSION_RE.match(version or "")
        if not match:
            continue
        if version.startswith(day_prefix):
            max_counter = max(max_counter, int(match.group(4)))
    max_next_counter = max_counter + bumps_needed
    if max_next_counter > 99:
        raise ValueError(
            f"Cannot allocate {bumps_needed} version bump(s) for {day_prefix}: "
            f"would exceed daily counter limit 99"
        )

    return [f"{day_prefix}{counter:02d}" for counter in range(max_counter + 1, max_next_counter + 1)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bump versions for changed marketplace plugins only."
    )
    parser.add_argument(
        "--marketplace",
        default=str(MARKETPLACE_PATH),
        help="Path to marketplace JSON file (default: .claude-plugin/marketplace.json).",
    )
    parser.add_argument(
        "--diff-range",
        default="HEAD^..HEAD",
        help="Git diff range used to detect changed plugins (default: HEAD^..HEAD).",
    )
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="Explicit changed file path(s). If provided, git diff is skipped.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned bumps without writing files.",
    )
    parser.add_argument(
        "--release-log",
        default="",
        help="Optional release log path to append with new release entry on write.",
    )
    parser.add_argument(
        "--pr-field",
        default="",
        help=(
            "Optional value for release-log PR field. Defaults to short commit ID when remotes "
            "exist, otherwise 'Unavailable (no remote configured)'."
        ),
    )
    parser.add_argument(
        "--checks-field",
        default="`make verify` ✅",
        help="Value for release-log Checks field (default: `make verify` ✅).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    marketplace_path = Path(args.marketplace)
    marketplace = _load_marketplace(marketplace_path)
    plugins = marketplace.get("plugins", [])
    if not isinstance(plugins, list):
        raise ValueError("marketplace.json field 'plugins' must be a list")

    if args.changed_file:
        changed_files = args.changed_file
    else:
        changed_files = _run_git_diff_names(args.diff_range)

    changed_names = _changed_plugin_names(plugins, changed_files)
    if not changed_names:
        print("No plugin changes detected; no version bump needed.")
        return 0

    existing_versions = [str(plugin.get("version", "")) for plugin in plugins]
    existing_versions.append(str(marketplace.get("metadata", {}).get("version", "")))
    next_version = _next_versions(
        existing_versions=existing_versions,
        bumps_needed=1,
        today=date.today(),
    )[0]

    updated = []
    for plugin in plugins:
        name = plugin.get("name")
        if name in changed_names:
            old = str(plugin.get("version", ""))
            plugin["version"] = next_version
            updated.append((name, old, next_version))

    metadata = marketplace.get("metadata", {})
    metadata_old = str(metadata.get("version", ""))
    metadata["version"] = next_version

    if args.dry_run:
        print("Dry run: planned version updates")
        if metadata_old != next_version:
            print(f"- metadata.version: {metadata_old or '<unset>'} -> {next_version}")
    else:
        _save_marketplace(marketplace_path, marketplace)
        print(f"Updated {marketplace_path}")
        for name, _old, new in updated:
            synced = _sync_plugin_json_version(name, new)
            if synced:
                print(f"Synced {synced}")
        if args.release_log:
            pr_field = args.pr_field.strip() or _default_pr_field()
            checks_field = args.checks_field.strip()
            _append_release_log(
                Path(args.release_log),
                next_version,
                changed_names,
                pr_field=pr_field,
                checks_field=checks_field,
            )
            print(f"Updated {args.release_log}")

    for name, old, new in updated:
        print(f"- {name}: {old or '<unset>'} -> {new}")

    return 0


if __name__ == "__main__":
    cli_entry(main)
