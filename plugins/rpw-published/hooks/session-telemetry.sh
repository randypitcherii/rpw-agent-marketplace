#!/bin/bash
# session-telemetry.sh — agent-session lifecycle rows for the shared Zerobus log table (#891).
#
# Registered on SessionStart, SessionEnd and PreCompact. Records THAT a session started,
# ended or compacted (session id, harness, cwd, source/reason, model) — never prompts,
# transcripts or tool I/O. Transcript shipping is a separate, governed decision (#1240).
#
# Off unless configured: the vendored sink in mcp-servers/lib/_rpw_logging ships with no
# destination, so nothing is sent until ~/.rpw/logging.env holds RPW_LOGGING_ZEROBUS_*
# settings (plugin README, "Centralized logging"). RPW_LOGGING_ZEROBUS=off disables it.
#
# Never blocks, never prints: stdout from a SessionStart hook becomes agent context, so
# all output goes to /dev/null and the work runs detached. The hook returns in
# milliseconds; the child finds a Python >= 3.10, ships the row, and exits.
#
#   session-telemetry.sh <start|end|precompact>    (hook JSON on stdin)

set +e
EVENT="${1:-unknown}"
[ "${RPW_LOGGING_ZEROBUS:-}" = "off" ] && exit 0
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SCRIPT="$PLUGIN_ROOT/hooks/session_telemetry.py"
[ -f "$SCRIPT" ] || exit 0
PAYLOAD="$(cat 2>/dev/null)"

(
    for py in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$py" >/dev/null 2>&1 \
            && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
            printf '%s' "$PAYLOAD" | "$py" "$SCRIPT" "$EVENT"
            exit 0
        fi
    done
) </dev/null >/dev/null 2>&1 &
disown 2>/dev/null
exit 0
