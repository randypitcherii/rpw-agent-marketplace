"""The rpw MCP runtime: installed plugins -> one mcporter config, env and command (#2623).

mcporter (https://github.com/openclaw/mcporter, MIT) runs every rpw backend in one
per-user keep-alive daemon. Both shell and MCP callers go through it, each over a
``mcporter serve --stdio`` child: the plugin's one `rpw` MCP entry (``front.py``) and
the `rpw-mcp-cli` shim. This module is the one place that decides what they run.
Decision and evidence: ``docs/decisions/ADR-2026-10-28-mcporter-runtime.md``.

What it does, and why:

- **Discovery.** Each plugin lists its backends in ``mcp-servers/rpw/servers.json``
  (the ``.mcp.json`` ``mcpServers`` shape). ``rpw-published`` is always there;
  ``rpw-private`` joins when installed, and its absence is silent. Installs come from
  the Claude Code plugin cache; with no cache (a Sandbox, a skills-only harness) they
  come from the unpacked internal release (#2630, :func:`release_plugins_root`).
- **One config.** All found backends go into one mcporter config with
  ``lifecycle: keep-alive``, an explicit ``cwd`` and ``imports: []`` (mcporter otherwise
  merges every Cursor/Claude/Codex config on the host). It is written owner-only,
  and only when its content changed.
- **The fast start.** A ``uv run --project`` backend is started through
  ``lib/backend_launch.py``, which syncs only when ``pyproject.toml`` changed and then
  starts with ``--no-sync`` (#428). Glean's and fevm's ``run_mcp.sh`` do the same.
- **A deterministic environment.** mcporter pools a connection by its whole effective
  definition, *including the caller's environment*: one differing variable (``OLDPWD``,
  a terminal session id, a harness marker) opens a second, cold backend process.
  Every caller therefore hands mcporter :func:`runtime_env`, an allowlisted env with
  a fixed ``PATH``, so the CLI from any cwd and the MCP entry from any harness share
  one warm connection per backend. Variables that do change behavior (``APP_ENV``,
  ``*_SEND_CONFIRM``, profile pins) pass through and so, correctly, get their own pool.
- **A pinned mcporter.** :data:`MCPORTER_VERSION`, installed once under
  ``~/.rpw/mcp/runtime/``, with ``npx -y mcporter@<version>`` as the fallback.

Stdlib only: the shell CLI imports it with no venv.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MCPORTER_VERSION = "0.16.0"
MIN_NODE_MAJOR = 24

PLUGIN_ROOT_PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"
BACKENDS_MANIFEST = Path("mcp-servers") / "rpw" / "servers.json"
CACHE_ENV = "RPW_MCP_CACHE_ROOT"
HOME_ENV = "RPW_MCP_HOME"  # where configs and the pinned mcporter live
MCPORTER_BIN_ENV = "RPW_MCPORTER_BIN"  # an explicit mcporter executable
PASSTHROUGH_ENV = "RPW_MCP_ENV_PASSTHROUGH"  # extra names, `PREFIX*` for a prefix
PATH_ENV = "RPW_MCP_PATH"  # replaces the canonical PATH below

# Set identically by every caller, because each is part of the daemon's connection key:
# - MCPORTER_DAEMON_TIMEOUT_MS: the daemon client's own wait on one operation. Its
#   default is 30s, below a slow tool (glean_chat answers or hands back a handle at
#   ~40s), and `serve` passes no per-call timeout of its own.
# - TERM: the MCP SDK's stdio client copies the caller's TERM into the child env when
#   the env lacks one, so a CLI run from a terminal and the entry run by a harness
#   would otherwise each get their own backend.
DAEMON_TIMEOUT_MS = 120_000
_FIXED = {"MCPORTER_DAEMON_TIMEOUT_MS": str(DAEMON_TIMEOUT_MS), "TERM": "dumb"}

# How long an idle backend stays up. Long enough that a session's calls stay warm,
# short enough that a dozen idle Python servers do not sit in memory overnight.
IDLE_TIMEOUT_MS = 2 * 60 * 60 * 1000

# --------------------------------------------------------------------------- env

_EXACT = frozenset(
    {
        "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "TZ", "APP_ENV",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "no_proxy", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL",
        "MCPORTER_DAEMON_DIR",  # a broker control, not part of the connection identity
    }
)
# Families the rpw backends (and the Databricks SDK and uv under them) read.
_PREFIXES = (
    "LC_", "XDG_", "DATABRICKS_", "UC_", "GDOCS_", "GOOGLE_", "GCLOUD_", "GEMINI_",
    "SLACK_", "FEVM_", "GLEAN_", "JIRA_", "EXA_", "NOTIFY_ME_", "IMSG_", "MLFLOW_",
    "RPW_", "UV_",
)
_SUFFIXES = ("_SEND_CONFIRM",)
# Never forwarded even inside an allowed family: they describe the caller's own
# process (a `uv run` wrapper, this runtime's controls), not the backend.
_DENIED = frozenset(
    {"UV_PROJECT_ENVIRONMENT", "UV_RUN_RECURSION_DEPTH", "VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"}
)
_DENIED_PREFIXES = ("RPW_MCP_", "UV_INTERNAL_")

_CANONICAL_PATH = (
    "~/.local/bin", "~/.cargo/bin", "/opt/homebrew/bin", "/opt/homebrew/sbin",
    "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
)


def _passthrough(environ: dict[str, str]) -> tuple[set[str], tuple[str, ...]]:
    names: set[str] = set()
    prefixes: list[str] = []
    for raw in (environ.get(PASSTHROUGH_ENV) or "").split(","):
        item = raw.strip()
        if item.endswith("*") and len(item) > 1:
            prefixes.append(item[:-1])
        elif item:
            names.add(item)
    return names, tuple(prefixes)


def _allowed(key: str, extra_names: set[str], extra_prefixes: tuple[str, ...]) -> bool:
    if key in extra_names or key.startswith(extra_prefixes or ("\0",)):
        return True
    if key in _DENIED or key.startswith(_DENIED_PREFIXES):
        return False
    return key in _EXACT or key.startswith(_PREFIXES) or key.endswith(_SUFFIXES)


def canonical_path(environ: dict[str, str] | None = None) -> str:
    """A PATH that does not depend on which shell or harness is calling."""
    env = os.environ if environ is None else environ
    if env.get(PATH_ENV):
        return env[PATH_ENV]
    home = env.get("HOME") or str(Path.home())
    dirs: list[str] = []
    for raw in _CANONICAL_PATH:
        path = raw.replace("~", home, 1) if raw.startswith("~") else raw
        if path not in dirs and Path(path).is_dir():
            dirs.append(path)
    return os.pathsep.join(dirs)


def runtime_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """The environment every mcporter invocation runs with. See the module docstring."""
    env = dict(os.environ if environ is None else environ)
    names, prefixes = _passthrough(env)
    kept = {k: v for k, v in env.items() if _allowed(k, names, prefixes)}
    kept["PATH"] = canonical_path(env)
    kept.update(_FIXED)
    return dict(sorted(kept.items()))


# --------------------------------------------------------------------------- discovery


@dataclass(frozen=True)
class Plugin:
    name: str
    root: Path


@dataclass(frozen=True)
class Backend:
    plugin: str
    name: str
    root: Path
    spec: dict[str, Any]  # placeholders expanded, as declared in servers.json

    @property
    def qualified_name(self) -> str:
        return f"{self.plugin}:{self.name}"

    @property
    def transport(self) -> str:
        return "http" if self.spec.get("url") else "stdio"


def default_cache_root() -> Path:
    return Path.home() / ".claude" / "plugins" / "cache" / "rpw-agent-marketplace"


MARKETPLACE_HOME_ENV = "RPW_MARKETPLACE_HOME"


def release_plugins_root(environ: dict[str, str] | None = None) -> Path:
    """The unpacked internal release's ``plugins/`` (#2630).

    ``${RPW_MARKETPLACE_HOME:-~/.rpw/internal-marketplace}/current/plugins/<name>/``:
    a flat layout, each plugin dir is the install itself (no version level). Used only
    when there is no Claude Code plugin cache and ``RPW_MCP_CACHE_ROOT`` is unset.
    """
    env = os.environ if environ is None else environ
    home = env.get(MARKETPLACE_HOME_ENV) or "~/.rpw/internal-marketplace"
    return Path(home).expanduser() / "current" / "plugins"


def installed_plugins(environ: dict[str, str] | None = None) -> tuple[Path, list[Plugin]] | None:
    """``(base, plugins)`` from the plugin cache, else the internal release; None if neither.

    An explicit ``RPW_MCP_CACHE_ROOT`` is the only source considered when set.
    """
    env = os.environ if environ is None else environ
    if env.get(CACHE_ENV):
        cache = Path(env[CACHE_ENV]).expanduser()
        return (cache, plugins_in_cache(cache)) if cache.is_dir() else None
    cache = default_cache_root()
    if cache.is_dir():
        return cache, plugins_in_cache(cache)
    release = release_plugins_root(env)
    if release.is_dir():
        return release, plugins_in_checkout(release)
    return None


def _latest_install(plugin_dir: Path) -> Path | None:
    candidates = [path for path in plugin_dir.iterdir() if path.is_dir()]
    return max(candidates, key=lambda path: path.name) if candidates else None


def plugins_in_cache(cache_root: Path) -> list[Plugin]:
    """The latest install of every ``rpw-*`` plugin in a Claude Code plugin cache."""
    found = []
    for plugin_dir in sorted(cache_root.glob("rpw-*")):
        if plugin_dir.is_dir() and (install := _latest_install(plugin_dir)) is not None:
            if (install / BACKENDS_MANIFEST).is_file():
                found.append(Plugin(plugin_dir.name, install))
    return found


def plugins_in_checkout(plugins_dir: Path) -> list[Plugin]:
    """Every ``rpw-*`` plugin dir in a repo checkout's ``plugins/``."""
    return [
        Plugin(d.name, d)
        for d in sorted(plugins_dir.glob("rpw-*"))
        if (d / BACKENDS_MANIFEST).is_file()
    ]


