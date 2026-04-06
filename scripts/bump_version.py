#!/usr/bin/env python3
"""Bump version strings across marketplace.json and plugin.json files.

Version format: YYYY.MM.DDNN where NN is a zero-padded two-digit sequence.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"


def compute_next_version(current_version: str, today: str) -> str:
    """Given a current version and today's date (YYYY.MM.DD), return the next version.

    If the current version's date matches today, increment NN.
    Otherwise, use today with NN=01.
    """
    parts = current_version.rsplit(".", 2)  # ['YYYY', 'MM', 'DDNN']
    if len(parts) == 3:
        cur_yyyy, cur_mm, cur_ddnn = parts
        cur_date = f"{cur_yyyy}.{cur_mm}.{cur_ddnn[:2]}"
    else:
        cur_date = ""

    if cur_date == today:
        seq = int(cur_ddnn[2:]) + 1
        dd = cur_ddnn[:2]
    else:
        today_parts = today.rsplit(".", 2)
        dd = today_parts[2]
        seq = 1

    today_parts = today.rsplit(".", 2)
    return f"{today_parts[0]}.{today_parts[1]}.{dd}{seq:02d}"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump plugin and marketplace versions.")
    parser.add_argument(
        "--plugin",
        action="append",
        dest="plugins",
        help="Plugin name(s) to bump. Omit to bump all.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing files.",
    )
    args = parser.parse_args()

    today = datetime.now().strftime("%Y.%m.%d")

    # Load marketplace.json
    marketplace = load_json(MARKETPLACE_JSON)
    current_meta_version = marketplace["metadata"]["version"]
    next_version = compute_next_version(current_meta_version, today)

    # Determine which plugins to bump
    all_plugin_names = [p["name"] for p in marketplace["plugins"]]
    if args.plugins:
        for name in args.plugins:
            if name not in all_plugin_names:
                print(f"Error: plugin '{name}' not found. Available: {all_plugin_names}", file=sys.stderr)
                sys.exit(1)
        target_plugins = args.plugins
    else:
        target_plugins = all_plugin_names

    # Collect changes
    changes = []

    # 1. Marketplace metadata version
    changes.append(
        f"  marketplace metadata.version: {current_meta_version} -> {next_version}"
    )

    # 2. Plugin entries in marketplace.json + individual plugin.json files
    for plugin_entry in marketplace["plugins"]:
        pname = plugin_entry["name"]
        if pname not in target_plugins:
            continue

        old_ver = plugin_entry["version"]
        changes.append(f"  marketplace plugins[{pname}].version: {old_ver} -> {next_version}")

        plugin_json_path = ROOT / "plugins" / pname / ".claude-plugin" / "plugin.json"
        if plugin_json_path.exists():
            pdata = load_json(plugin_json_path)
            old_pver = pdata.get("version", "unknown")
            changes.append(f"  {plugin_json_path.relative_to(ROOT)}: {old_pver} -> {next_version}")
        else:
            changes.append(f"  WARNING: {plugin_json_path.relative_to(ROOT)} not found")

    # Print summary
    mode = "DRY RUN" if args.dry_run else "BUMP"
    print(f"[{mode}] {current_meta_version} -> {next_version}")
    print(f"  today={today}, targets={target_plugins}")
    for c in changes:
        print(c)

    if args.dry_run:
        return

    # Apply changes
    marketplace["metadata"]["version"] = next_version
    for plugin_entry in marketplace["plugins"]:
        if plugin_entry["name"] in target_plugins:
            plugin_entry["version"] = next_version
    save_json(MARKETPLACE_JSON, marketplace)

    for pname in target_plugins:
        plugin_json_path = ROOT / "plugins" / pname / ".claude-plugin" / "plugin.json"
        if plugin_json_path.exists():
            pdata = load_json(plugin_json_path)
            pdata["version"] = next_version
            save_json(plugin_json_path, pdata)

    print("Done.")


if __name__ == "__main__":
    main()
