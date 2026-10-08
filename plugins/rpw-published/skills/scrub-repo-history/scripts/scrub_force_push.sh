#!/usr/bin/env bash
# scrub_force_push.sh — the force-push gate for a history scrub.
#
# A rewritten local mirror is still recoverable. A force-push to a shared branch
# is not: it rewrites what everyone else fetches and can destroy work pushed
# after your backup was taken. This script refuses to push unless BOTH hold:
#
#   1. a real backup mirror exists (a git repo with a non-zero commit count), and
#   2. the operator typed the exact confirmation phrase for this remote/branch.
#
# Usage:
#   scrub_force_push.sh --repo DIR --remote NAME --branch BRANCH \
#                       --backup DIR [--tags] [--dry-run] [--confirm "PHRASE"]
#
# Run it once without --confirm: it prints the required phrase and exits 2.
# Confirmation is per-push. Do not reuse a phrase from an earlier operation.
#
# Exit codes:
#   0  pushed (or --dry-run passed the gate)
#   2  no confirmation, or the phrase did not match
#   3  backup missing or unusable
#   4  branch is protected on the remote (push would be rejected)
#  64  usage error

set -euo pipefail

REPO="."
REMOTE=""
BRANCH=""
BACKUP=""
CONFIRM=""
PUSH_TAGS=0
DRY_RUN=0

usage() {
    sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
    exit 64
}

while [ $# -gt 0 ]; do
    case "$1" in
        --repo)    REPO="${2:?}";   shift 2 ;;
        --remote)  REMOTE="${2:?}"; shift 2 ;;
        --branch)  BRANCH="${2:?}"; shift 2 ;;
        --backup)  BACKUP="${2:?}"; shift 2 ;;
        --confirm) CONFIRM="${2:?}"; shift 2 ;;
        --tags)    PUSH_TAGS=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage ;;
        *) echo "unknown argument: $1" >&2; usage ;;
    esac
done

[ -n "$REMOTE" ] && [ -n "$BRANCH" ] && [ -n "$BACKUP" ] || {
    echo "error: --remote, --branch and --backup are all required" >&2
    usage
}

git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || {
    echo "error: $REPO is not a git repository" >&2
    exit 64
}

# ------------------------------------------------------------- backup gate ---
if ! git -C "$BACKUP" rev-parse --git-dir >/dev/null 2>&1; then
    cat >&2 <<EOF
REFUSING TO PUSH: no backup at $BACKUP

The backup mirror is the only undo for a history rewrite. Take one first:

    git clone --mirror <repo> $BACKUP
EOF
    exit 3
fi

backup_commits=$(git -C "$BACKUP" rev-list --all --count 2>/dev/null || echo 0)
if [ "$backup_commits" -eq 0 ]; then
    echo "REFUSING TO PUSH: backup at $BACKUP has no commits — it is not a usable backup." >&2
    exit 3
fi

# --------------------------------------------------------- protection gate ---
# Best effort: only checks when `gh` is available and the remote is on GitHub.
remote_url=$(git -C "$REPO" remote get-url "$REMOTE" 2>/dev/null || echo "")
if [ -n "$remote_url" ] && command -v gh >/dev/null 2>&1 && printf '%s' "$remote_url" | grep -q 'github\.com'; then
    slug=$(printf '%s' "$remote_url" | sed -e 's#^git@github\.com:##' -e 's#^https://github\.com/##' -e 's#\.git$##')
    if gh api "repos/$slug/branches/$BRANCH/protection" >/dev/null 2>&1; then
        cat >&2 <<EOF
REFUSING TO PUSH: $slug branch '$BRANCH' is protected.

A protected branch rejects a force-push. Do the scrub on the integration branch
and promote it forward through the normal release path. Do not unprotect a
release branch to force a rewrite through it.
EOF
        exit 4
    fi
fi

# ------------------------------------------------------ confirmation gate ---
REQUIRED="force-push $REMOTE/$BRANCH — rewritten history, irreversible, everyone re-clones"

TAGS_NOTE=""
if [ "$PUSH_TAGS" -eq 1 ]; then TAGS_NOTE=" + all tags"; fi

if [ "$CONFIRM" != "$REQUIRED" ]; then
    cat >&2 <<EOF
REFUSING TO PUSH: explicit confirmation required.

About to force-push:
  repo:   $(cd "$REPO" && pwd)
  remote: $REMOTE ${remote_url:+($remote_url)}
  branch: $BRANCH$TAGS_NOTE
  backup: $BACKUP ($backup_commits commits)

This rewrites the shared branch. Every clone, worktree, open PR and pinned SHA
breaks, and anything pushed since the backup was taken will be lost. It cannot
be undone except by restoring the backup mirror.

If the user has approved this, re-run with:

  --confirm "$REQUIRED"
EOF
    exit 2
fi

# ------------------------------------------------------------------ push ---
if [ "$DRY_RUN" -eq 1 ]; then
    echo "gate passed (--dry-run): would run"
    echo "  git -C $REPO push --force $REMOTE $BRANCH"
    if [ "$PUSH_TAGS" -eq 1 ]; then echo "  git -C $REPO push --force --tags $REMOTE"; fi
    exit 0
fi

git -C "$REPO" push --force "$REMOTE" "$BRANCH"
if [ "$PUSH_TAGS" -eq 1 ]; then
    git -C "$REPO" push --force --tags "$REMOTE"
fi

cat <<EOF

Pushed. Now, in this order:
  1. Tell everyone with a clone to RE-CLONE — a 'git pull' merges the old
     history back and undoes the scrub.
  2. Rebase or reopen every affected PR.
  3. Delete stale remote branches/tags still pointing at pre-rewrite history.
  4. Keep the backup mirror at $BACKUP until the rewrite is confirmed good.
  5. If this was a leak: confirm the credential is already rotated and revoked.
EOF
