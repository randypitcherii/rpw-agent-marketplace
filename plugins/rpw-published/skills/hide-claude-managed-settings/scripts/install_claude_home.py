#!/usr/bin/env python3
"""Install the claude-home launcher + Seatbelt profile.

Idempotent. Copies the bundled launcher and profile into place, then runs
`claude-home --check` to verify the boundary.

Usage:
  uv run --no-project python install_claude_home.py [--dry-run] [--bin-dir DIR] [--config-dir DIR]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
LAUNCHER = ASSETS / "claude-home"
UNATTENDED = ASSETS / "claude-home-unattended"
PROFILE = ASSETS / "claude-home.sb"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument(
        "--bin-dir",
        default=str(Path.home() / ".local/bin"),
        help="where to install the launcher (default: ~/.local/bin)",
    )
    ap.add_argument(
        "--config-dir",
        default=str(Path.home() / ".config/claude-home"),
        help="where to install the profile (default: ~/.config/claude-home)",
    )
    args = ap.parse_args()

    bin_dir = Path(args.bin_dir).expanduser()
    config_dir = Path(args.config_dir).expanduser()
    dst_launcher = bin_dir / "claude-home"
    dst_unattended = bin_dir / "claude-home-unattended"
    dst_profile = config_dir / "claude-home.sb"

    for src in (LAUNCHER, UNATTENDED, PROFILE):
        if not src.is_file():
            print(f"error: bundled asset missing: {src}", file=sys.stderr)
            return 1

    plan = [
        (LAUNCHER, dst_launcher, 0o755),
        (UNATTENDED, dst_unattended, 0o755),
        (PROFILE, dst_profile, 0o644),
    ]

    print("Install plan:")
    for src, dst, mode in plan:
        marker = " (overwrite)" if dst.exists() else ""
        print(f"  {src.name} -> {dst}{marker}")
    print(f"  then: {dst_launcher} --check")

    if args.dry_run:
        print("dry-run: nothing written")
        return 0

    bin_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    for src, dst, mode in plan:
        shutil.copyfile(src, dst)
        dst.chmod(mode)
        print(f"installed {dst}")

    print("\nVerifying:")
    result = subprocess.run([str(dst_launcher), "--check"])
    if result.returncode != 0:
        print("error: post-install check failed", file=sys.stderr)
        return result.returncode

    if shutil.which("claude-home") is None:
        print(f"\nnote: {bin_dir} is not on PATH — add it to your shell profile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
