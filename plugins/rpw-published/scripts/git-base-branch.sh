#!/usr/bin/env bash
# Base-branch resolution — the one place that decides what a new branch is cut from.
#
# The failure this prevents: a work branch cut off a stale local default ref, or
# off the FORK's default branch when the real base is the PARENT repo's default
# branch. Both produce a PR whose diff carries already-merged work and conflicts
# on contact — pure review noise.
#
# The rule, in order:
#   1. Is this repo a fork? (`gh repo view --json isFork,parent`, or an
#      `upstream` remote distinct from `origin`.)
#   2. Base remote = the PARENT repo's remote when a fork, else `origin`.
#   3. That remote's default branch, resolved dynamically — never hardcoded.
#   4. `git fetch <remote> <branch>` FIRST, then branch from `<remote>/<branch>`.
#   5. A fork with no `upstream` remote fails loudly with the exact
#      `git remote add` command — never a silent fallback to `origin`.
#
# Env:
#   GIT / GH                      injectable, so every call site is mockable
#   RPW_BASE_BRANCH_GH_TIMEOUT    seconds a single `gh repo view` may take (default 5)
#   RPW_BASE_BRANCH_OFFLINE=1     no network at all: no `gh`, no `ls-remote`.
#                                 Callers that must not touch the network set this
#                                 (the drift advisory does, via
#                                 RPW_WORKTREE_DRIFT_NO_FETCH=1 — #1753).
#
# Entry points (sourceable; all I/O via ${GIT:-git} / ${GH:-gh} so they're
# mockable — see tests/test_git_base_branch.py):
#
#   base_remote                  -> prints the remote to branch from
#   base_default_branch <remote> -> prints that remote's default branch name
#   base_ref [--no-fetch]        -> fetches, then prints `<remote>/<branch>`
#
# CLI:
#   git-base-branch.sh ref [--no-fetch]        # `<remote>/<branch>`, after fetch
#   git-base-branch.sh remote                  # the remote alone
#   git-base-branch.sh branch [<remote>]       # the default branch alone
#   git-base-branch.sh worktree <path> <new-branch> [-- <git worktree args>]
#
# Exit codes: 0 ok, 1 usage, 2 not a git repo, 3 fork with no upstream remote,
# 4 default branch unresolvable.

set -uo pipefail

GIT="${GIT:-git}"
GH="${GH:-gh}"

_bb_warn() { printf 'git-base-branch: %s\n' "$*" >&2; }

_bb_git() { "$GIT" "$@"; }

# Offline mode: no `gh`, no `ls-remote`. `make verify` fronts every gate with the
# drift advisory, which sources this file, so an unbounded network call here stalls
# the gate before its first line of output (#1753).
_bb_offline() { [ "${RPW_BASE_BRANCH_OFFLINE:-}" = "1" ]; }

# Hard-bounded child. `timeout(1)` is absent on stock macOS and `gtimeout` on
# ubuntu-latest (#1088), so the bound is pure bash: run the child in the
# background writing to a temp file, poll from THIS shell, kill on expiry.
# Polling here rather than from a watcher subshell means a fast call costs its own
# runtime, not the timeout. Expiry returns 124 with no output — indistinguishable,
# to every caller, from "gh had no answer", which is the correct degradation.
_bb_bounded() {
  local secs="${RPW_BASE_BRANCH_GH_TIMEOUT:-5}"
  case "$secs" in ''|0|*[!0-9]*) secs=5 ;; esac

  local out
  out="$(mktemp "${TMPDIR:-/tmp}/rpw-base-branch.XXXXXX" 2>/dev/null)" || {
    # No temp file to capture into: run unbounded rather than lose the answer.
    "$@" 2>/dev/null
    return $?
  }

  "$@" >"$out" 2>/dev/null &
  local pid=$! ticks=0 expired=0
  local max_ticks=$((secs * 5))          # 0.2s per tick
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$ticks" -ge "$max_ticks" ]; then
      # Children FIRST, then the parent. Killing the parent first orphans whatever
      # it was waiting on — the child reparents to PID 1 and `pkill -P` can no
      # longer find it, which is exactly how a "killed" harness keeps running
      # (#644). A real `gh` has no children; a wrapper or test stub does.
      command -v pkill >/dev/null 2>&1 && pkill -P "$pid" >/dev/null 2>&1
      kill "$pid" 2>/dev/null
      expired=1
      break
    fi
    sleep 0.2
    ticks=$((ticks + 1))
  done
  wait "$pid" 2>/dev/null
  local rc=$?

  if [ "$expired" -eq 1 ]; then
    rm -f "$out"
    return 124
  fi
  cat "$out" 2>/dev/null
  rm -f "$out"
  return "$rc"
}

