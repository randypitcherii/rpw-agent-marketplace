#!/usr/bin/env bash
# Build finalize — end-of-branch lifecycle cleanup.
#
# Safe to call regardless of merge state:
#   - If the current feature branch is fully merged into origin/<default>,
#     drops the local feature branch and pulls latest in both this worktree
#     and the user's main (non-worktree) clone.
#   - If the feature branch is NOT yet merged (or the fetch fails), exits 0
#     with a friendly message and changes nothing.
#
# Main-clone sync uses git pull --ff-only --autostash, which handles
# unrelated uncommitted changes safely via stash-pull-pop. A conflict only
# occurs when the pull touches the same files the user is actively editing;
# in that case a HOLD note is surfaced for manual resolution.
#
# After a successful sync, refreshes the Claude Code marketplace index
# (best-effort) so new plugin versions are visible without a session restart.
#
# Sourceable; entry point is build_finalize. Run from anywhere inside the
# build worktree (no args).
#
# Log prefix: 'build-finalize:'

# Capture this file's own directory at source time, mirroring build-state.sh.
_RPW_BUILD_FINALIZE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"

# ---------------------------------------------------------------------------
# Path / config resolution
# ---------------------------------------------------------------------------

_build_finalize_git_root() {
  git rev-parse --show-toplevel 2>/dev/null
}

_build_finalize_yml_file() {
  local root
  root=$(_build_finalize_git_root) || return 1
  echo "$root/.rpw/build.yml"
}

# Determine the default branch. Resolution order:
#   1. .rpw/build.yml top-level `default_branch:` key (no yaml dep — grep)
#   2. origin/HEAD symbolic ref
#   3. `production` fallback
_build_finalize_default_branch() {
  local yml
  yml=$(_build_finalize_yml_file 2>/dev/null) || true
  if [ -n "$yml" ] && [ -f "$yml" ]; then
    local from_yml
    from_yml=$(grep -E '^default_branch:[[:space:]]*' "$yml" 2>/dev/null \
      | sed -E 's/^default_branch:[[:space:]]*//; s/[[:space:]]+$//' \
      | head -n1)
    if [ -n "$from_yml" ]; then
      echo "$from_yml"
      return 0
    fi
  fi
  local from_remote
  from_remote=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null \
    | sed 's|^origin/||')
  if [ -n "$from_remote" ]; then
    echo "$from_remote"
    return 0
  fi
  echo "production"
}

# Optional MAIN_CLONE override from .rpw/build.yml. Empty if not set.
_build_finalize_main_clone_override() {
  local yml
  yml=$(_build_finalize_yml_file 2>/dev/null) || return 0
  if [ -n "$yml" ] && [ -f "$yml" ]; then
    grep -E '^main_clone:[[:space:]]*' "$yml" 2>/dev/null \
      | sed -E 's/^main_clone:[[:space:]]*//; s/[[:space:]]+$//' \
      | head -n1
  fi
}

