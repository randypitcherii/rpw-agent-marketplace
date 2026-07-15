#!/usr/bin/env bash
# Worktree-bound file edit guard (#70).
# PreToolUse Edit|Write|MultiEdit gate: when an active build is in progress,
# block file edits whose target falls outside the current worktree's toplevel.
#
# Fail-open scenarios:
# - No active build (no state file): allow.
# - Not in a git checkout: allow.
# - JSON parse failure: allow (don't break unrelated tool calls).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$SCRIPT_DIR/../scripts/build-state.sh"

INPUT=$(cat)

eval "$(python3 -c "
import json, sys, shlex
data = json.loads(sys.stdin.read())
inp = data.get('input', {}) or {}
fp = inp.get('file_path') or ''
print(f'FILE_PATH={shlex.quote(fp)}')
" <<< "$INPUT" 2>/dev/null)" || exit 0

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

source "$LIB" 2>/dev/null || exit 0

# Only enforce during an active build.
STATE_FILE=$(_build_state_file 2>/dev/null) || exit 0
if [ ! -f "$STATE_FILE" ]; then
  exit 0
fi

WORKTREE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0

# Resolve paths through python's os.path.realpath so symlinked tmp paths
# (e.g., macOS /var -> /private/var) compare correctly. macOS ships bash 3.2
# which lacks `mapfile`; use python to emit each value on its own line and
# read them sequentially.
ABS_PATH=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$FILE_PATH")
CANON_WORKTREE=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$WORKTREE_ROOT")
CANON_COORDINATOR=""
if [ -n "${RPW_BUILD_COORDINATOR_DIR:-}" ]; then
  CANON_COORDINATOR=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$RPW_BUILD_COORDINATOR_DIR")
fi

# Allowed: target is inside the worktree root.
case "$ABS_PATH/" in
  "$CANON_WORKTREE/"*) exit 0 ;;
esac

# Allowed: target is inside the coordinator dir (env override) — supports
# workers that need to write back to the coordinator's ledger.
if [ -n "$CANON_COORDINATOR" ]; then
  case "$ABS_PATH/" in
    "$CANON_COORDINATOR/"*) exit 0 ;;
  esac
fi

echo "BLOCKED: file edit target is outside the active build worktree." >&2
echo "  worktree: $WORKTREE_ROOT" >&2
echo "  target:   $ABS_PATH" >&2
echo "If this edit is intentional, end the active build first (make build-clear)." >&2
exit 2
