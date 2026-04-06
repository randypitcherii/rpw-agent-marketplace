#!/usr/bin/env python3
"""Publish a filtered copy of this repo to a public GitHub repository."""

from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import shutil
import subprocess
from pathlib import Path

import sys as _sys

_sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import cli_entry  # noqa: E402

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required: uv pip install pyyaml")


def load_config(config_path: Path) -> dict:
    """Load the .public-publish.yml config file."""
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def filter_files(files: list[str], config: dict) -> list[str]:
    """Filter a list of relative file paths based on exclusion config."""
    excluded_paths = config["exclude"].get("paths", [])
    patterns = config["exclude"].get("patterns", [])
    result = []
    for f in files:
        if any(f == p.rstrip("/") or f.startswith(p.rstrip("/") + "/") for p in excluded_paths):
            continue
        if _matches_any_pattern(f, patterns):
            continue
        result.append(f)
    return result


def _matches_any_pattern(filepath: str, patterns: list[str]) -> bool:
    """Check if a filepath matches any exclusion glob pattern."""
    if filepath.endswith(".example"):
        return False
    for pattern in patterns:
        if pattern.startswith("**/"):
            base_pattern = pattern[3:]
            if fnmatch.fnmatch(filepath, pattern) or fnmatch.fnmatch(filepath, base_pattern):
                return True
            parts = filepath.split("/")
            if any(fnmatch.fnmatch(part, base_pattern) for part in parts):
                return True
        elif fnmatch.fnmatch(filepath, pattern):
            return True
    return False


def patch_manifest(manifest: dict, excluded_paths: list[str]) -> dict:
    """Remove plugins whose source paths fall under excluded paths."""
    result = copy.deepcopy(manifest)
    result["plugins"] = [
        p
        for p in result["plugins"]
        if not any(
            p["source"].lstrip("./").startswith(ep.rstrip("/"))
            for ep in excluded_paths
        )
    ]
    return result


def sync_files(
    src_root: Path, dest_root: Path, files: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """Sync filtered files from src to dest. Returns (added, updated, removed)."""
    added, updated, removed = [], [], []

    for rel in files:
        src_file = src_root / rel
        dest_file = dest_root / rel
        if not src_file.exists():
            continue
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        existed = dest_file.exists()
        shutil.copy2(src_file, dest_file)
        if existed:
            updated.append(rel)
        else:
            added.append(rel)

    files_set = set(files)
    for dest_file in sorted(dest_root.rglob("*")):
        if dest_file.is_dir():
            continue
        rel = dest_file.relative_to(dest_root).as_posix()
        if rel.startswith(".git/") or rel == ".git":
            continue
        if rel not in files_set:
            dest_file.unlink()
            removed.append(rel)

    for dest_dir in sorted(dest_root.rglob("*"), reverse=True):
        if dest_dir.is_dir() and not any(dest_dir.iterdir()):
            rel = dest_dir.relative_to(dest_root).as_posix()
            if not rel.startswith(".git"):
                dest_dir.rmdir()

    return added, updated, removed


def get_tracked_files(repo_root: Path) -> list[str]:
    """Get list of git-tracked files."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def run_secret_scan(target_dir: Path) -> int:
    """Run public_release_gate.py against a directory. Returns 0 on success."""
    scripts_dir = Path(__file__).resolve().parent
    result = subprocess.run(
        [_sys.executable, str(scripts_dir / "public_release_gate.py"), "--repo-root", str(target_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    return result.returncode


def publish(
    repo_root: Path,
    config: dict,
    public_repo_dir: Path,
    *,
    dry_run: bool = False,
) -> int:
    """Run the full publish pipeline. Returns 0 on success."""
    print("Running secret scan on source repo...")
    if run_secret_scan(repo_root) != 0:
        print("ABORT: Source repo failed secret scan.")
        return 1

    all_files = get_tracked_files(repo_root)
    filtered = filter_files(all_files, config)
    print(f"Files: {len(all_files)} tracked, {len(filtered)} after filtering ({len(all_files) - len(filtered)} excluded)")

    if not dry_run:
        if not (public_repo_dir / ".git").is_dir():
            print(f"ABORT: {public_repo_dir} is not a git repository.")
            return 1
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=public_repo_dir,
            capture_output=True,
            text=True,
        )
        if status.stdout.strip():
            print(f"ABORT: Public repo at {public_repo_dir} has uncommitted changes.")
            return 1

    if dry_run:
        print("\n=== DRY RUN — files that would be published ===")
        for f in filtered:
            print(f"  {f}")
        print(f"\nTotal: {len(filtered)} files")
        return 0

    print("Syncing files to public repo...")
    added, updated, removed = sync_files(repo_root, public_repo_dir, filtered)

    manifest_path = public_repo_dir / ".claude-plugin" / "marketplace.json"
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as f:
            manifest = json.load(f)
        patched = patch_manifest(manifest, config["exclude"].get("paths", []))
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(patched, f, indent=2)
            f.write("\n")
        print("Patched marketplace.json (removed excluded plugins)")

    print("Running secret scan on publish output...")
    if run_secret_scan(public_repo_dir) != 0:
        print("ABORT: Published output failed secret scan. Review and fix before retrying.")
        return 1

    print("\n=== Sync Summary ===")
    print(f"  Added:   {len(added)}")
    print(f"  Updated: {len(updated)}")
    print(f"  Removed: {len(removed)}")

    if not added and not updated and not removed:
        print("No changes to publish.")
        return 0

    from datetime import date

    subprocess.run(["git", "add", "-A"], cwd=public_repo_dir, check=True)
    commit_msg = f"publish: sync from private repo ({date.today().isoformat()})"
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=public_repo_dir, check=True)
    print(f"Committed: {commit_msg}")

    subprocess.run(["git", "push"], cwd=public_repo_dir, check=True)
    print("Pushed to public remote.")

    # Tag with the marketplace version for pinning support
    manifest_path = public_repo_dir / ".claude-plugin" / "marketplace.json"
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as f:
            version = json.load(f).get("metadata", {}).get("version")
        if version:
            tag = f"v{version}"
            tag_result = subprocess.run(
                ["git", "tag", tag],
                cwd=public_repo_dir,
                capture_output=True,
                text=True,
            )
            if tag_result.returncode == 0:
                subprocess.run(["git", "push", "--tags"], cwd=public_repo_dir, check=True)
                print(f"Tagged: {tag}")
            else:
                print(f"Tag {tag} already exists, skipping.")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish filtered repo to public GitHub.")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Private repo root (default: current directory).",
    )
    parser.add_argument(
        "--config",
        default=".public-publish.yml",
        help="Path to exclusion config (default: .public-publish.yml).",
    )
    parser.add_argument(
        "--public-repo",
        default=".public-repo",
        help="Path to local clone of public repo (default: .public-repo).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be published without modifying anything.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    config_path = repo_root / args.config
    public_repo_dir = (repo_root / args.public_repo).resolve()

    config = load_config(config_path)

    return publish(repo_root, config, public_repo_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    cli_entry(main)
