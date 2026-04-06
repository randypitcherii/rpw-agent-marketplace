#!/bin/bash
# session-start-orient.sh — SessionStart hook for automatic session orientation
# Self-contained: gathers git info, beads info, and directory listing inline.

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

## Beads

echo "## Beads"
if [ -d ".beads" ] && command -v bd >/dev/null 2>&1; then
    echo "In progress:"
    bd list --status=in_progress 2>/dev/null | head -5 || echo "not available"
    echo ""
    echo "Ready:"
    bd ready 2>/dev/null | head -5 || echo "not available"
    echo ""
    echo "Blocked:"
    bd blocked 2>/dev/null | head -3 || echo "not available"
else
    echo "No beads project"
fi

echo ""

## Project Files

echo "## Project Files"
ls -la 2>/dev/null | head -20 || echo "not available"

echo ""

## Suggested Next

echo "## Suggested Next"
if [ -d ".beads" ] && command -v bd >/dev/null 2>&1; then
    # Priority: in-progress work first, then highest-priority ready bead
    in_progress_line=$(bd list --status=in_progress 2>/dev/null | head -1)
    if [ -n "$in_progress_line" ]; then
        echo "Continue: $in_progress_line"
    else
        ready_line=$(bd ready 2>/dev/null | head -1)
        if [ -n "$ready_line" ]; then
            echo "Pick up: $ready_line"
        else
            echo "No ready beads. Review recent commits or check for new work."
        fi
    fi
else
    echo "No beads project. Review recent commits or check for open tasks."
fi

echo ""

# Instruction for Claude
echo "---"
echo "Present this session orientation to the user as your first response. Be concise — use the data above to give a brief summary of where things stand and highlight the suggested next activity."

exit 0
