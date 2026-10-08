#!/usr/bin/env python3
"""Discover and call installed RPW MCP servers through MCP Inspector's CLI.

The server remains the source of truth for schemas, auth, policy, and execution.
This wrapper only resolves versioned plugin installs, creates an ephemeral client
config, and bounds output for shell-only agent harnesses.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
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
BACKENDS_MANIFEST = Path("mcp-servers") / "rpw" / "servers.json"

# Spill files this CLI creates, and how long one stays readable. `sweep_spills` deletes
# only this prefix, so it can never touch a file it did not name (#1972).
SPILL_PREFIX = "rpw-mcp-output-"
SPILL_MAX_AGE_SECONDS = 24 * 60 * 60


# MCP Inspector does not pass the caller's environment to a stdio server, so a
# documented per-call opt-out (`SLACK_SEND_CONFIRM=0 rpw-mcp-cli call ...`) would
# never arrive. Forward exactly the house send-confirm switches, nothing else.
FORWARDED_SUFFIX = "_SEND_CONFIRM"


@dataclass(frozen=True)
class Server:
    plugin: str
    name: str
    root: Path
    config: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        return f"{self.plugin}:{self.name}"


def _cache_root() -> Path:
    configured = os.environ.get(CACHE_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".claude" / "plugins" / "cache" / "rpw-agent-marketplace"


def _latest_install(plugin_dir: Path) -> Path | None:
    candidates = [path for path in plugin_dir.iterdir() if path.is_dir()]
    return max(candidates, key=lambda path: path.name) if candidates else None


def _expand(value: Any, plugin_root: Path) -> Any:
    if isinstance(value, str):
        return value.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root))
    if isinstance(value, list):
        return [_expand(item, plugin_root) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, plugin_root) for key, item in value.items()}
    return value


def discover_servers(cache_root: Path | None = None) -> list[Server]:
    root = cache_root or _cache_root()
    if not root.is_dir():
        raise RuntimeError(
            f"RPW plugin cache not found at {root}. Install the RPW plugins or set {CACHE_ENV}."
        )

    found: list[Server] = []
    for plugin_dir in sorted(root.glob("rpw-*")):
        if not plugin_dir.is_dir():
            continue
        install = _latest_install(plugin_dir)
        if install is None:
            continue
        # A plugin's .mcp.json holds one aggregator entry that fronts every backend
        # (#2215). A one-shot shell call should start one server, not all of them, so
        # address the backends it lists directly.
        config_path = install / BACKENDS_MANIFEST
        if not config_path.is_file():
            config_path = install / ".mcp.json"
        if not config_path.is_file():
            continue
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot read {config_path}: {exc}") from exc
        servers = payload.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise TypeError(f"Invalid mcpServers object in {config_path}")
        for name, config in sorted(servers.items()):
            if isinstance(config, dict):
                found.append(
                    Server(
                        plugin=plugin_dir.name,
                        name=name,
                        root=install,
                        config=_expand(config, install),
                    )
                )
    return found


def resolve_server(name: str, servers: list[Server]) -> Server:
    if ":" in name:
        matches = [server for server in servers if server.qualified_name == name]
    else:
        matches = [server for server in servers if server.name == name]
    if not matches:
        available = ", ".join(server.qualified_name for server in servers) or "none"
        raise ValueError(f"Unknown MCP server '{name}'. Available: {available}")
    if len(matches) > 1:
        choices = ", ".join(server.qualified_name for server in matches)
        raise ValueError(f"MCP server '{name}' is ambiguous; use one of: {choices}")
    return matches[0]


def _inspector_path() -> str:
    path = shutil.which("mcp-inspector")
    if path:
        return path
    raise RuntimeError(
        "mcp-inspector is not installed. Run "
        "`npm install -g @modelcontextprotocol/inspector`, then retry."
    )


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


def _bridge_config(config: dict[str, Any]) -> dict[str, Any]:
    """The server's config plus the caller's send-confirm switches (#2142).

    Servers with outbound tools gate them in-process on every surface (#2179), so the
    one thing the bridge must do is let a confirmed opt-out reach them.
    """
    if "url" in config:  # not spawned by us: an env block would mean nothing
        return config
    switches = {k: v for k, v in os.environ.items() if k.endswith(FORWARDED_SUFFIX)}
    if not switches:
        return config
    return {**config, "env": {**(config.get("env") or {}), **switches}}


def _invoke(server: Server, method_args: list[str], max_bytes: int | None) -> int:
    config = {"mcpServers": {server.name: _bridge_config(server.config)}}
    config_file: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="rpw-mcp-", suffix=".json", delete=False
        ) as handle:
            json.dump(config, handle)
            config_file = handle.name
        os.chmod(config_file, 0o600)
        command = [
            _inspector_path(),
            "--cli",
            "--config",
            config_file,
            "--server",
            server.name,
            "--format",
            "json",
            *method_args,
        ]
        result = subprocess.run(
            command, text=False, capture_output=True, timeout=180, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"MCP call timed out after {exc.timeout} seconds") from exc
    finally:
        if config_file:
            Path(config_file).unlink(missing_ok=True)

    if result.returncode != 0:
        _report_failure(result.stderr, result.stdout, max_bytes)
        return result.returncode

    output = result.stdout
    if max_bytes is None or len(output) <= max_bytes:
        sys.stdout.buffer.write(output)
        return 0

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
    tools.add_argument("server", help="server name or plugin:server when ambiguous")

    call = commands.add_parser("call", help="call one MCP tool")
    call.add_argument("server", help="server name or plugin:server when ambiguous")
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
        servers = discover_servers()
        if args.command == "servers":
            rows = []
            for server in servers:
                transport = "http" if "url" in server.config else "stdio"
                rows.append(
                    {
                        "name": server.name,
                        "qualified_name": server.qualified_name,
                        "plugin": server.plugin,
                        "transport": transport,
                        **(
                            {"command": server.config.get("command", "")}
                            if transport == "stdio"
                            else {}
                        ),
                    }
                )
            print(json.dumps({"servers": rows}, ensure_ascii=False))
            return 0

        server = resolve_server(args.server, servers)
        if args.command == "tools":
            method_args = ["--method", "tools/list"]
        else:
            method_args = [
                "--method",
                "tools/call",
                "--tool-name",
                args.tool,
                "--tool-args-json",
                tool_arguments(args.json, args.arg_file),
            ]
        return _invoke(server, method_args, max_bytes)
    except ValueError as exc:
        parser.error(str(exc))
    except (RuntimeError, TypeError) as exc:
        print(f"rpw-mcp-cli: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