# `gh` is optional: without it (or without auth, or past the timeout) we fall back
# to pure-git signals.
_bb_gh_json() {
  _bb_offline && return 1
  command -v "$GH" >/dev/null 2>&1 || return 1
  _bb_bounded "$GH" repo view --json "$1" -q "$2"
}

_bb_gh_repo_default() {
  _bb_offline && return 1
  command -v "$GH" >/dev/null 2>&1 || return 1
  _bb_bounded "$GH" repo view "$1" --json defaultBranchRef -q .defaultBranchRef.name
}

_bb_have_remote() {
  _bb_git remote 2>/dev/null | grep -Fxq "$1"
}

_bb_remote_url() { _bb_git remote get-url "$1" 2>/dev/null; }

# `owner/repo` out of any GitHub remote URL (ssh, https, with or without .git).
_bb_remote_slug() {
  local url
  url="$(_bb_remote_url "$1")" || return 1
  [ -n "$url" ] || return 1
  printf '%s' "$url" \
    | sed -e 's#\.git$##' -e 's#^git@[^:]*:##' -e 's#^ssh://[^/]*/##' -e 's#^https\{0,1\}://[^/]*/##' \
    | awk -F/ 'NF>=2 { print $(NF-1) "/" $NF }'
}

# ---------------------------------------------------------------------------
# base_remote — which remote holds the true base
# ---------------------------------------------------------------------------
#
# A fork is detected from `gh` (`isFork`) or, offline, from an `upstream` remote
# whose URL differs from `origin`'s. When it IS a fork we require a remote
# pointing at the parent and refuse to fall back to `origin`: branching off the
# fork's default is the exact drift this helper exists to stop.
base_remote() {
  _bb_git rev-parse --git-dir >/dev/null 2>&1 || {
    _bb_warn "not a git repository"
    return 2
  }

  local is_fork parent upstream_url origin_url
  is_fork="$(_bb_gh_json isFork .isFork || true)"
  parent="$(_bb_gh_json parent '.parent | if . == null then "" else .owner.login + "/" + .name end' || true)"

  upstream_url="$(_bb_remote_url upstream)"
  origin_url="$(_bb_remote_url origin)"

  if [ "$is_fork" != "true" ] && [ -z "$parent" ]; then
    # No fork signal from gh. Offline heuristic: a distinct `upstream` remote.
    if [ -n "$upstream_url" ] && [ "$upstream_url" != "$origin_url" ]; then
      printf 'upstream\n'
      return 0
    fi
    if [ -z "$origin_url" ]; then
      _bb_warn "no 'origin' remote configured"
      return 3
    fi
    printf 'origin\n'
    return 0
  fi

  # It IS a fork. Find a remote pointing at the parent; prefer `upstream`.
  if [ -n "$upstream_url" ] && [ "$upstream_url" != "$origin_url" ]; then
    printf 'upstream\n'
    return 0
  fi

  local remote url
  while IFS= read -r remote; do
    [ -n "$remote" ] || continue
    [ "$remote" = "origin" ] && continue
    url="$(_bb_remote_url "$remote")"
    [ -n "$url" ] && [ "$url" != "$origin_url" ] || continue
    if [ -z "$parent" ] || printf '%s' "$url" | grep -Fqi -- "$parent"; then
      printf '%s\n' "$remote"
      return 0
    fi
  done < <(_bb_git remote 2>/dev/null)

  _bb_warn "this repo is a fork${parent:+ of $parent} but has no 'upstream' remote."
  _bb_warn "branching off the fork's default branch produces drift — add the parent first:"
  _bb_warn "  git remote add upstream https://github.com/${parent:-<parent-owner>/<parent-repo>}.git"
  return 3
}

