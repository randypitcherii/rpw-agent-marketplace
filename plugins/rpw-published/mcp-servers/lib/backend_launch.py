"""Start a ``uv run --project`` MCP backend without re-resolving it every time (#2623).

Plain ``uv run --project <dir>`` re-resolves the project on every start, which costs
network round-trips through a registry proxy (#428). Each backend's venv is therefore
synced only when its ``pyproject.toml`` changed since the last sync, and the backend
then starts with ``--no-sync``. The stamp is the file glean's and fevm's ``run_mcp.sh``
already write (``.venv/.rpw-pyproject.sha256``), so every launcher shares one gate.

mcporter's keep-alive daemon starts the backends itself (ADR-2026-10-27), so this gate
can no longer live in an aggregator. The generated mcporter config runs every
``uv run --project`` backend through this file instead::

    uv run --no-project python <plugin>/mcp-servers/lib/backend_launch.py \\
        run --project <dir> python <dir>/run_mcp.py

Stdlib only: it runs before any backend venv exists. On any failure the original
command runs unchanged, so the slow path is always the fallback, never a wrong one.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

STAMP_NAME = ".rpw-pyproject.sha256"  # shared with glean's and fevm's run_mcp.sh
# Set by the `uv run --no-project` wrapper that starts this file. They describe that
# wrapper's interpreter, never the backend's own project.
_NOT_FORWARDED = frozenset(
    {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONHOME", "PYTHONPATH", "UV_RUN_RECURSION_DEPTH"}
)


def _log(message: str) -> None:
    print(f"[rpw-mcp] {message}", file=sys.stderr, flush=True)


def uv_project(command: str, args: list[str]) -> str | None:
    """The ``--project`` dir of a ``uv run --project <dir> ...`` launch that may skip sync."""
    if Path(command).name != "uv" or not args or args[0] != "run":
        return None
    if "--project" not in args or "--no-sync" in args or "--frozen" in args:
        return None
    index = args.index("--project") + 1
    return args[index] if index < len(args) else None


def child_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    return {k: v for k, v in source.items() if k not in _NOT_FORWARDED}


def ensure_synced(project: str | Path) -> bool:
    """True when ``project``'s venv matches its ``pyproject.toml``, syncing it if not."""
    root = Path(project)
    stamp = root / ".venv" / STAMP_NAME
    try:
        want = hashlib.sha256((root / "pyproject.toml").read_bytes()).hexdigest()
        if stamp.is_file() and stamp.read_text(encoding="utf-8") == want:
            return True
        _log(f"syncing {root.name} (first run or pyproject.toml changed)")
        proc = subprocess.run(
            ["uv", "sync", "--project", str(root)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=child_env(),
            check=False,
        )
        if proc.returncode != 0:
            _log(
                f"uv sync failed for {root}; starting without the fast path: "
                f"{proc.stderr.decode(errors='replace').strip()[-300:]}"
            )
            return False
        stamp.write_text(want, encoding="utf-8")
        return True
    except OSError as exc:
        _log(f"fast path unavailable for {root}: {exc}")
        return False


def fast_args(command: str, args: list[str]) -> list[str]:
    """``args`` with ``--no-sync`` when the backend's venv is known current."""
    project = uv_project(command, args)
    if project is None or not ensure_synced(project):
        return list(args)
    return [args[0], "--no-sync", *args[1:]]


def main(argv: list[str] | None = None) -> None:
    """Exec ``uv <argv>``, with ``--no-sync`` when the project is current."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.exit("usage: backend_launch.py run --project <dir> <command> [args...]")
    os.execvpe("uv", ["uv", *fast_args("uv", args)], child_env())


if __name__ == "__main__":
    main()
