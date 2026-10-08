"""One MCP server that fronts a plugin's backend MCP servers (#2215, #894 slice A).

Each plugin's `.mcp.json` declares exactly one entry: this aggregator. That keeps every
harness adapter (codex-sync, Omnigent bundles, permission allowlists) down to one
server per plugin. The backends are listed in ``mcp-servers/rpw/servers.json``, which
uses the same shape as ``.mcp.json``'s ``mcpServers`` (``command``/``args``/``env``/
``cwd`` for stdio, ``url`` for streamable HTTP) and the same ``${CLAUDE_PLUGIN_ROOT}``
placeholder.

Behavior that matters, and why:

- **``tools/list`` must not wait on the slowest backend.** Claude Code reads the tool
  list once, at connect, and ignores ``tools/list_changed`` in a running turn
  (verified 2026-10-07 with ``claude -p``). So a backend missing from the first list
  is missing for the whole session. Every backend's tool list is therefore cached on
  disk after a successful connect. On the next start, cached tools are advertised
  immediately and each call waits for its own backend. Only a backend with no cache
  yet, on its first ever start, delays the first list, and then for at most
  ``RPW_MCP_INITIAL_WAIT`` seconds (default 25, inside Claude Code's 30s MCP startup
  window).
- **Backends connect in parallel and stay connected.** One long-lived session per
  backend, as when every server had its own ``.mcp.json`` entry, so a tool call never
  pays a cold start after warm-up.
- **A failed backend is dropped, not fatal.** Its cached tools stay listed and return
  the backend's actual failure, so the user sees why (e.g. "not configured") rather
  than a tool that silently vanished. The ``rpw_backends`` tool reports every
  backend's state.
- **Tool names are not prefixed.** House tool names already carry their server's prefix
  (``gdocs_*``, ``slack_*``), so the only rename is the MCP server segment of the
  harness-qualified name. Hooks that match on a tool-name suffix keep working. If two
  backends expose the same name, the later backend loses the name and the clash is
  reported.
- **``uv run --project`` backends skip re-resolution when nothing changed.** Plain
  ``uv run`` re-resolves the project on every start, which costs network round-trips
  through a registry proxy. When the project's ``pyproject.toml`` hash matches the
  stamp from the last sync, the backend starts with ``--no-sync``. Otherwise it runs
  ``uv sync`` first and records the stamp. This is the same gate glean's
  ``run_mcp.sh`` applies to itself, and it uses the same stamp file.
- **The full environment is forwarded to stdio backends.** The MCP SDK's default gives a
  child process only a handful of safe variables. A harness hands its env to the server
  it starts (``SLACK_SEND_CONFIRM``, ``APP_ENV``, profile pins), so that env must reach
  the backend that actually reads it. The aggregator's own venv variables are not
  forwarded.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PLUGIN_ROOT_PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"
TIMEOUT_ENV = "RPW_MCP_BACKEND_TIMEOUT"
DEFAULT_TIMEOUT_SECONDS = 180.0  # a first-run `uv sync` of a backend can be slow
INITIAL_WAIT_ENV = "RPW_MCP_INITIAL_WAIT"
DEFAULT_INITIAL_WAIT_SECONDS = 25.0
CACHE_DIR_ENV = "RPW_MCP_CACHE_DIR"
STATUS_TOOL = "rpw_backends"
STAMP_NAME = ".rpw-pyproject.sha256"  # shared with glean's run_mcp.sh
_NOT_FORWARDED = frozenset({"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONHOME", "PYTHONPATH"})


def _log(message: str) -> None:
    print(f"[rpw-mcp] {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- manifest


def _expand(value: Any, plugin_root: Path) -> Any:
    if isinstance(value, str):
        return value.replace(PLUGIN_ROOT_PLACEHOLDER, str(plugin_root))
    if isinstance(value, list):
        return [_expand(item, plugin_root) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, plugin_root) for key, item in value.items()}
    return value


def load_manifest(path: Path, plugin_root: Path) -> dict[str, dict[str, Any]]:
    """Read ``servers.json`` and expand the plugin-root placeholder. Order is kept."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict):
        raise ValueError(f"{path}: expected an 'mcpServers' object")
    return {
        name: _expand(spec, plugin_root)
        for name, spec in servers.items()
        if isinstance(spec, dict)
    }


# --------------------------------------------------------------------------- launching


def uv_project(spec: dict[str, Any]) -> str | None:
    """The ``--project`` dir of a ``uv run --project <dir> ...`` spec that may skip sync."""
    args = [str(a) for a in spec.get("args", [])]
    if spec.get("command") != "uv" or not args or args[0] != "run":
        return None
    if "--project" not in args or "--no-sync" in args or "--frozen" in args:
        return None
    index = args.index("--project") + 1
    return args[index] if index < len(args) else None


