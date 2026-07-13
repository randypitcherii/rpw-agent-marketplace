#!/usr/bin/env bash
# orient-gate.sh — shared opt-in gate for the rpw-published "session orientation"
# and "MCP health check" hooks.
#
# These hooks are useful in repos that use this marketplace's issue-tracking +
# MCP conventions, but are unwanted noise (prompt-hijacking / error spam) in an
# arbitrary project a public installer opens. So they are OFF by default and a
# project (or user) must explicitly opt in.
#
# A hook sources this file and calls `rpw_orient_enabled`. Exit 0 = opted in,
# exit 1 = not opted in (hook should exit 0 silently).
#
# Opt-in signals (any one enables):
#   1. Env var   RPW_ORIENT=1              (escape hatch / CI)
#   2. Project   <project>/.claude/rpw-orient.on   (git-trackable per-repo marker)
#   3. User      ~/.claude/rpw-published.local.md  with frontmatter `orientation: true`

rpw_orient_enabled() {
  # 1. Explicit env override.
  case "${RPW_ORIENT:-}" in
    1|true|yes|on) return 0 ;;
    0|false|no|off) return 1 ;;
  esac

  # 2. Per-project marker file. CLAUDE_PROJECT_DIR is set by Claude Code; fall
  #    back to cwd otherwise.
  local project_dir="${CLAUDE_PROJECT_DIR:-$(pwd)}"
  if [ -f "$project_dir/.claude/rpw-orient.on" ]; then
    return 0
  fi

  # 3. User-level plugin-settings flag: `orientation: true` in the frontmatter
  #    of ~/.claude/rpw-published.local.md.
  local local_md="$HOME/.claude/rpw-published.local.md"
  if [ -f "$local_md" ] && grep -qE '^orientation:[[:space:]]*(true|yes|on)[[:space:]]*$' "$local_md" 2>/dev/null; then
    return 0
  fi

  return 1
}
