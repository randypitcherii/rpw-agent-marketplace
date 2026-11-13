#!/usr/bin/env python3
"""Discover and call installed RPW MCP servers from the shell, through mcporter (#2623).

The servers stay the source of truth for schemas, auth, policy and execution. This
shim only builds the one mcporter config for every installed rpw plugin
(``mcp-servers/rpw/mcp_runtime.py``), and bounds the output under the house CLI output
contract (docs/process/cli-output-contract.md).

``tools`` and ``call`` speak MCP to a short-lived ``mcporter serve --stdio --servers
<one>`` child, exactly as the plugin's `rpw` entry (``front.py``) does, with the same
config and env. So the shell and the MCP entry share the daemon's warm backends, and
the output is the full MCP result (every content block, ``structuredContent``,
``isError``), not ``mcporter call``'s lossy JSON rendering. A warm call takes ~1.2s.

The MCP client is FastMCP's. This file starts under any Python; when FastMCP is not
importable it re-runs itself in the `rpw` entry's own venv (``mcp-servers/rpw``),
through ``lib/backend_launch.py`` so that venv is synced only when it changed.
Decision: docs/decisions/ADR-2026-10-28-mcporter-runtime.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# The house CLI output contract (docs/process/cli-output-contract.md): stdout
# carries a status line, the counts, and `full: <path>`. 8 KiB is enough to hold
# the answer a caller reads; the 50 KiB this used to be was large enough never to
# fire, which made it a cap in name only (#1962).
DEFAULT_MAX_BYTES = 8 * 1024

# The contract's non-negotiable half: a failing call reports the first failure
# inline so the agent does not pay a second read call to learn what broke.
FAILURE_MAX_LINES = 40

CACHE_ENV = "RPW_MCP_CACHE_ROOT"

# Spill files this CLI creates, and how long one stays readable. `sweep_spills` deletes
# only this prefix, so it can never touch a file it did not name (#1972).
SPILL_PREFIX = "rpw-mcp-output-"
SPILL_MAX_AGE_SECONDS = 24 * 60 * 60

# mcporter's own call deadline (default 60s) is the one that fires; set it above every
# server-side limit (#2623 part B: each tool answers inside 45s) so a slow tool returns
# its own envelope rather than a transport timeout. `--timeout` / the env override it.
DEFAULT_CALL_TIMEOUT_SECONDS = 120
CALL_TIMEOUT_ENV = "RPW_MCP_CALL_TIMEOUT_SECONDS"
# A cold `tools` list can include a backend's first `uv sync`.
LIST_TIMEOUT_MS = 180_000
# Set on the re-run inside the `rpw` entry's venv, so a venv without FastMCP fails
# loudly instead of re-running forever.
IN_RUNTIME_VENV_ENV = "RPW_MCP_CLI_IN_RUNTIME_VENV"

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent.parent
RUNTIME_DIR = Path("mcp-servers") / "rpw"


def _default_cache_root() -> Path:
    return Path.home() / ".claude" / "plugins" / "cache" / "rpw-agent-marketplace"


def _cache_root() -> Path:
    configured = os.environ.get(CACHE_ENV)
    return Path(configured).expanduser() if configured else _default_cache_root()


def _release_plugins_root() -> Path:
    """Mirrors ``mcp_runtime.release_plugins_root`` (needed before that module loads)."""
    home = os.environ.get("RPW_MARKETPLACE_HOME") or "~/.rpw/internal-marketplace"
    return Path(home).expanduser() / "current" / "plugins"


def _load_runtime():
    """Import ``mcp_runtime`` from this plugin, the newest installed one, or the release."""
    candidates = [PLUGIN_ROOT / RUNTIME_DIR]
    published = _default_cache_root() / "rpw-published"
    if published.is_dir():
        installs = sorted((p for p in published.iterdir() if p.is_dir()), key=lambda p: p.name)
        candidates += [p / RUNTIME_DIR for p in reversed(installs)]
    candidates.append(_release_plugins_root() / "rpw-published" / RUNTIME_DIR)
    for directory in candidates:
        if (directory / "mcp_runtime.py").is_file():
            sys.path.insert(0, str(directory))
            import mcp_runtime

            return mcp_runtime
    raise RuntimeError(
        "the rpw MCP runtime (mcp-servers/rpw/mcp_runtime.py) was not found; "
        "update the rpw-published plugin"
    )


def runtime():
    """The prepared mcporter runtime for the installed plugins.

    The Claude Code plugin cache is the default source, so the shell shares warm
    backends with Claude Code's `rpw` entry. With no cache (a Sandbox), the unpacked
    internal release (#2630). A checkout with neither serves itself.
    """
    mcp_runtime = _load_runtime()
    found = mcp_runtime.installed_plugins()
    if found is not None:
        base, plugins = found
    elif os.environ.get(CACHE_ENV):
        raise RuntimeError(f"RPW plugin cache not found at {_cache_root()} (from {CACHE_ENV}).")
    else:
        base, plugins = mcp_runtime.plugins_for_root(PLUGIN_ROOT)
    if not plugins:
        raise RuntimeError(
            f"No RPW plugins with MCP servers found under {base}. Install the RPW "
            f"plugins or set {CACHE_ENV}."
        )
    return mcp_runtime.prepare(base, plugins)


def resolve_server(name: str, backends: list) -> Any:
    if ":" in name:
        matches = [b for b in backends if b.qualified_name == name]
    else:
        matches = [b for b in backends if b.name == name]
    if not matches:
        available = ", ".join(b.qualified_name for b in backends) or "none"
        raise ValueError(f"Unknown MCP server '{name}'. Available: {available}")
    return matches[0]


def _spill(payload: bytes, suffix: str) -> str:
    """Write the complete output to an owner-only file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=SPILL_PREFIX, suffix=suffix, delete=False
    ) as handle:
        handle.write(payload)
        path = handle.name
    os.chmod(path, 0o600)
    return path