async def fast_start(spec: dict[str, Any]) -> dict[str, Any]:
    """``spec`` with ``--no-sync`` when the backend's venv is known current.

    Syncs first, recording the stamp, when it is not. On any failure the spec comes
    back unchanged, so the slow path is always the fallback and never a wrong one.
    """
    project = uv_project(spec)
    if project is None:
        return spec
    root = Path(project)
    stamp = root / ".venv" / STAMP_NAME
    try:
        want = hashlib.sha256((root / "pyproject.toml").read_bytes()).hexdigest()
        if not (stamp.is_file() and stamp.read_text(encoding="utf-8") == want):
            proc = await asyncio.create_subprocess_exec(
                "uv", "sync", "--project", project,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                env=_child_env({}),
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                _log(f"uv sync failed for {project}; starting without the fast path: "
                     f"{err.decode(errors='replace').strip()[-300:]}")
                return spec
            stamp.write_text(want, encoding="utf-8")
    except OSError as exc:
        _log(f"fast path unavailable for {project}: {exc}")
        return spec
    args = [str(a) for a in spec["args"]]
    return {**spec, "args": [args[0], "--no-sync", *args[1:]]}


def _child_env(extra: dict[str, Any]) -> dict[str, str]:
    inherited = {k: v for k, v in os.environ.items() if k not in _NOT_FORWARDED}
    return {**inherited, **{k: str(v) for k, v in extra.items()}}


def transport_for(spec: dict[str, Any]):
    """Build the client transport for one backend spec."""
    if spec.get("url"):
        from fastmcp.client.transports import StreamableHttpTransport

        return StreamableHttpTransport(spec["url"], headers=spec.get("headers") or None)
    if spec.get("command"):
        from fastmcp.client.transports import StdioTransport

        return StdioTransport(
            command=spec["command"],
            args=[str(a) for a in spec.get("args", [])],
            env=_child_env(spec.get("env") or {}),
            cwd=spec.get("cwd"),
        )
    raise ValueError("backend spec has neither 'command' nor 'url'")


# --------------------------------------------------------------------------- cache


def cache_path(manifest: Path) -> Path:
    """Per-install tool-list cache, kept outside the plugin dir (it may be read-only)."""
    root = Path(os.environ.get(CACHE_DIR_ENV) or Path.home() / ".cache" / "rpw-mcp")
    key = hashlib.sha256(str(manifest.resolve()).encode()).hexdigest()[:16]
    return root / f"tools-{key}.json"


def read_cache(path: Path) -> dict[str, list[dict[str, Any]]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_cache(path: Path, tools: dict[str, list[dict[str, Any]]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tools, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        _log(f"could not write tool cache {path}: {exc}")


# --------------------------------------------------------------------------- backends


@dataclass
class Backend:
    name: str
    spec: dict[str, Any]
    client: Any = None
    tools: list[Any] = field(default_factory=list)  # mcp.types.Tool, once connected
    instructions: str = ""
    error: str = ""
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    stop: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def ok(self) -> bool:
        return self.client is not None and not self.error


async def hold(backend: Backend, timeout: float) -> None:
    """Connect one backend and keep its session open until told to stop.

    The connection is entered and exited in this one task, because anyio cancel
    scopes must close in the task that opened them.
    """
    from fastmcp import Client

    async def _connect_and_wait() -> None:
        client = Client(transport_for(await fast_start(backend.spec)))
        async with client:
            backend.tools = list(await client.list_tools())
            result = client.initialize_result
            backend.instructions = (getattr(result, "instructions", None) or "").strip()
            backend.client = client
            backend.ready.set()
            await backend.stop.wait()

    try:
        connecting = asyncio.create_task(_connect_and_wait())
        done, _ = await asyncio.wait({connecting}, timeout=timeout)
        if not done and not backend.ready.is_set():
            connecting.cancel()
            backend.error = f"no response within {timeout:g}s"
        await asyncio.gather(connecting, return_exceptions=False)
    except asyncio.CancelledError:
        if not backend.error:
            raise
    except Exception as exc:  # noqa: BLE001 - one bad backend must not sink the rest
        backend.error = f"{type(exc).__name__}: {exc}".strip()
    finally:
        if backend.error:
            backend.client = None
        backend.ready.set()


def status(backends: list[Backend]) -> dict[str, Any]:
    return {
        "backends": [
            {
                "name": b.name,
                "state": "ok" if b.ok else ("starting" if not b.ready.is_set() else "failed"),
                "tools": len(b.tools) if b.ok else 0,
                **({"error": b.error} if b.error else {}),
            }
            for b in backends
        ]
    }


def instructions_note(backends: list[Backend]) -> str:
    return "\n\n".join(
        f"[{b.name}] {b.instructions}" for b in backends if b.ok and b.instructions
    )


# --------------------------------------------------------------------------- front


class Aggregator:
    """The front server: one forwarding tool per backend tool, plus ``rpw_backends``."""

    def __init__(self, name: str, backends: list[Backend], cache: Path, initial_wait: float):
        from fastmcp import FastMCP
        from fastmcp.server.middleware import Middleware

        self.backends = backends
        self.cache = cache
        self.cached = read_cache(cache)
        self.owner: dict[str, str] = {STATUS_TOOL: "rpw"}
        self.registered: set[str] = set()
        self.session = None
        self.listed = False
        self.deadline = time.monotonic() + initial_wait
        self.server = FastMCP(name)

        @self.server.tool(name=STATUS_TOOL)
        async def rpw_backends() -> str:
            """Report which backend MCP servers this aggregator connected, and why any failed."""
            # A diagnostic wants the settled answer: give still-starting backends the
            # rest of the initial window before reporting.
            remaining = self.deadline - time.monotonic()
            if remaining > 0:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*(b.ready.wait() for b in backends)), remaining
                    )
                except TimeoutError:
                    pass
            return json.dumps(status(backends), indent=2)

        for backend in backends:
            for raw in self.cached.get(backend.name, []):
                self._register(backend, raw)

        front = self

        class _FirstList(Middleware):
            async def on_initialize(self, context, call_next):
                await front.wait_uncached()
                front.server.instructions = instructions_note(backends) or None
                return await call_next(context)

            async def on_call_tool(self, context, call_next):
                # A client that calls without listing first (a one-shot shell call)
                # must not get "unknown tool" for a backend that is still starting.
                await front.wait_uncached()
                return await call_next(context)

            async def on_list_tools(self, context, call_next):
                await front.wait_uncached()
                ctx = getattr(context, "fastmcp_context", None)
                if ctx is not None and front.session is None:
                    try:
                        front.session = ctx.session
                    except Exception:  # noqa: BLE001 - notifications are best-effort
                        pass
                front.listed = True
                return await call_next(context)

        self.server.add_middleware(_FirstList())

    async def wait_uncached(self) -> None:
        """Wait for backends with no cached tools, up to the initial deadline."""
        pending = [b for b in self.backends if b.name not in self.cached]
        remaining = self.deadline - time.monotonic()
        if pending and remaining > 0:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(b.ready.wait() for b in pending)), remaining
                )
            except TimeoutError:
                pass

    def _register(self, backend: Backend, raw: dict[str, Any]) -> bool:
        """Advertise one backend tool; its calls wait for and go to that backend."""
        import mcp.types as mcp_types
        from fastmcp.server.providers.proxy import ProxyTool

        tool = mcp_types.Tool.model_validate(raw)
        holder = self.owner.get(tool.name)
        if holder is not None and holder != backend.name:
            _log(f"{backend.name}: tool {tool.name!r} already provided by {holder}; skipped")
            return False
        self.owner[tool.name] = backend.name
        if tool.name in self.registered:
            self.server.local_provider.remove_tool(tool.name)
        self.server.add_tool(ProxyTool.from_mcp_tool(self._client_for(backend), tool))
        self.registered.add(tool.name)
        return True

    def _client_for(self, backend: Backend):
        async def factory():
            await backend.ready.wait()
            if not backend.ok:
                from fastmcp.exceptions import ToolError

                raise ToolError(f"{backend.name} MCP server is unavailable: {backend.error}")
            return backend.client

        return factory

    async def watch(self, backend: Backend) -> None:
        """When ``backend`` settles, reconcile its advertised tools with its real ones."""
        await backend.ready.wait()
        if not backend.ok:
            _log(f"{backend.name}: unavailable ({backend.error})")
            return
        live = [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in backend.tools]
        before = {t["name"] for t in self.cached.get(backend.name, [])}
        after = {t["name"] for t in live}
        for name in before - after:
            if self.owner.get(name) == backend.name:
                self.server.local_provider.remove_tool(name)
                self.registered.discard(name)
                del self.owner[name]
        for raw in live:
            self._register(backend, raw)
        _log(f"{backend.name}: {len(live)} tools")
        changed = live != self.cached.get(backend.name)
        self.cached[backend.name] = live
        if changed:
            write_cache(self.cache, self.cached)
            if self.listed and self.session is not None:
                try:
                    await self.session.send_tool_list_changed()
                except Exception as exc:  # noqa: BLE001
                    _log(f"could not send tools/list_changed: {exc}")


