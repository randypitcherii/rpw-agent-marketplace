#!/usr/bin/env bash
# safety-tilde-guard.sh — PreToolUse hook (Bash matcher)
# Blocks commands that operate on bare ~ (tilde), preventing:
#   1. mkdir with bare ~ — creates a literal "~" directory
#   2. rm targeting bare ~ or ~/ — deletes home directory contents
#
# Input: JSON from PreToolUse with tool_name and input.command
# Exit 0 = allow, Exit 2 = block (with message on stdout)

set -euo pipefail

INPUT=$(cat)

# Extract command from JSON input
COMMAND=$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(data.get('input', {}).get('command', ''))
" <<< "$INPUT" 2>/dev/null) || exit 0

# No command to check
if [ -z "$COMMAND" ]; then
  exit 0
fi

# Check for mkdir with bare ~ (creates literal tilde directory)
# Matches: mkdir ~, mkdir ~/foo, mkdir -p ~, mkdir -p ~/foo
if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)mkdir\s+(-[a-zA-Z]+\s+)*~(/|\s|$)'; then
  echo "BLOCKED: 'mkdir ~' creates a literal tilde directory or modifies your home. Use \$HOME or an absolute path instead."
  exit 2
fi

# Check for rm targeting bare ~ or ~/
# Matches: rm ~, rm -rf ~, rm -rf ~/, rm ~/*, etc.
if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)rm\s+(-[a-zA-Z]+\s+)*~(/|\s|$)'; then
  echo "BLOCKED: 'rm ~' would delete your home directory contents. This is almost certainly not what you want."
  exit 2
fi

exit 0
