#!/usr/bin/env python3
"""iMessage MCP server — FastMCP wrapping the `imsg` CLI in BASIC MODE only.

Two deliberately-scoped capabilities (see issue #284):

1. Read-only message search — `search`, `history`, `chats` against the local
   `chat.db`. Read commands NEVER mutate state. They are the only subcommands the
   read path is allowed to invoke (enforced by `_run_read`).
2. Send-only "notify-me" alerts — `imessage_notify_me` can send a text to exactly
   one recipient, the `NOTIFY_ME_HANDLE` configured in the env file. The tool takes
   no recipient argument, so an agent cannot redirect it to anyone else.

Basic mode requires only Full Disk Access + Automation permission. This server
never touches `imsg`'s advanced/IMCore bridge commands (react, edit, unsend,
typing, launch, …), which need System Integrity Protection disabled. SIP stays on.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP(name="imessage-mcp")

# Resolve the imsg binary once. Override with IMSG_BIN for non-standard installs.
_IMSG = os.getenv("IMSG_BIN") or shutil.which("imsg") or "imsg"

# The recipient for notify-me. Read at import time from the env file; the send tool
# exposes no recipient parameter, so this is the ONLY address it can ever reach.
_NOTIFY_ME_HANDLE = os.getenv("NOTIFY_ME_HANDLE", "")
_NOTIFY_ME_SERVICE = os.getenv("NOTIFY_ME_SERVICE", "imessage")

# Subcommands the read path may invoke. All are read-only against chat.db.
# `send` is intentionally absent — it is reachable ONLY through `imessage_notify_me`.
_READ_COMMANDS = {"search", "history", "chats"}

_TIMEOUT_SECONDS = 30


def _err(message: str, **extra: object) -> str:
    """Shape a JSON error string matching imsg's own {success:false,error:...} envelope."""
    return json.dumps({"success": False, "error": message, **extra})


def _run(args: list[str]) -> str:
    """Invoke `imsg` with list args (no shell). Return stdout, or a JSON error string."""
    try:
        proc = subprocess.run(
            [_IMSG, *args],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return _err(
            f"`imsg` binary not found at '{_IMSG}'. Install with "
            "`brew install steipete/tap/imsg` or set IMSG_BIN."
        )
    except subprocess.TimeoutExpired:
        return _err(f"`imsg {args[0]}` timed out after {_TIMEOUT_SECONDS}s.")

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return _err(
            f"`imsg {args[0]}` exited {proc.returncode}.",
            detail=detail,
            hint=(
                "If this is a permissions error, grant the terminal/host app Full Disk "
                "Access (System Settings > Privacy & Security) and Automation permission."
            ),
        )
    return proc.stdout.strip() or _err("`imsg` returned empty output.")


def _run_read(subcommand: str, args: list[str]) -> str:
    """Read path. Hard-asserts the subcommand is a known read-only command."""
    if subcommand not in _READ_COMMANDS:
        # Defensive: this can only fire on a coding error, never on tool input.
        return _err(f"Refusing to run non-read subcommand '{subcommand}'.")
    return _run([subcommand, *args, "--json"])


# --- Read-only search tools -------------------------------------------------


@mcp.tool
def imessage_search(query: str, match: str = "contains", limit: int = 50) -> str:
    """Search local iMessage/SMS history for a phrase (read-only).

    Use this to recover context or surface forgotten tasks/to-dos buried in messages.
    query: text to look for. match: "contains" (default) or "exact" (case-insensitive
    exact text). limit: max results, clamped to 1-200. Returns JSON message rows.
    """
    if not query.strip():
        return _err("query must be non-empty.")
    match = match if match in {"contains", "exact"} else "contains"
    limit = min(max(limit, 1), 200)
    return _run_read(
        "search",
        ["--query", query, "--match", match, "--limit", str(limit)],
    )


@mcp.tool
def imessage_list_chats(limit: int = 20) -> str:
    """List recent conversations (read-only). Returns JSON with each chat's id,
    participants, service, and last_message_at. Use a chat `id` with
    `imessage_recent` to pull that conversation's messages. limit clamped to 1-200.
    """
    limit = min(max(limit, 1), 200)
    return _run_read("chats", ["--limit", str(limit)])


@mcp.tool
def imessage_recent(
    chat_id: int = 0,
    limit: int = 20,
    participants: str = "",
    start: str = "",
    end: str = "",
) -> str:
    """Show recent messages for a conversation (read-only).

    Identify the conversation by `chat_id` (a rowid from `imessage_list_chats`) and/or
    `participants` (comma-separated handles). limit clamped to 1-200. Optional `start`
    / `end` are ISO8601 bounds (start inclusive, end exclusive). Returns JSON rows.
    """
    if chat_id <= 0 and not participants.strip():
        return _err("Provide chat_id (from imessage_list_chats) or participants.")
    limit = min(max(limit, 1), 200)
    args = ["--limit", str(limit)]
    if chat_id > 0:
        args += ["--chat-id", str(chat_id)]
    if participants.strip():
        args += ["--participants", participants]
    if start.strip():
        args += ["--start", start]
    if end.strip():
        args += ["--end", end]
    return _run_read("history", args)


# --- Send-only alert path ---------------------------------------------------


@mcp.tool
def imessage_notify_me(text: str) -> str:
    """Send an iMessage alert to the owner of this machine — send-only, fixed recipient.

    iMessage is a high-signal, low-noise channel, so this is a good way for an agent
    to push an alert (a finished long task, something that needs attention) to the
    user's phone. The recipient is the NOTIFY_ME_HANDLE configured at setup; this tool
    takes no recipient argument and can reach no one else. text: the alert body.
    """
    if not _NOTIFY_ME_HANDLE:
        return _err(
            "NOTIFY_ME_HANDLE is not configured. Set it in the imessage server env "
            "file (template.env -> dev.env) to your own phone number or iMessage email."
        )
    if not text.strip():
        return _err("text must be non-empty.")
    return _run(
        [
            "send",
            "--to",
            _NOTIFY_ME_HANDLE,
            "--text",
            text,
            "--service",
            _NOTIFY_ME_SERVICE,
            "--json",
        ]
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