# ---------------------------------------------------------------------------
# base_default_branch <remote> — that remote's default branch, never hardcoded
# ---------------------------------------------------------------------------
#
# Order: `gh` for the parent/own repo (authoritative, no local state), then the
# cached `refs/remotes/<remote>/HEAD` symref, then `git ls-remote --symref`.
base_default_branch() {
  local remote="${1:-}"
  [ -n "$remote" ] || { _bb_warn "base_default_branch needs a remote"; return 1; }

  # Ask GitHub about the repo THIS remote points at — not whichever repo `gh`
  # happens to resolve from the ambient checkout.
  local branch="" slug
  slug="$(_bb_remote_slug "$remote" || true)"
  if [ -n "$slug" ]; then
    branch="$(_bb_gh_repo_default "$slug" || true)"
  fi

  if [ -z "$branch" ] || [ "$branch" = "null" ]; then
    branch="$(_bb_git symbolic-ref --short "refs/remotes/$remote/HEAD" 2>/dev/null | sed "s#^$remote/##")"
  fi

  # `ls-remote` is a network call too — an offline caller must not reach it.
  if [ -z "$branch" ] && ! _bb_offline; then
    branch="$(_bb_git ls-remote --symref "$remote" HEAD 2>/dev/null \
      | awk '$1 == "ref:" { sub("refs/heads/", "", $2); print $2; exit }')"
  fi

  if [ -z "$branch" ] || [ "$branch" = "null" ]; then
    _bb_warn "could not resolve the default branch of '$remote'."
    _bb_warn "  set it with: git remote set-head $remote --auto"
    return 4
  fi

  printf '%s\n' "$branch"
}

# ---------------------------------------------------------------------------
# base_ref [--no-fetch] — the fetched `<remote>/<branch>` to branch from
# ---------------------------------------------------------------------------
base_ref() {
  local fetch=1
  [ "${1:-}" = "--no-fetch" ] && fetch=0

  local remote branch rc
  remote="$(base_remote)" || return $?
  branch="$(base_default_branch "$remote")" || return $?

  if [ "$fetch" -eq 1 ]; then
    if ! _bb_git fetch "$remote" "$branch"; then
      rc=$?
      _bb_warn "git fetch $remote $branch failed — refusing to branch off a possibly-stale ref"
      return "$rc"
    fi
  fi

  printf '%s/%s\n' "$remote" "$branch"
}

# ---------------------------------------------------------------------------
# base_worktree_add <path> <new-branch> [extra git args...]
# ---------------------------------------------------------------------------
# Branch + worktree in ONE step off the freshly-fetched base. Creating the
# branch separately lets the worktree tool mint its own `worktree-*` name and
# the PR lands on the wrong branch (#307).
base_worktree_add() {
  local path="${1:-}" branch="${2:-}"
  [ -n "$path" ] && [ -n "$branch" ] || {
    _bb_warn "usage: base_worktree_add <path> <new-branch> [git worktree args...]"
    return 1
  }
  shift 2

  local ref
  ref="$(base_ref)" || return $?
  _bb_git worktree add "$@" "$path" -b "$branch" "$ref"
}

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_bb_usage() {
  cat >&2 <<'USAGE'
usage: git-base-branch.sh <command> [args]

  ref [--no-fetch]                      fetch, then print `<remote>/<branch>`
  remote                                print the remote to branch from
  branch [<remote>]                     print that remote's default branch
  worktree <path> <new-branch> [args]   fetch + `git worktree add` off the base
USAGE
  return 1
}

# Only run the CLI when executed, not when sourced.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    ref)      shift; base_ref "$@" ;;
    remote)   shift; base_remote "$@" ;;
    branch)
      shift
      if [ -n "${1:-}" ]; then
        base_default_branch "$1"
      else
        _r="$(base_remote)" || exit $?
        base_default_branch "$_r"
      fi
      ;;
    worktree) shift; base_worktree_add "$@" ;;
    *)        _bb_usage ;;
  esac
fi