async def serve(name: str, manifest: Path, plugin_root: Path) -> None:
    specs = load_manifest(manifest, plugin_root)
    backends = [Backend(n, s) for n, s in specs.items()]
    initial_wait = float(os.environ.get(INITIAL_WAIT_ENV) or DEFAULT_INITIAL_WAIT_SECONDS)
    timeout = float(os.environ.get(TIMEOUT_ENV) or DEFAULT_TIMEOUT_SECONDS)
    front = Aggregator(name, backends, cache_path(manifest), initial_wait)
    holders = [asyncio.create_task(hold(b, timeout), name=f"rpw-mcp:{b.name}") for b in backends]
    watchers = [asyncio.create_task(front.watch(b)) for b in backends]
    try:
        await front.server.run_stdio_async(show_banner=False)
    finally:
        for backend in backends:
            backend.stop.set()
        for task in watchers:
            task.cancel()
        await asyncio.gather(*holders, *watchers, return_exceptions=True)


def run(name: str, here: Path) -> None:
    """Entry point for a plugin's ``mcp-servers/rpw/run_mcp.py``.

    ``here`` is that directory. The plugin root is always taken from this file's own
    location, two levels up, never from ``CLAUDE_PLUGIN_ROOT``: an inherited value
    could name a different plugin, and a uvx install has no such variable at all.
    """
    asyncio.run(serve(name, here / "servers.json", here.parent.parent))
