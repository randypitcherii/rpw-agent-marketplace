"""Optional MCP-server telemetry to the shared Zerobus log table (#891).

A thin bridge over the ``rpw_logging`` Zerobus sink, which ``make sync-mcp-lib`` vendors
into ``lib/_rpw_logging/`` (MCP servers cannot depend on the unpublished package). The
canonical lib falls back to an installed ``rpw_logging``; with neither, every call no-ops.

**Off unless configured.** The vendored sink ships without a default destination, so a
published plugin sends nothing until its user writes ``~/.rpw/logging.env`` (or the
server's env file) with ``RPW_LOGGING_ZEROBUS_*`` settings, documented at the top of
``lib/_rpw_logging/zerobus.py``.
``RPW_LOGGING_ZEROBUS=off`` disables it outright.

What is sent: server lifecycle events (start / degraded) plus WARNING-and-above records
from the root logger, redacted by the sink before they leave the process, and one
``mcp.tool_call`` row per MCP tool call (``install_tool_telemetry``). That includes
calls through the ``rpw-mcp-cli`` bridge, which reaches the server over MCP too. Tool
arguments and results are never sent. Nothing here may raise into the server.

Native tool calls use the **in-process** sink, not the detached hand-off: an MCP server is
long-lived, so the first token mint is paid once by a background thread and every
``submit`` after it is a queue put. A detached child per tool call would pay 2–3 s of token
mint on every single call (``docs/process/centralized-logging.md``, "Two transports").
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from types import ModuleType
from typing import Any, Optional


def _sink_module() -> Optional[ModuleType]:
    try:
        from lib._rpw_logging import zerobus  # vendored copy (plugins)

        return zerobus
    except ImportError:
        pass
    try:
        from rpw_logging import zerobus  # canonical package, when installed

        return zerobus
    except ImportError:
        return None


def application_name(server: str) -> str:
    return f"mcp.{server}"


def install(server: str, *, level: int = logging.WARNING) -> bool:
    """Mirror root-logger records at ``level``+ to the table. True when the sink is live."""
    zerobus = _sink_module()
    if zerobus is None:
        return False
    try:
        if not zerobus.get_sink().enabled:
            return False
        root = logging.getLogger()
        if not any(isinstance(h, zerobus.ZerobusHandler) for h in root.handlers):
            root.addHandler(zerobus.ZerobusHandler(application_name(server), level=level))
        return True
    except Exception:  # noqa: BLE001 - telemetry must never break a server
        return False


def event(
    server: str,
    event_name: str,
    *,
    severity: str = "INFO",
    message: Optional[str] = None,
    logger_name: str = "lib.launcher",
    **payload: Any,
) -> bool:
    """Fire-and-forget one lifecycle event (``mcp.server.start``, ``mcp.server.degraded``)."""
    zerobus = _sink_module()
    if zerobus is None:
        return False
    try:
        return zerobus.log_event(
            application_name=application_name(server),
            event_name=event_name,
            severity=severity,
            message=message,
            logger_name=logger_name,
            payload=payload or None,
        )
    except Exception:  # noqa: BLE001
        return False


# ── native MCP tool calls (#1969) ──
#
# The native tool name arrives from the MCP *client*, so it is caller-controlled text. Keep
# it only when it looks like a tool name — the same guard `cli.invocation` puts on a
# subcommand, for the same reason: an unrecognised name is arbitrary client input, and this
# row is an allow-list of names, sizes and flags.
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
UNNAMED_TOOL = "<other>"
TOOL_CALL_EVENT = "mcp.tool_call"


def safe_tool_name(tool: Any) -> str:
    """``tool`` when it looks like a tool name, else ``<other>``. Never raises."""
    return tool if isinstance(tool, str) and _TOOL_NAME_RE.match(tool) else UNNAMED_TOOL


def result_chars(result: Any) -> int:
    """How many characters a tool returned — a length, never a prefix or a sample.

    Reads FastMCP's ``ToolResult`` shape by duck-typing (``content`` blocks, then
    ``structured_content``) so a future result class cannot break a server. Structured
    content is counted only when no text block carried a length, because FastMCP usually
    serializes the same data into both and counting both doubles every size. 0 when
    unmeasurable.
    """
    try:
        blocks = getattr(result, "content", None)
        if blocks is None:
            return len(result) if isinstance(result, str) else len(str(result))
        total = 0
        for block in blocks:
            for attr in ("text", "data"):  # text blocks, then base64 image/audio blocks
                value = getattr(block, attr, None)
                if isinstance(value, str):
                    total += len(value)
                    break
        if total == 0:
            structured = getattr(result, "structured_content", None)
            if structured is not None:
                total = len(json.dumps(structured, default=str))
        return total
    except Exception:  # noqa: BLE001 - a size is never worth an exception
        return 0


def tool_call_payload(
    tool: Any,
    *,
    duration_ms: float,
    chars: int,
    is_error: bool,
    error_type: Optional[str] = None,
) -> dict:
    """The ``mcp.tool_call`` allow-list. Arguments and results structurally cannot enter it.

    Every value is derived here from a name, a size or a flag — nothing is copied out of
    the call's inputs or outputs, so there is no field a prompt could travel in.
    """
    payload: dict[str, Any] = {
        "tool": safe_tool_name(tool),
        "duration_ms": round(float(duration_ms), 1),
        "result_chars": int(chars),
        "is_error": bool(is_error),
    }
    if error_type:
        payload["error_type"] = str(error_type)[:64]
    return payload


def _emit_tool_call(
    server: str,
    tool: Any,
    started: float,
    *,
    chars: int,
    is_error: bool,
    error_type: Optional[str] = None,
) -> None:
    try:
        name = safe_tool_name(tool)
        event(
            server,
            TOOL_CALL_EVENT,
            severity="WARN" if is_error else "INFO",
            message=f"tool {name}" + (" failed" if is_error else ""),
            logger_name="lib.telemetry",
            **tool_call_payload(
                tool,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                chars=chars,
                is_error=is_error,
                error_type=error_type,
            ),
        )
    except Exception:  # noqa: BLE001 - a tool call must never fail over its own telemetry
        pass


def build_tool_middleware(base: type, server: str) -> Any:
    """One FastMCP middleware instance recording ``mcp.tool_call`` rows, given its base class.

    ``base`` is injected rather than imported so the builder is testable without fastmcp;
    :func:`install_tool_telemetry` supplies the real ``fastmcp.server.middleware.Middleware``.
    """

    class ToolCallTelemetry(base):  # type: ignore[misc, valid-type]
        """Times each native tool call and records its name, size and error flag."""

        async def on_call_tool(self, context: Any, call_next: Callable) -> Any:
            started = time.perf_counter()
            tool = getattr(getattr(context, "message", None), "name", None)
            try:
                result = await call_next(context)
            except Exception as exc:
                _emit_tool_call(
                    server,
                    tool,
                    started,
                    chars=0,
                    is_error=True,
                    error_type=type(exc).__name__,
                )
                raise
            _emit_tool_call(
                server,
                tool,
                started,
                chars=result_chars(result),
                is_error=bool(getattr(result, "is_error", False)),
            )
            return result

    return ToolCallTelemetry()


def install_tool_telemetry(mcp: Any, server: str) -> bool:
    """Record one ``mcp.tool_call`` row per native tool call on ``mcp``. True when installed.

    FastMCP middleware is the seam because it *is* the dispatch path. Every surface
    reaches a tool over MCP, the ``rpw-mcp-cli`` bridge included (the in-process
    per-server CLIs were retired in #2143). Returns False, silently, with no sink, no
    middleware API, or on any error at all.
    """
    if mcp is None:
        return False
    zerobus = _sink_module()
    if zerobus is None:
        return False
    try:
        if not zerobus.get_sink().enabled:
            return False
        if not hasattr(mcp, "add_middleware"):
            return False
        from fastmcp.server.middleware import Middleware

        mcp.add_middleware(build_tool_middleware(Middleware, server))
        return True
    except Exception:  # noqa: BLE001 - telemetry must never break a server
        return False