def sweep_spills(
    root: Path | None = None,
    *,
    max_age_seconds: int = SPILL_MAX_AGE_SECONDS,
    now: float | None = None,
) -> int:
    """Delete this CLI's own aged-out spill files. Returns how many went (#1972).

    Nothing used to delete them, and the 8 KiB cap moved spilling from never-fires to the
    common case, so full `google-docs` / `slack` / `jira` / `glean` payloads piled up in
    TMPDIR forever. Age rather than "every prior file": a `full: <path>` an earlier call in
    this session handed the agent must still be readable when the agent gets to it.

    Only files matching this CLI's own prefix, never a symlink, never a path outside the
    temp dir it writes to. Best-effort throughout — a sweep must never fail a call.
    """
    directory = root or Path(tempfile.gettempdir())
    cutoff = (time.time() if now is None else now) - max_age_seconds
    removed = 0
    try:
        candidates = sorted(directory.glob(f"{SPILL_PREFIX}*"))
    except OSError:
        return 0
    for path in candidates:
        try:
            if path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_mtime > cutoff:
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _excerpt(text: str, max_lines: int, max_bytes: int) -> tuple[str, str]:
    """The tail of ``text`` under BOTH bounds, plus a count line that says what was cut.

    Tail rather than head: a failing process writes its warnings first and the error that
    killed it last, so the head is reliably the noise and the tail is reliably the answer
    (#1972 — 50 lines of `(node:…) Warning:` ahead of the real MCP error).
    """
    lines = text.splitlines()
    total_lines = len(lines)
    total_bytes = len(text.encode("utf-8", errors="replace"))
    body = "\n".join(lines[-max_lines:]) if max_lines < total_lines else text
    raw = body.encode("utf-8", errors="replace")
    if len(raw) > max_bytes:
        raw = raw[-max_bytes:]
        body = raw.decode("utf-8", errors="replace")
    shown_lines = len(body.splitlines())
    if shown_lines == total_lines and len(raw) == total_bytes:
        return body, f"all {total_lines} lines, {total_bytes} bytes"
    # Both dimensions, always: a bare line count implies bytes did not truncate (#1972).
    return body, (
        f"tail {shown_lines} of {total_lines} lines, "
        f"{len(raw)} of {total_bytes} bytes"
    )


