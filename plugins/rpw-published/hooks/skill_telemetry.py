"""Ship one ``agent.skill.load`` row per Skill tool use (see skill-telemetry.sh). Never raises.

Reads the Claude Code ``PostToolUse`` hook JSON on stdin. The row says *which* skill was
loaded and *how big* its body was — never the body, never the ``args`` the skill was invoked
with. Building the payload from an allow-list of derived values (a name, a length, a flag)
rather than filtering the hook input is what makes that structural instead of careful:
there is no field on this row that a prompt or an argument could travel in.

Why the size matters: #1959's helpfulness loop reads "which skills actually get loaded, and
how much context does each one cost" out of `log_events`, which is why 72 local skill loads
with 0 rows in the table was the symptom (#1969).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # sibling hook module, same plugin dir — always shipped together
    from session_telemetry import harness
except Exception:  # noqa: BLE001 - telemetry plumbing must never fail a tool call

    def harness() -> str:
        return "claude-code"


EVENT_NAME = "agent.skill.load"
#: Skill names are model-chosen text, so keep one only when it looks like a skill name:
#: ``plugin:skill``, ``apps/web:deploy`` (directory-scoped), or a bare ``skill``.
_SKILL_RE = re.compile(r"^[A-Za-z0-9_./:-]{1,80}$")
UNKNOWN_SKILL = "<unknown>"
#: ``tool_input`` keys that have carried the skill name. ``args`` is deliberately absent.
_NAME_KEYS = ("skill", "name")


def safe_skill(value: object) -> str:
    """``value`` when it looks like a skill name, else ``<unknown>``. Never raises."""
    if isinstance(value, str):
        stripped = value.strip()
        if _SKILL_RE.match(stripped):
            return stripped
    return UNKNOWN_SKILL


def skill_name(hook: dict) -> str:
    tool_input = hook.get("tool_input")
    if isinstance(tool_input, dict):
        for key in _NAME_KEYS:
            candidate = safe_skill(tool_input.get(key))
            if candidate != UNKNOWN_SKILL:
                return candidate
    return UNKNOWN_SKILL


def response_chars(response: object) -> int:
    """How many characters the skill body came back as — a length, never a sample."""
    if response is None:
        return 0
    if isinstance(response, str):
        return len(response)
    try:
        return len(json.dumps(response, default=str))
    except Exception:  # noqa: BLE001 - a size is never worth an exception
        return len(str(response))


def build(hook: dict) -> dict:
    """The ``agent.skill.load`` row. Every payload value is a name, a size or a flag."""
    skill = skill_name(hook)
    prefix, _, bare = skill.rpartition(":")
    # Two different prefixes share the `<prefix>:<skill>` shape: a plugin name, and a
    # directory scope like `apps/web`. Reporting the latter as `plugin` would invent a
    # plugin called `apps/web` in #1959's `GROUP BY plugin` (#1972).
    directory_scoped = "/" in prefix
    cwd = hook.get("cwd") or str(Path.cwd())
    payload = {
        "skill": bare,
        "plugin": None if directory_scoped else (prefix or None),
        "scope": prefix if directory_scoped else None,
        "result_chars": response_chars(hook.get("tool_response")),
        "harness": harness(),
        "cwd": cwd,
        "project": Path(cwd).name,
    }
    return {
        "application_name": "claude-code",
        "event_name": EVENT_NAME,
        "severity": "INFO",
        "message": f"skill load {skill}",
        "logger_name": "rpw-published.hooks.skill-telemetry",
        "session_id": hook.get("session_id"),
        "payload": {k: v for k, v in payload.items() if v is not None},
    }


def is_skill_use(hook: dict) -> bool:
    """True for a Skill tool use. The manifest matcher already scopes this hook to ``Skill``;
    this is the second lock, so a broader registration cannot mint skill rows for Bash."""
    tool = hook.get("tool_name")
    return tool is None or tool == "Skill"


def main(argv: list[str]) -> int:
    try:
        hook = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        hook = {}
    if not isinstance(hook, dict):
        hook = {}
    if not is_skill_use(hook):
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-servers"))
    try:
        from lib._rpw_logging import zerobus
    except Exception:  # noqa: BLE001 - no vendored sink: nothing to do
        return 0
    try:
        sink = zerobus.get_sink()
        if sink.enabled:
            sink.emit(**build(hook))
            sink.flush(20.0)
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
