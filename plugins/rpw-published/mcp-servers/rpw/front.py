"""The `rpw` MCP entry: a thin, unprefixing front over ``mcporter serve --stdio`` (#2623).

mcporter's keep-alive daemon holds every backend connection, restarts a backend that
died, and is shared with the ``rpw-mcp-cli`` shell path. This front only does the two
things ``mcporter serve`` cannot (verified against v0.16.0, ADR-2026-10-28):

- **Unprefixed tool names.** ``serve`` publishes ``server__tool`` whenever it fronts
  more than one server, and has no option to stop. House tool names already carry
  their server's prefix (``slack_*``, ``gdocs_*``), and hooks and allowlists match on
  them, so each tool is re-advertised under its own name and forwarded to its
  prefixed bridge name. If two backends expose one name, the earlier backend in
  ``servers.json`` order wins.
- **A first ``tools/list`` that never waits on a cold backend.** Claude Code reads the
  tool list once, at connect, and ignores ``tools/list_changed`` in a running turn, so
  a backend missing from the first list is missing for the session. ``serve`` lists
  backends one after another with no cache (about 22s for four cold backends in the
  spike). The front advertises the last successful list from disk at once and
  refreshes it in the background, one ``mcporter list <server>`` per backend in
  parallel, which also reports why a backend failed. Only a backend never listed
  before holds the first list, and then for at most ``RPW_MCP_INITIAL_WAIT`` seconds
  (default 25).

Calls go through ``serve``, which holds a 60s per-call ceiling of its own in v0.16.0
(it passes no timeout to the daemon). Every rpw tool returns inside 45s (#2623 part
B), so the ceiling is never the first limit to fire.

The bridge process is a FastMCP keep-alive stdio transport: if it dies, the next call
starts a new one. The ``rpw_backends`` tool reports each backend's state.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import mcp_runtime  # noqa: E402

STATUS_TOOL = "rpw_backends"
INITIAL_WAIT_ENV = "RPW_MCP_INITIAL_WAIT"
DEFAULT_INITIAL_WAIT_SECONDS = 25.0
CACHE_DIR_ENV = "RPW_MCP_CACHE_DIR"
SEPARATOR = "__"
# A backend's first start can include a `uv sync`; give a cold list far longer than
# mcporter's 30s default. It runs in the background, so nobody waits on it but itself.
LIST_TIMEOUT_MS = 180_000
TOOL_FIELDS = ("name", "title", "description", "inputSchema", "outputSchema", "annotations")


def _log(message: str) -> None:
    print(f"[rpw-mcp] {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- names


def _encode_part(value: str, *, leading: bool = False, trailing: bool = False) -> str:
    """mcporter serve's own encoding (src/serve.ts ``encodeToolNamePart``)."""
    encoded = value.replace("%", "%25").replace(SEPARATOR, "%5F%5F")
    if leading and encoded.startswith("_"):
        encoded = "%5F" + encoded[1:]
    if trailing and encoded.endswith("_"):
        encoded = encoded[:-1] + "%5F"
    return encoded


def bridged_name(server: str, tool: str) -> str:
    return f"{_encode_part(server, trailing=True)}{SEPARATOR}{_encode_part(tool, leading=True)}"


# --------------------------------------------------------------------------- cache


def cache_path(config_path: Path) -> Path:
    """Tool-list cache per mcporter config, outside the plugin dir (it may be read-only)."""
    root = Path(os.environ.get(CACHE_DIR_ENV) or Path.home() / ".cache" / "rpw-mcp")
    key = hashlib.sha256(str(config_path).encode()).hexdigest()[:16]
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


# --------------------------------------------------------------------------- front


