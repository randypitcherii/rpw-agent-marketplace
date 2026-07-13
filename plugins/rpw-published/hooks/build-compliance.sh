#!/usr/bin/env bash
# Build compliance hook — PreToolUse gate for git commit/merge during /build.
# Plugin-owned version. Sources the canonical build-state library.
# Fail-open when no active build (not in a /build session).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$SCRIPT_DIR/../scripts/build-state.sh"

INPUT=$(cat)

# Parse tool_name and command from JSON input via python3.
eval "$(python3 -c "
import json, sys, shlex
data = json.loads(sys.stdin.read())
print(f'TOOL_NAME={shlex.quote(data.get(\"tool_name\", \"\"))}')
print(f'COMMAND={shlex.quote(data.get(\"input\", {}).get(\"command\", \"\"))}')
" <<< "$INPUT" 2>/dev/null)" || exit 0

# Only gate Bash tool calls.
if [ "$TOOL_NAME" != "Bash" ]; then
  exit 0
fi

source "$LIB" 2>/dev/null || exit 0

STATE_FILE=$(_build_state_file 2>/dev/null) || exit 0
if [ ! -f "$STATE_FILE" ]; then
  exit 0
fi

case "$COMMAND" in
  *"git commit"*)
    CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null) || CURRENT_BRANCH=""
    if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "production" ]; then
      echo "BLOCKED: Cannot commit to $CURRENT_BRANCH during an active build. Switch to your feature branch."
      exit 2
    fi
    if ! build_phase_get check_passed >/dev/null 2>&1; then
      echo "BLOCKED: Cannot commit without passing the check gate. Run 'make check', then 'make build-phase PHASE=check_passed'."
      exit 2
    fi
    ;;
  *"git merge"*)
    EXPECTED_FB=$(python3 -c "
import json, sys
try:
    st = json.load(open(sys.argv[1]))
    fb = st.get('feature_branch') or ''
    print(fb)
except Exception:
    pass
" "$STATE_FILE" 2>/dev/null) || EXPECTED_FB=""
    if [ -n "$EXPECTED_FB" ]; then
      CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null) || CURRENT_BRANCH=""
      if [ "$CURRENT_BRANCH" != "$EXPECTED_FB" ]; then
        echo "BLOCKED: git merge is only allowed on the build feature branch (expected '$EXPECTED_FB', currently on '$CURRENT_BRANCH')."
        exit 2
      fi
    fi
    case "$COMMAND" in
      *"git merge"*"production"*|*"git merge"*"main"*)
        if ! build_phase_get check_passed >/dev/null 2>&1; then
          echo "BLOCKED: Cannot merge without passing the check gate. Run 'make check' first."
          exit 2
        fi
        if ! build_phase_get worktrees_clean >/dev/null 2>&1; then
          echo "WARNING: Merging to default branch without confirming worktrees are clean. Verify with 'git worktree list'."
        fi
        ;;
    esac
    ;;
  *"git add -A"*|*"git add --all"*|*"git add ."*)
    echo "BLOCKED: 'git add -A' / 'git add .' can accidentally stage worktree directories or secrets. Use 'git add <specific-files>' instead."
    exit 2
    ;;
esac

exit 0
