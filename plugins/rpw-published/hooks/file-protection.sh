#!/usr/bin/env bash
# File protection hook for Claude Code PreToolUse (Edit/Write).
# Plugin-owned version. Warns on marketplace manifest / plugin manifest edits.
# Reads tool input JSON from stdin, checks file_path against protected patterns.
# Exit 2 = block action. Non-zero stdout = warning message shown to user.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(data.get('input', {}).get('file_path', ''))
" <<< "$INPUT" 2>/dev/null) || FILE_PATH=""

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

case "$FILE_PATH" in
  */.claude-plugin/marketplace.json|*.claude-plugin/marketplace.json)
    echo "WARNING: Editing marketplace.json — this is the root manifest. Verify changes with 'make check'."
    ;;
  */plugin.json)
    echo "WARNING: Editing a plugin manifest (plugin.json). Verify version and field changes with 'make check'."
    ;;
esac

exit 0
