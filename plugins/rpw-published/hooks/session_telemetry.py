"""Ship one agent-session lifecycle row (see session-telemetry.sh). Never raises.

Reads the Claude Code hook JSON on stdin. Only allow-listed, non-content fields are kept:
the row says a session started / ended / compacted, not what was said in it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

#: Hook-input keys worth keeping. Everything else (prompts, tool input) is dropped.
_KEEP = (
    "source",
    "reason",
    "trigger",
    "model",
    "permission_mode",
    "agent_type",
    "hook_event_name",
)
_EVENTS = {
    "start": "agent.session.start",
    "end": "agent.session.end",
    "precompact": "agent.session.compact",
}


def harness() -> str:
    """``claude-code``, or ``omnigent.<harness>`` when an Omnigent runner launched it.

    Public because ``skill_telemetry.py`` imports it: two hook rows that disagree about
    which harness they came from would be worse than the coupling (#1969).
    """
    if os.environ.get("OMNIGENT_RUNNER_ID"):
        return (
            f"omnigent.{os.environ.get('OMNIGENT_RUNNER_LAUNCH_HARNESS') or 'claude'}"
        )
    return "claude-code"


def build(event: str, hook: dict) -> dict:
    payload = {
        k: hook[k] for k in _KEEP if isinstance(hook.get(k), (str, int, float, bool))
    }
    model = hook.get("model")
    if isinstance(model, dict):  # newer hook schema: {"id": ..., "display_name": ...}
        payload["model"] = model.get("id") or model.get("display_name")
    cwd = hook.get("cwd") or os.getcwd()
    payload.update(
        harness=harness(),
        omnigent_runner_id=os.environ.get("OMNIGENT_RUNNER_ID"),
        cwd=cwd,
        project=Path(cwd).name,
        transcript=Path(hook["transcript_path"]).name
        if hook.get("transcript_path")
        else None,
        plugin="rpw-published",
    )
    detail = payload.get("source") or payload.get("reason") or payload.get("trigger")
    return {
        "application_name": "claude-code",
        "event_name": _EVENTS.get(event, f"agent.session.{event}"),
        "severity": "INFO",
        "message": f"session {event}" + (f" ({detail})" if detail else ""),
        "logger_name": "rpw-published.hooks.session-telemetry",
        "session_id": hook.get("session_id"),
        "payload": {k: v for k, v in payload.items() if v is not None},
    }


def main(argv: list[str]) -> int:
    event = argv[1] if len(argv) > 1 else "unknown"
    try:
        hook = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        hook = {}
    if not isinstance(hook, dict):
        hook = {}
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-servers"))
    try:
        from lib._rpw_logging import zerobus
    except Exception:  # noqa: BLE001 - no vendored sink: nothing to do
        return 0
    try:
        sink = zerobus.get_sink()
        if sink.enabled:
            sink.emit(**build(event, hook))
            sink.flush(20.0)
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