def _failure_payload(streams: list[tuple[str, bytes]]) -> bytes:
    """The complete detail for the spill file, one labelled section per stream."""
    parts: list[bytes] = []
    for label, raw in streams:
        parts.append(f"--- {label} ---\n".encode())
        parts.append(raw if raw.endswith(b"\n") else raw + b"\n")
    return b"".join(parts)


def _report_failure(stderr: bytes, stdout: bytes, max_bytes: int | None) -> None:
    """Report a failed call: an excerpt of EVERY stream inline, then `full: <path>`.

    Diagnostics go to stderr, the conventional channel for them — the contract
    requires the detail to be inline *somewhere* in this invocation's output, not
    that it be on stdout. What it forbids is a bare pointer with nothing inline.

    Each stream gets its own share of both budgets (#1972). Head-slicing the two
    *concatenated* let a noisy stderr spend the whole inline budget and push the whole of
    stdout — where the real MCP error lands — out of the report entirely.
    """
    streams = [(name, raw) for name, raw in (("stderr", stderr), ("stdout", stdout)) if raw]
    if not streams:
        return
    # Normalized to the lines that could be shown, so every count below — per stream and
    # in the summary — describes exactly the same text.
    texts = [
        (name, "\n".join(raw.decode("utf-8", errors="replace").splitlines()))
        for name, raw in streams
    ]
    total_lines = sum(len(text.splitlines()) for _, text in texts)
    total_bytes = sum(len(text.encode("utf-8", errors="replace")) for _, text in texts)
    if max_bytes is None or (
        total_lines <= FAILURE_MAX_LINES and total_bytes <= max_bytes
    ):
        for _, text in texts:
            sys.stderr.write(text + "\n")
        return
    path = _spill(_failure_payload(streams), ".log")
    share_lines = max(1, FAILURE_MAX_LINES // len(texts))
    share_bytes = max(1, max_bytes // len(texts))
    for name, text in texts:
        body, counts = _excerpt(text, share_lines, share_bytes)
        sys.stderr.write(f"{name} ({counts}):\n{body}\n")
    sys.stderr.write(
        f"failed: {total_lines} lines, {total_bytes} bytes total; "
        f"excerpts above are the tail of each stream\n"
        f"full: {path}\n"
    )


def _call_timeout_seconds(flag: float | None) -> float:
    if flag is not None:
        return flag
    raw = os.environ.get(CALL_TIMEOUT_ENV, "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_CALL_TIMEOUT_SECONDS


def _emit(output: bytes, max_bytes: int | None) -> None:
    if max_bytes is None or len(output) <= max_bytes:
        sys.stdout.buffer.write(output)
        return
    output_path = _spill(output, ".json")
    preview = output[:max_bytes].decode("utf-8", errors="replace")
    print(
        json.dumps(
            {
                "truncated": True,
                "total_bytes": len(output),
                "preview": preview,
                # `full` is the contract's key; `output_file` is its back-compat
                # alias, carrying the same path for callers written before #1962.
                "full": output_path,
                "output_file": output_path,
            },
            ensure_ascii=False,
        )
    )


def ensure_mcp_client(argv: list[str]) -> None:
    """Re-run this CLI in the `rpw` entry's venv when FastMCP is not importable here.

    That venv is the one the plugin's MCP entry runs in, so it always has FastMCP, and
    ``backend_launch.py`` keeps it to a ``uv run --no-sync`` (no resolution) once it is
    synced. A ``uv run --with fastmcp`` would re-resolve on every call (5-10s measured).
    """
    try:
        import fastmcp  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get(IN_RUNTIME_VENV_ENV):
        raise RuntimeError("FastMCP is not importable even in the rpw entry's venv; "
                           "delete mcp-servers/rpw/.venv in the plugin and retry")
    project = Path(_load_runtime().__file__).resolve().parent
    launcher = project.parent / "lib" / "backend_launch.py"
    command = ["uv", "run", "--no-project", "--quiet", "python", str(launcher),
               "run", "--project", str(project), "python", str(Path(__file__).resolve()), *argv]
    os.execvpe("uv", command, {**os.environ, IN_RUNTIME_VENV_ENV: "1"})


def _strip_bridge_names(server: str, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tools as their backend names them, not as ``mcporter serve`` namespaces them."""
    prefix = f"{server}__"
    tag = f"[{server}] "
    out = []
    for tool in tools:
        tool = dict(tool)
        if tool.get("name", "").startswith(prefix):
            tool["name"] = tool["name"][len(prefix):].replace("%5F", "_").replace("%25", "%")
        if isinstance(tool.get("description"), str) and tool["description"].startswith(tag):
            tool["description"] = tool["description"][len(tag):]
        out.append(tool)
    return out


async def _over_serve(rt, server: str, method: str, tool: str, arguments: dict[str, Any],
                      timeout: float, log: Path) -> dict[str, Any]:
    """One MCP request to a ``mcporter serve --stdio`` child serving only ``server``.

    Serving one server keeps the SDK's validation re-list (its first structured result
    lists tools) to that server's warm daemon list, never every backend in turn.
    """
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    argv = rt.argv("serve", "--stdio", "--servers", server)
    transport = StdioTransport(argv[0], argv[1:], env=rt.env, cwd=str(rt.config_path.parent),
                               keep_alive=False, log_file=log)
    async with Client(transport, timeout=timeout, init_timeout=timeout) as client:
        if method == "tools":
            listed = await client.list_tools_mcp()
            dumped = listed.model_dump(mode="json", by_alias=True, exclude_none=True)
            dumped["tools"] = _strip_bridge_names(server, dumped.get("tools", []))
            return {"server": server, "result": dumped}
        # Imported late: front.py's encoding is the one place that mirrors serve's.
        sys.path.insert(0, str(Path(_load_runtime().__file__).resolve().parent))
        from front import bridged_name

        result = await client.call_tool_mcp(bridged_name(server, tool), arguments, timeout=timeout)
        return {"result": result.model_dump(mode="json", by_alias=True, exclude_none=True)}


def _invoke(rt, server: str, method: str, tool: str, arguments: str, timeout: float,
            max_bytes: int | None) -> int:
    """Run one request and print it under the output contract. Returns the exit code."""
    fd, log_name = tempfile.mkstemp(prefix=f"{SPILL_PREFIX}serve-", suffix=".log")
    os.close(fd)
    log = Path(log_name)
    failure = ""
    payload: dict[str, Any] = {}
    try:
        payload = asyncio.run(asyncio.wait_for(
            _over_serve(rt, server, method, tool, json.loads(arguments), timeout, log),
            timeout + 15,
        ))
    except TimeoutError:
        failure = f"rpw-mcp-cli: {server}: no answer within {timeout:g}s"
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - an MCP error, or a dead serve child
        failure = f"rpw-mcp-cli: {server}: {type(exc).__name__}: {exc}"
    try:
        stderr = log.read_bytes()
    except OSError:
        stderr = b""
    log.unlink(missing_ok=True)
    if failure:
        _report_failure(stderr, b"", max_bytes)
        print(failure, file=sys.stderr)
        return 1
    output = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
    if payload.get("result", {}).get("isError"):
        # A tool-level error: the result is the failure detail, so it goes inline
        # (with whatever the runtime logged), never behind a bare pointer.
        _report_failure(stderr, output, max_bytes)
        return 1
    _emit(output, max_bytes)
    return 0


def _json_object(raw: str) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--json must be a valid JSON object: {exc.msg}"
        ) from exc
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("--json must be a JSON object")
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _arg_file(raw: str) -> tuple[str, Path]:
    key, sep, path = raw.partition("=")
    if not sep or not key or not path:
        raise argparse.ArgumentTypeError(f"--arg-file must be KEY=PATH, got {raw!r}")
    return key, Path(path).expanduser()


def tool_arguments(raw_json: str, arg_files: list[tuple[str, Path]]) -> str:
    """Merge `--json` with `--arg-file` string values into one JSON object (#2143).

    `--arg-file` exists so a long or quote-heavy body (a markdown doc, a Slack message)
    never has to survive shell quoting inside `--json`. It is explicit by design: no
    `@path` magic, because a real string argument may start with `@`.
    """
    arguments = json.loads(raw_json)
    for key, path in arg_files:
        if key in arguments:
            raise ValueError(f"argument {key!r} given both in --json and by --arg-file")
        try:
            arguments[key] = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"--arg-file {key}: cannot read {path}: {exc.strerror}") from exc
    return json.dumps(arguments, separators=(",", ":"), ensure_ascii=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rpw-mcp-cli",
        description="Discover and call installed RPW MCP servers from shell-only agent harnesses.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"inline output limit before saving the full result (default: {DEFAULT_MAX_BYTES})",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="print everything inline: no cap, no preview, no spill file",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("servers", help="list installed RPW MCP servers")

    tools = commands.add_parser("tools", help="list a server's tools and input schemas")
    tools.add_argument("server", help="server name (or plugin:server)")

    call = commands.add_parser("call", help="call one MCP tool")
    call.add_argument("server", help="server name (or plugin:server)")
    call.add_argument("tool", help="tool name from the tools command")
    call.add_argument(
        "--json",
        default="{}",
        type=_json_object,
        help="tool arguments as a JSON object (default: {})",
    )
    call.add_argument(
        "--arg-file",
        action="append",
        default=[],
        type=_arg_file,
        metavar="KEY=PATH",
        help="set string argument KEY to the contents of PATH (repeatable)",
    )
    call.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=f"call deadline (default {DEFAULT_CALL_TIMEOUT_SECONDS}, env {CALL_TIMEOUT_ENV})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_bytes < 1:
        parser.error("--max-bytes must be positive")
    # `--full` is the contract's opt-out: unbounded, so it outranks --max-bytes.
    max_bytes: int | None = None if args.full else args.max_bytes
    sweep_spills()  # silent: the contract owns this stdout (#1972)
    try:
        rt = runtime()
        if args.command == "servers":
            rows = []
            for backend in rt.backends:
                rows.append(
                    {
                        "name": backend.name,
                        "qualified_name": backend.qualified_name,
                        "plugin": backend.plugin,
                        "transport": backend.transport,
                        **(
                            {"command": backend.spec.get("command", "")}
                            if backend.transport == "stdio"
                            else {}
                        ),
                    }
                )
            print(json.dumps({"servers": rows}, ensure_ascii=False))
            return 0

        server = resolve_server(args.server, rt.backends)
        ensure_mcp_client(sys.argv[1:] if argv is None else argv)
        if args.command == "tools":
            return _invoke(rt, server.name, "tools", "", "{}", LIST_TIMEOUT_MS / 1000, max_bytes)
        timeout = _call_timeout_seconds(args.timeout)
        if timeout <= 0:
            parser.error("--timeout must be positive")
        arguments = tool_arguments(args.json, args.arg_file)
        return _invoke(rt, server.name, "call", args.tool, arguments, timeout, max_bytes)
    except ValueError as exc:
        parser.error(str(exc))
    except (RuntimeError, TypeError) as exc:
        print(f"rpw-mcp-cli: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