def plugins_for_root(own_root: Path, own_name: str = "rpw-published") -> tuple[Path, list[Plugin]]:
    """The plugins to serve alongside the plugin at ``own_root``, and where they came from.

    An installed plugin lives at ``<cache>/<plugin>/<version>/``; a checkout or the
    unpacked internal release at ``<...>/plugins/<plugin>/`` (both flat). Anything else
    (the uvx tree) serves itself, plus an installed ``rpw-private`` (plugin cache, else
    the internal release) when there is one.
    """
    own_root = own_root.resolve()
    if own_root.parent.name == own_name:
        cache = own_root.parent.parent
        return cache, plugins_in_cache(cache)
    if own_root.name == own_name and own_root.parent.name == "plugins":
        return own_root.parent, plugins_in_checkout(own_root.parent)
    plugins = [Plugin(own_name, own_root)]
    found = installed_plugins({k: v for k, v in os.environ.items() if k != CACHE_ENV})
    if found is not None:
        plugins += [p for p in found[1] if p.name != own_name]
    return own_root, plugins


def _expand(value: Any, plugin_root: Path) -> Any:
    if isinstance(value, str):
        return value.replace(PLUGIN_ROOT_PLACEHOLDER, str(plugin_root))
    if isinstance(value, list):
        return [_expand(item, plugin_root) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, plugin_root) for key, item in value.items()}
    return value


