#!/bin/bash
# skill-telemetry.sh — one agent.skill.load row per Skill tool use (#1969).
#
# Registered on PostToolUse with matcher Skill. Records WHICH skill was loaded and how many
# characters its body cost (skill name, plugin, result chars, harness, session id) — never
# the skill body, never the args it was invoked with. Feeds #1959's helpfulness loop, which
# had to mine local transcripts because these 72 loads produced 0 rows in the table.
#
# Off unless configured: the vendored sink in mcp-servers/lib/_rpw_logging ships with no
# destination, so nothing is sent until ~/.rpw/logging.env holds RPW_LOGGING_ZEROBUS_*
# settings (plugin README, "Centralized logging"). RPW_LOGGING_ZEROBUS=off disables it.
#
# Never blocks, never prints, never fails the tool call: all output goes to /dev/null and
# the work runs detached, so an unreachable sink costs the tool call nothing beyond the
# fork. The hook returns in milliseconds; the child finds a Python >= 3.10, ships the row,
# and exits.
#
#   skill-telemetry.sh        (PostToolUse hook JSON on stdin)

set +e
[ "${RPW_LOGGING_ZEROBUS:-}" = "off" ] && exit 0
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SCRIPT="$PLUGIN_ROOT/hooks/skill_telemetry.py"
[ -f "$SCRIPT" ] || exit 0
PAYLOAD="$(cat 2>/dev/null)"

(
    for py in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$py" >/dev/null 2>&1 \
            && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
            printf '%s' "$PAYLOAD" | "$py" "$SCRIPT"
            exit 0
        fi
    done
) </dev/null >/dev/null 2>&1 &
disown 2>/dev/null
exit 0