class Front:
    """One forwarding tool per backend tool, plus ``rpw_backends``."""

    def __init__(self, runtime: mcp_runtime.Runtime, initial_wait: float):
        from fastmcp import FastMCP
        from fastmcp.server.middleware import Middleware

        self.runtime = runtime
        self.order = [b.name for b in runtime.backends]
        self.cache = cache_path(runtime.config_path)
        self.cached = read_cache(self.cache)
        self.errors: dict[str, str] = {}
        self.refreshed = asyncio.Event()
        self.owner: dict[str, str] = {STATUS_TOOL: "rpw"}
        self.session = None
        self.listed = False
        self.deadline = time.monotonic() + initial_wait
        self.bridge = None  # the `mcporter serve --stdio` client, once resolved
        self.bridge_error = ""
        self.base_argv: list[str] = []
        self.bridge_ready = asyncio.Event()
        self.server = FastMCP("rpw")

        @self.server.tool(name=STATUS_TOOL)
        async def rpw_backends() -> str:
            """Report which backend MCP servers the rpw runtime reached, and why any failed."""
            await self.wait_uncached()
            return json.dumps(self.status(), indent=2)

        for name in self.order:
            for raw in self.cached.get(name, []):
                self._register(name, raw)

        front = self

        class _FirstList(Middleware):
            async def on_call_tool(self, context, call_next):
                # A client that calls without listing first must not get "unknown
                # tool" for a backend that has never been listed yet.
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

    # ----------------------------------------------------------------- state

    def status(self) -> dict[str, Any]:
        rows = []
        for name in self.order:
            count = sum(1 for owner in self.owner.values() if owner == name)
            if name in self.errors:
                state = "failed"
            elif not self.refreshed.is_set():
                state = "starting"
            else:
                state = "ok"
            rows.append({"name": name, "state": state, "tools": count,
                         **({"error": self.errors[name]} if name in self.errors else {})})
        return {"runtime": f"mcporter {mcp_runtime.MCPORTER_VERSION}",
                "config": str(self.runtime.config_path), "backends": rows}

    async def wait_uncached(self) -> None:
        """Wait for the first refresh when some backend has no cached tools yet."""
        if self.refreshed.is_set() or all(name in self.cached for name in self.order):
            return
        remaining = self.deadline - time.monotonic()
        if remaining > 0:
            try:
                await asyncio.wait_for(self.refreshed.wait(), remaining)
            except TimeoutError:
                pass

    # ----------------------------------------------------------------- tools

    def _register(self, server: str, raw: dict[str, Any]) -> bool:
        import mcp.types as mcp_types
        from fastmcp.server.providers.proxy import ProxyTool

        name = raw.get("name", "")
        holder = self.owner.get(name)
        if holder is not None and holder != server:
            if holder == "rpw" or self.order.index(holder) < self.order.index(server):
                _log(f"{server}: tool {name!r} already provided by {holder}; skipped")
                return False
            self.server.local_provider.remove_tool(name)
        elif holder == server:
            self.server.local_provider.remove_tool(name)
        bridged = mcp_types.Tool.model_validate({**raw, "name": bridged_name(server, name)})
        tool = ProxyTool.from_mcp_tool(self._bridge_client, bridged).model_copy(
            update={"name": name}
        )
        self.server.add_tool(tool)
        self.owner[name] = server
        return True

    async def _bridge_client(self):
        await self.bridge_ready.wait()
        if self.bridge is None:
            from fastmcp.exceptions import ToolError

            raise ToolError(f"the rpw MCP runtime is unavailable: {self.bridge_error}")
        return self.bridge

    async def start_bridge(self) -> None:
        """Resolve the pinned mcporter (a first run installs it) and open the bridge."""
        from fastmcp import Client
        from fastmcp.client.transports import StdioTransport

        try:
            argv = await asyncio.to_thread(self.runtime.argv, "serve", "--stdio")
            self.base_argv = argv[:-2]
            self.bridge = Client(
                StdioTransport(argv[0], argv[1:], env=self.runtime.env,
                               cwd=str(self.runtime.config_path.parent)),
                timeout=None,
            )
        except RuntimeError as exc:
            self.bridge_error = str(exc)
            _log(self.bridge_error)
        finally:
            self.bridge_ready.set()

    def _unregister_missing(self, server: str, keep: set[str]) -> None:
        for name, owner in list(self.owner.items()):
            if owner == server and name not in keep:
                self.server.local_provider.remove_tool(name)
                del self.owner[name]

    async def list_backend(self, server: str) -> tuple[list[dict[str, Any]], str]:
        """``server``'s tools via ``mcporter list <server> --json``, or why there are none.

        One process per backend, all at once: ``serve``'s own ``tools/list`` starts cold
        backends one after another.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.base_argv, "list", server, "--json", "--timeout", str(LIST_TIMEOUT_MS),
                env=self.runtime.env, cwd=str(self.runtime.config_path.parent),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), LIST_TIMEOUT_MS / 1000 + 30)
        except (OSError, TimeoutError) as exc:
            return [], f"{type(exc).__name__}: {exc}"
        try:
            payload = json.loads(out or b"{}")
        except ValueError:
            payload = {}
        tools = [
            {k: v for k, v in tool.items() if k in TOOL_FIELDS}
            for tool in payload.get("tools") or []
            if isinstance(tool, dict) and tool.get("name")
        ]
        if tools and payload.get("status", "ok") == "ok":
            return tools, ""
        issue = payload.get("issue") or {}
        reason = (payload.get("error") or issue.get("rawMessage") or payload.get("status")
                  or err.decode(errors="replace").strip()[-300:] or "no tools listed")
        return [], str(reason)

    async def refresh(self) -> None:
        """List every backend in parallel; reconcile the advertised tools."""
        await self.start_bridge()
        if self.bridge is None:
            for name in self.order:
                self.errors[name] = self.bridge_error
            self.refreshed.set()
            return
        results = await asyncio.gather(*(self.list_backend(name) for name in self.order))
        live = {name: tools for name, (tools, _) in zip(self.order, results, strict=True)}
        self.errors = {
            name: reason for name, (tools, reason) in zip(self.order, results, strict=True)
            if not tools
        }
        changed = False
        for name in self.order:
            if not live[name]:
                continue  # keep cached tools: their calls report the real failure
            self._unregister_missing(name, {t["name"] for t in live[name]})
            for raw in live[name]:
                self._register(name, raw)
            if live[name] != self.cached.get(name):
                self.cached[name] = live[name]
                changed = True
        for name, reason in self.errors.items():
            _log(f"{name}: unavailable ({reason})")
        _log(f"{sum(len(v) for v in live.values())} tools from "
             f"{len(self.order) - len(self.errors)}/{len(self.order)} backends")
        if changed:
            write_cache(self.cache, self.cached)
        self.refreshed.set()
        if changed and self.listed and self.session is not None:
            try:
                await self.session.send_tool_list_changed()
            except Exception as exc:  # noqa: BLE001
                _log(f"could not send tools/list_changed: {exc}")
        await self.prewarm_bridge()

    async def prewarm_bridge(self) -> None:
        """Open the bridge and list through it once, off the call path.

        The MCP SDK lists a server's tools the first time a call returns structured
        content, to validate it, and ``serve`` lists every backend in turn. Doing that
        here, after the parallel lists warmed the daemon, keeps it off the first call.
        """
        try:
            async with self.bridge:
                await self.bridge.list_tools()
        except Exception as exc:  # noqa: BLE001 - a call will retry the connection
            _log(f"bridge warm-up failed: {type(exc).__name__}: {exc}")


async def serve(own_root: Path) -> None:
    runtime = mcp_runtime.prepare_for_root(own_root)
    initial_wait = float(os.environ.get(INITIAL_WAIT_ENV) or DEFAULT_INITIAL_WAIT_SECONDS)
    front = Front(runtime, initial_wait)
    refresher = asyncio.create_task(front.refresh(), name="rpw-mcp:refresh")
    try:
        await front.server.run_stdio_async(show_banner=False)
    finally:
        refresher.cancel()
        await asyncio.gather(refresher, return_exceptions=True)
        if front.bridge is not None:
            try:
                await front.bridge.transport.close()
            except Exception:  # noqa: BLE001
                pass


def run(own_root: Path) -> None:
    """Entry point. ``own_root`` is this plugin's root (or the uvx tree)."""
    asyncio.run(serve(own_root))