def load_backends(plugins: list[Plugin]) -> list[Backend]:
    """Every backend the plugins list, in order. A name already taken is skipped."""
    found: list[Backend] = []
    taken: dict[str, str] = {}
    for plugin in plugins:
        path = plugin.root / BACKENDS_MANIFEST
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"cannot read {path}: {exc}") from exc
        servers = payload.get("mcpServers")
        if not isinstance(servers, dict):
            raise RuntimeError(f"{path}: expected an 'mcpServers' object")
        for name, spec in servers.items():
            if not isinstance(spec, dict):
                continue
            if name in taken:
                print(
                    f"[rpw-mcp] {plugin.name}: server {name!r} already provided by "
                    f"{taken[name]}; skipped",
                    file=sys.stderr,
                )
                continue
            taken[name] = plugin.name
            found.append(Backend(plugin.name, name, plugin.root, _expand(spec, plugin.root)))
    return found


# --------------------------------------------------------------------------- config


def _uv_project(args: list[str]) -> str | None:
    if not args or args[0] != "run" or "--project" not in args:
        return None
    index = args.index("--project") + 1
    return args[index] if index < len(args) else None


def mcporter_entry(backend: Backend) -> dict[str, Any]:
    """One mcporter server definition: keep-alive, explicit cwd, the fast start."""
    spec = backend.spec
    lifecycle = {"mode": "keep-alive", "idleTimeoutMs": IDLE_TIMEOUT_MS}
    if spec.get("url"):
        entry = {"url": spec["url"], "lifecycle": lifecycle}
        if spec.get("headers"):
            entry["headers"] = spec["headers"]
        return entry
    command = str(spec["command"])
    args = [str(a) for a in spec.get("args", [])]
    project = _uv_project(args) if Path(command).name == "uv" else None
    if project and "--no-sync" not in args and "--frozen" not in args:
        launcher = backend.root / "mcp-servers" / "lib" / "backend_launch.py"
        if launcher.is_file():
            args = ["run", "--no-project", "--quiet", "python", str(launcher), *args]
    # mcporter defaults cwd to the config file's dir. Pin it to the backend's own dir so
    # the backend never depends on who calls, and relative paths in it keep working.
    if spec.get("cwd"):
        cwd = str(spec["cwd"])
    elif project:
        cwd = project
    else:
        script = next((a for a in args if a.endswith((".sh", ".py")) and Path(a).is_absolute()), None)
        cwd = str(Path(script).parent) if script else str(backend.root)
    entry: dict[str, Any] = {"command": command, "args": args, "cwd": cwd, "lifecycle": lifecycle}
    if spec.get("env"):
        entry["env"] = {k: str(v) for k, v in spec["env"].items()}
    return entry