# Detect the main (non-worktree) clone path. Resolution:
#   1. main_clone override in .rpw/build.yml
#   2. dirname of `git rev-parse --git-common-dir` (the clone holding .git/)
_build_finalize_main_clone_path() {
  local override
  override=$(_build_finalize_main_clone_override)
  if [ -n "$override" ]; then
    echo "$override"
    return 0
  fi
  local common
  common=$(git rev-parse --git-common-dir 2>/dev/null) || return 1
  # When common-dir is relative, resolve relative to the current worktree root.
  if [[ "$common" != /* ]]; then
    local root
    root=$(_build_finalize_git_root) || return 1
    common="$root/$common"
  fi
  # Normalize: dirname of the .git directory == clone path.
  # `git rev-parse --git-common-dir` returns the .git dir itself (or its parent
  # if the worktree is the main clone).
  local parent
  parent=$(cd "$common/.." 2>/dev/null && pwd) || return 1
  echo "$parent"
}

# ---------------------------------------------------------------------------
# Merge-check (the critical-correctness function)
# ---------------------------------------------------------------------------

# _build_finalize_check_merged <feature-branch> <default-branch>
# Returns 0 iff the feature branch's changes are fully represented in
# origin/<default-branch>. Handles regular merges, fast-forwards, squash
# merges, and rebases.
# Does NOT fetch; the caller decides whether to fetch first.
_build_finalize_check_merged() {
  local feature="${1:?usage: _build_finalize_check_merged <feature> <default>}"
  local default="${2:?usage: _build_finalize_check_merged <feature> <default>}"
  # Verify origin/<default> ref exists locally; if not, refuse to claim merged.
  if ! git rev-parse --verify --quiet "refs/remotes/origin/${default}" >/dev/null 2>&1; then
    return 1
  fi
  # Fast path: ancestor check covers regular merges, fast-forwards, and rebases.
  if git merge-base --is-ancestor HEAD "refs/remotes/origin/${default}" 2>/dev/null; then
    return 0
  fi
  # Authoritative path (#165): if a merged PR exists for this branch, the work
  # is merged regardless of diff state. This handles the false-positive where an
  # intervening commit on the default branch also touched a file the feature
  # touched — then HEAD's file differs from origin/<default>'s by the
  # intervening hunks, even though the squash merge correctly applied the
  # feature's diff. Degrade gracefully: on any gh error, gh absence, empty
  # output, or zero count, do NOT return — fall through to the diff-equality
  # fallback below (preserves gh-free operation and the genuinely-unmerged path).
  if command -v gh >/dev/null 2>&1; then
    local merged_count
    merged_count=$(gh pr list --state merged --head "$feature" --json number --jq 'length' 2>/dev/null) || merged_count=""
    if [ -n "$merged_count" ] && [ "$merged_count" -gt 0 ] 2>/dev/null; then
      return 0
    fi
  fi
  # Fallback: diff-equality check for squash merges (topologically disjoint).
  # Find the common ancestor between our feature branch and origin/<default>.
  local base
  base=$(git merge-base HEAD "refs/remotes/origin/${default}" 2>/dev/null) || return 1
  # List files changed in the feature branch vs the merge-base.
  local files
  files=$(git diff --name-only "$base"..HEAD)
  # If no files differ, the feature branch contains only metadata (e.g. empty
  # commits). We cannot confirm equivalence via diff, so conservatively treat
  # this as unmerged to avoid false positives.
  [ -z "$files" ] && return 1
  # For each changed file, check whether the version on origin/<default> now
  # matches our feature branch's version. Use the pathspec form of git diff
  # (not HEAD:file vs remote:file) so that deleted files on both sides are
  # treated as identical (both absent == no diff == merged).
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if ! git diff --quiet HEAD "refs/remotes/origin/${default}" -- "$f" 2>/dev/null; then
      return 1
    fi
  done <<< "$files"
  return 0
}

# ---------------------------------------------------------------------------
# Cleanup steps
# ---------------------------------------------------------------------------

# In the current build worktree:
#   - checkout the default branch (no-op if already there)
#   - fast-forward pull
#   - delete the local feature branch (if it exists locally and isn't current)
# Each step is best-effort: failures are logged and DO NOT abort the rest of
# finalize. The summary reports the true outcome rather than claiming success.
#
# Sets these globals for the summary:
#   _BUILD_FINALIZE_WORKTREE_BRANCH — branch we ended up on
#   _BUILD_FINALIZE_WORKTREE_NOTE   — human-readable note (empty on full success)
_build_finalize_worktree() {
  local default="$1"
  local feature="$2"
  _BUILD_FINALIZE_WORKTREE_NOTE=""

  local current
  current=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")

  if [ "$current" != "$default" ]; then
    if git checkout "$default" 2>/dev/null; then
      :
    else
      _BUILD_FINALIZE_WORKTREE_NOTE="checkout skipped — $default likely checked out in another worktree"
      _BUILD_FINALIZE_WORKTREE_BRANCH="$current"
      echo "build-finalize: $_BUILD_FINALIZE_WORKTREE_NOTE"
      return 0
    fi
  fi

  if ! git pull --ff-only origin "$default" 2>/dev/null; then
    echo "build-finalize: warning — fast-forward pull of $default failed in worktree"
  fi

  # Delete local feature branch if it still exists and we're not on it.
  if [ -n "$feature" ] && [ "$feature" != "$default" ]; then
    if git rev-parse --verify --quiet "refs/heads/$feature" >/dev/null 2>&1; then
      if git branch -D "$feature" >/dev/null 2>&1; then
        echo "build-finalize: deleted local branch $feature"
      else
        echo "build-finalize: warning — could not delete local branch $feature"
      fi
    fi
  fi

  _BUILD_FINALIZE_WORKTREE_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "?")
}

# Sync the main (non-worktree) clone:
#   - Detect main clone path
#   - If it's the same as current worktree, skip (no separate clone exists)
#   - If it's on a different branch, log warning and skip
#   - Otherwise: git fetch --prune origin + git pull --ff-only --autostash origin <default>
#
# The --autostash flag handles unrelated uncommitted changes safely via a
# stash-pull-pop sequence. A conflict only arises when the pull touches files
# the user is actively editing; in that case the stash is left intact and a
# HOLD note is surfaced so the user knows where to look.
#
# After a successful pull, attempts a best-effort marketplace index refresh
# so new plugin versions become visible without a session restart.
#
# NEVER switches branches under the user.
#
# Sets globals for the summary:
#   _BUILD_FINALIZE_MAIN_PATH   — path of the main clone (or empty if skipped)
#   _BUILD_FINALIZE_MAIN_NOTE   — note (empty on full success, or reason skipped)
#   _BUILD_FINALIZE_MAIN_BRANCH — branch in main clone
_build_finalize_main_clone() {
  local default="$1"
  _BUILD_FINALIZE_MAIN_PATH=""
  _BUILD_FINALIZE_MAIN_NOTE=""
  _BUILD_FINALIZE_MAIN_BRANCH=""

  local main_path
  main_path=$(_build_finalize_main_clone_path) || {
    _BUILD_FINALIZE_MAIN_NOTE="could not determine main clone path"
    echo "build-finalize: $_BUILD_FINALIZE_MAIN_NOTE"
    return 0
  }

  local current_root
  current_root=$(_build_finalize_git_root) || return 0
  if [ "$main_path" = "$current_root" ]; then
    _BUILD_FINALIZE_MAIN_NOTE="no separate main clone (this worktree IS the main checkout)"
    echo "build-finalize: $_BUILD_FINALIZE_MAIN_NOTE"
    return 0
  fi
  if [ ! -d "$main_path/.git" ] && [ ! -f "$main_path/.git" ]; then
    _BUILD_FINALIZE_MAIN_NOTE="main clone path does not look like a git checkout: $main_path"
    echo "build-finalize: $_BUILD_FINALIZE_MAIN_NOTE"
    return 0
  fi
  _BUILD_FINALIZE_MAIN_PATH="$main_path"

  local main_branch
  main_branch=$(git -C "$main_path" symbolic-ref --short HEAD 2>/dev/null || echo "")
  _BUILD_FINALIZE_MAIN_BRANCH="$main_branch"
  if [ "$main_branch" != "$default" ]; then
    _BUILD_FINALIZE_MAIN_NOTE="main clone on '$main_branch' (expected '$default') — not syncing"
    echo "build-finalize: $_BUILD_FINALIZE_MAIN_NOTE"
    return 0
  fi

  if ! git -C "$main_path" fetch --prune origin 2>/dev/null; then
    _BUILD_FINALIZE_MAIN_NOTE="fetch failed in main clone — not syncing"
    echo "build-finalize: $_BUILD_FINALIZE_MAIN_NOTE"
    return 0
  fi

  # Pull with --autostash to handle unrelated uncommitted changes safely.
  # Git's stash-pull-pop sequence only conflicts when the pull touches files
  # the user is actively editing; in that case surface a HOLD note.
  if ! git -C "$main_path" pull --ff-only --autostash origin "$default" >/dev/null 2>&1; then
    # Capture the autostash conflict detail so the user knows where to look.
    local stash_ref
    stash_ref=$(git -C "$main_path" stash list 2>/dev/null | head -n1)
    _BUILD_FINALIZE_MAIN_NOTE="autostash conflict on pull — manual resolve needed. stash: ${stash_ref:-<none>}"
    echo "build-finalize: $_BUILD_FINALIZE_MAIN_NOTE"
    return 0  # do not fail the whole finalize; surface the note for the HOLD box.
  fi

  # Best-effort: refresh Claude Code's marketplace index so new plugin
  # versions become visible without a session restart. Skip silently if
  # `claude` CLI isn't on PATH.
  if command -v claude >/dev/null 2>&1; then
    claude plugin marketplace update rpw-agent-marketplace >/dev/null 2>&1 || true
  fi
}

# Print final state.
_build_finalize_summary() {
  local default="$1"
  local worktree_root
  worktree_root=$(_build_finalize_git_root 2>/dev/null || echo "?")
  local worktree_sha
  worktree_sha=$(git rev-parse --short HEAD 2>/dev/null || echo "?")
  local worktree_clean="clean"
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    worktree_clean="DIRTY"
  fi
  local wt_branch="${_BUILD_FINALIZE_WORKTREE_BRANCH:-?}"
  local wt_note="${_BUILD_FINALIZE_WORKTREE_NOTE:-}"

  if [ -n "$_BUILD_FINALIZE_MAIN_PATH" ] && [ -z "$_BUILD_FINALIZE_MAIN_NOTE" ]; then
    local main_sha
    main_sha=$(git -C "$_BUILD_FINALIZE_MAIN_PATH" rev-parse --short HEAD 2>/dev/null || echo "?")
    local main_clean="clean"
    if [ -n "$(git -C "$_BUILD_FINALIZE_MAIN_PATH" status --porcelain 2>/dev/null)" ]; then
      main_clean="DIRTY"
    fi
    echo "build-finalize: main clone ($_BUILD_FINALIZE_MAIN_PATH): $_BUILD_FINALIZE_MAIN_BRANCH at $main_sha, $main_clean"
  else
    echo "build-finalize: main clone: skipped (${_BUILD_FINALIZE_MAIN_NOTE:-no detail})"
  fi

  if [ -n "$wt_note" ]; then
    echo "build-finalize: worktree ($worktree_root): $wt_branch at $worktree_sha, $worktree_clean ($wt_note)"
  else
    echo "build-finalize: worktree ($worktree_root): $wt_branch at $worktree_sha, $worktree_clean"
  fi
}

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

build_finalize() {
  set -uo pipefail
  local default feature
  default=$(_build_finalize_default_branch)
  feature=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")

  if [ -z "$feature" ]; then
    echo "build-finalize: not on a branch (detached HEAD) — skipping cleanup." >&2
    return 0
  fi

  # Fetch origin/<default> first so the merge-check has fresh data.
  if ! git fetch origin "$default" 2>/dev/null; then
    echo "build-finalize: warning — could not fetch origin/$default. Cannot determine merge state — skipping cleanup."
    echo "build-finalize: run 'make build-finalize' again with network access after the PR merges."
    return 0
  fi

  if ! _build_finalize_check_merged "$feature" "$default"; then
    echo "build-finalize: feature branch '$feature' has unmerged commits vs origin/$default — skipping cleanup."
    echo "build-finalize: run 'make build-finalize' again after the PR merges."
    return 0
  fi

  echo "build-finalize: '$feature' fully merged into origin/$default — proceeding with cleanup."
  _build_finalize_worktree "$default" "$feature"
  _build_finalize_main_clone "$default"
  _build_finalize_summary "$default"
}
