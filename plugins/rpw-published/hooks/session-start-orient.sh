#!/bin/bash
# session-start-orient.sh — SessionStart hook for automatic session orientation
# Self-contained: gathers git info, GitHub Issues info, and directory listing inline.
#
# OFF by default: this hook injects a "present orientation as your first
# response" instruction and assumes this marketplace's GitHub-Issues +
# `status: in-progress` label taxonomy. That is prompt-hijacking noise in an
# arbitrary project. A project/user must opt in — see scripts/orient-gate.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../scripts/orient-gate.sh
source "$SCRIPT_DIR/../scripts/orient-gate.sh" 2>/dev/null || exit 0
rpw_orient_enabled || exit 0

## Git State

if git rev-parse --git-dir >/dev/null 2>&1; then
    current_branch=$(git branch --show-current 2>/dev/null || echo "detached")

    default_branch=""
    for candidate in main production master; do
        if git show-ref --verify --quiet "refs/heads/$candidate" 2>/dev/null; then
            default_branch="$candidate"
            break
        fi
    done

    echo "## Git State"
    echo "Branch: $current_branch"
    [ -n "$default_branch" ] && echo "Default: $default_branch"
    echo ""
    echo "Status:"
    git status --short 2>/dev/null | head -10 || echo "not available"
    echo ""
    echo "Recent commits:"
    git log --oneline -5 2>/dev/null || echo "not available"

    worktree_count=$(git worktree list 2>/dev/null | wc -l | tr -d ' ')
    if [ "${worktree_count:-0}" -gt 1 ]; then
        echo ""
        echo "Worktrees:"
        git worktree list 2>/dev/null || echo "not available"
    fi
else
    echo "## Git State"
    echo "No git repository"
fi

echo ""

## GitHub Issues

echo "## GitHub Issues"
if command -v gh >/dev/null 2>&1; then
    echo "In progress:"
    gh issue list --label "status: in-progress" --limit 5 2>/dev/null || echo "not available"
    echo ""
    echo "Open:"
    gh issue list --state open --limit 5 2>/dev/null || echo "not available"
else
    echo "gh CLI not available. Install: https://cli.github.com"
fi

echo ""

## Project Files

echo "## Project Files"
ls -la 2>/dev/null | head -20 || echo "not available"

echo ""

## Suggested Next

echo "## Suggested Next"
if command -v gh >/dev/null 2>&1; then
    # Priority: in-progress work first, then oldest open issue
    in_progress_line=$(gh issue list --label "status: in-progress" --limit 1 --json number,title --jq '.[0] | "#\(.number) \(.title)"' 2>/dev/null)
    if [ -n "$in_progress_line" ]; then
        echo "Continue: $in_progress_line"
    else
        ready_line=$(gh issue list --state open --limit 1 --json number,title --jq '.[0] | "#\(.number) \(.title)"' 2>/dev/null)
        if [ -n "$ready_line" ]; then
            echo "Pick up: $ready_line"
        else
            echo "No open issues. Review recent commits or check for new work."
        fi
    fi
else
    echo "gh CLI not available. Review recent commits or check for open tasks."
fi

echo ""

# Instruction for Claude
echo "---"
echo "Present this session orientation to the user as your first response. Be concise — use the data above to give a brief summary of where things stand and highlight the suggested next activity."

exit 0