def build_config(backends: list[Backend]) -> dict[str, Any]:
    return {
        "imports": [],
        "mcpServers": {b.name: mcporter_entry(b) for b in backends},
    }


def rpw_home(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get(HOME_ENV) or Path.home() / ".rpw" / "mcp").expanduser()


def config_path_for(base: Path, environ: dict[str, str] | None = None) -> Path:
    """``mcporter.json`` for the default plugin cache, a stable per-source name otherwise.

    Named by where the plugins came from, not by their versions, so a version bump
    rewrites one file instead of leaving one behind per release.
    """
    home = rpw_home(environ)
    try:
        default = default_cache_root().resolve()
    except OSError:
        default = default_cache_root()
    if base.resolve() == default:
        return home / "mcporter.json"
    digest = hashlib.sha256(str(base.resolve()).encode()).hexdigest()[:10]
    return home / f"mcporter-{digest}.json"


def write_config(config: dict[str, Any], path: Path) -> Path:
    """Write ``config`` owner-only, atomically, and only when it changed."""
    text = json.dumps(config, indent=2, sort_keys=True) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return path
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=".mcporter-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


# --------------------------------------------------------------------------- mcporter


def _node_ok(node: str) -> bool:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    match = re.match(r"v(\d+)", out.stdout.strip())
    return bool(match) and int(match.group(1)) >= MIN_NODE_MAJOR


def find_node(environ: dict[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    for path in (env.get("PATH", ""), canonical_path(env)):
        node = shutil.which("node", path=path)
        if node and _node_ok(node):
            return node
    return None


def _installed_cli(home: Path) -> Path:
    return home / "runtime" / f"mcporter-{MCPORTER_VERSION}" / "node_modules" / "mcporter" / "dist" / "cli.js"


def install_mcporter(home: Path, node: str) -> Path | None:
    """Install the pinned mcporter under ``home``; None when npm is unavailable or fails."""
    target = _installed_cli(home)
    if target.is_file():
        return target
    npm = shutil.which("npm", path=str(Path(node).parent)) or shutil.which("npm")
    if not npm:
        return None
    final = home / "runtime" / f"mcporter-{MCPORTER_VERSION}"
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".mcporter-", dir=final.parent))
    try:
        proc = subprocess.run(
            [npm, "install", "--prefix", str(staging), "--no-save", "--no-audit", "--no-fund",
             "--loglevel=error", f"mcporter@{MCPORTER_VERSION}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300, check=False,
        )
        if proc.returncode != 0:
            print(f"[rpw-mcp] npm install mcporter@{MCPORTER_VERSION} failed: "
                  f"{proc.stderr.decode(errors='replace').strip()[-300:]}", file=sys.stderr)
            return None
        try:
            staging.rename(final)
        except OSError:  # a concurrent install won; use its copy
            pass
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[rpw-mcp] npm install mcporter failed: {exc}", file=sys.stderr)
        return None
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return target if target.is_file() else None


def mcporter_command(environ: dict[str, str] | None = None) -> list[str]:
    """The argv prefix that runs the pinned mcporter. Raises RuntimeError without Node 24+."""
    env = os.environ if environ is None else environ
    if env.get(MCPORTER_BIN_ENV):
        return [env[MCPORTER_BIN_ENV]]
    node = find_node(env)
    if node is None:
        raise RuntimeError(
            f"Node {MIN_NODE_MAJOR}+ is required for the rpw MCP runtime (mcporter). "
            "Install it (e.g. `brew install node`), then retry."
        )
    cli = install_mcporter(rpw_home(env), node)
    if cli is not None:
        return [node, str(cli)]
    npx = shutil.which("npx", path=str(Path(node).parent)) or shutil.which("npx")
    if npx:
        return [npx, "-y", f"mcporter@{MCPORTER_VERSION}"]
    raise RuntimeError(f"cannot install mcporter@{MCPORTER_VERSION}: npm/npx not found")


# --------------------------------------------------------------------------- prepare


@dataclass(frozen=True)
class Runtime:
    """Everything a caller needs to run mcporter over the installed rpw backends."""

    backends: list[Backend]
    config_path: Path
    env: dict[str, str]

    def argv(self, *args: str, environ: dict[str, str] | None = None) -> list[str]:
        return [*mcporter_command(environ), "--config", str(self.config_path), *args]


def prepare(
    base: Path,
    plugins: list[Plugin],
    environ: dict[str, str] | None = None,
) -> Runtime:
    backends = load_backends(plugins)
    path = write_config(build_config(backends), config_path_for(base, environ))
    return Runtime(backends=backends, config_path=path, env=runtime_env(environ))


def prepare_for_root(own_root: Path, environ: dict[str, str] | None = None) -> Runtime:
    base, plugins = plugins_for_root(own_root)
    return prepare(base, plugins, environ)
