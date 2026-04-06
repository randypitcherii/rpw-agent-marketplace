#!/usr/bin/env bash
# destructive-command-guard.sh — PreToolUse hook (Bash matcher)
# Blocks catastrophic commands that can cause irreversible damage.
#
# Categories:
#   1. Filesystem destruction: rm -rf /, chmod -R 777 /, etc.
#   2. Privilege escalation: sudo, su
#   3. Disk/partition tools: dd, mkfs, fdisk, parted
#   4. Git destructive operations: force-push, reset --hard to remote
#   5. Process/system kill: kill -9 1, killall, shutdown, reboot
#
# Design: Uses regex matching (not string prefix) to resist variable
# expansion bypass (see CVE-2025-66032 re: deny-list prefix matching).
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

# === 1. Filesystem destruction ===

# rm -rf / or rm -rf /* (with any flag combos)
if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)rm\s+(-[a-zA-Z]*[rR][a-zA-Z]*\s+)*(/\s|/\*|/\s*$)'; then
  echo "BLOCKED: 'rm -rf /' would destroy the entire filesystem. This command is never safe to run."
  exit 2
fi

# chmod/chown -R on root
if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)(chmod|chown)\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)\S+\s+/\s*$'; then
  echo "BLOCKED: Recursive chmod/chown on '/' would break the entire system."
  exit 2
fi

# === 2. Privilege escalation ===

if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)sudo\s'; then
  echo "BLOCKED: 'sudo' runs commands with elevated privileges. Claude Code should not require root access. If you need this, run it manually."
  exit 2
fi

if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)su\s+(-|root)'; then
  echo "BLOCKED: 'su' switches to another user. Claude Code should not require privilege escalation."
  exit 2
fi

# === 3. Disk/partition tools ===

if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)(dd|mkfs(\.[a-z0-9]+)?|fdisk|parted|diskutil)\s'; then
  echo "BLOCKED: Low-level disk tools (dd, mkfs, fdisk, parted, diskutil) can destroy disk partitions. Run manually if truly needed."
  exit 2
fi

# === 4. Git destructive operations ===

# git push --force (or -f) to main/master/production
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*(-f|--force|--force-with-lease)'; then
  # Check if targeting protected branches
  if echo "$COMMAND" | grep -qE '(main|master|production)'; then
    echo "BLOCKED: Force-push to protected branch (main/master/production) would rewrite shared history. This is almost never safe."
    exit 2
  fi
  echo "WARNING: Force-push detected. Verify this is intentional and not targeting a shared branch."
fi

# git reset --hard with remote ref (discards all local work)
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard\s+(origin|upstream)/'; then
  echo "BLOCKED: 'git reset --hard <remote>' discards all local changes irreversibly. Use 'git stash' or create a backup branch first."
  exit 2
fi

# === 5. Process/system commands ===

if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)(shutdown|reboot|halt|init\s+[06])\s*'; then
  echo "BLOCKED: System shutdown/reboot commands should not be run by Claude Code."
  exit 2
fi

if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)kill\s+(-9\s+)?1(\s|$)'; then
  echo "BLOCKED: Killing PID 1 (init/launchd) would crash the system."
  exit 2
fi

if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)killall\s'; then
  echo "BLOCKED: 'killall' can terminate critical processes. Use 'kill <specific-pid>' instead."
  exit 2
fi

# === 6. Dangerous redirects ===

if echo "$COMMAND" | grep -qE '>\s*/dev/sd[a-z]'; then
  echo "BLOCKED: Writing directly to a block device would destroy the filesystem on that disk."
  exit 2
fi

if echo "$COMMAND" | grep -qE '(^|[;&|]\s*):()\s*\{\s*:\|\:&\s*\}\s*;'; then
  echo "BLOCKED: Fork bomb detected. This would crash the system by exhausting process resources."
  exit 2
fi

exit 0
