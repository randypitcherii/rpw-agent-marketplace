"""`rpw-mcp`: run the `rpw` MCP aggregator from a uvx install (#2242, #894 slice B).

The wheel carries this plugin's `mcp-servers/` tree under `plugin/`, so

    uvx --from "git+<repo>#subdirectory=plugins/rpw-published" rpw-mcp

serves the same backends an installed Claude Code plugin does, on a host with only
`uv`.

**The tree is copied out of the install before it runs.** uvx installs into uv's own
cache, and uv refuses to sync a project inside its cache, so each backend's
`uv run --project` would fail there. The tree is copied once per content hash to
`~/.cache/rpw-mcp/trees/`, outside uv's cache. It then behaves exactly like an installed
plugin, with each backend's venv inside its own copy.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

PACKAGED = Path(__file__).resolve().parent / "plugin"
TREES_ENV = "RPW_MCP_TREES_DIR"


def _digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def materialize(packaged: Path = PACKAGED) -> Path:
    """A plugin-root copy of the packaged tree outside uv's cache; reused when unchanged."""
    trees = Path(os.environ.get(TREES_ENV) or Path.home() / ".cache" / "rpw-mcp" / "trees")
    target = trees / f"rpw-mcp-{_digest(packaged)}"
    if (target / "mcp-servers" / "rpw" / "servers.json").is_file():
        return target
    trees.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".rpw-mcp-", dir=trees))
    shutil.copytree(packaged, staging, dirs_exist_ok=True)
    for script in staging.rglob("*.sh"):
        script.chmod(0o755)
    try:
        staging.rename(target)
    except OSError:  # a concurrent start won the race; use its copy
        shutil.rmtree(staging, ignore_errors=True)
    return target


def main() -> None:
    if not (PACKAGED / "mcp-servers" / "rpw" / "servers.json").is_file():
        sys.exit(f"rpw-mcp: packaged MCP tree missing at {PACKAGED}")
    root = materialize()
    servers = root / "mcp-servers"
    sys.path.insert(0, str(servers))
    from lib import aggregator

    aggregator.run("rpw", servers / "rpw")
