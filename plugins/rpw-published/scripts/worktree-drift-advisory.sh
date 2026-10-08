#!/usr/bin/env bash
# Stale-worktree drift advisory (#1661, option A).
#
# `make base-worktree` makes a worktree correct AT CREATION (#1164). A long-lived
# one then ages: it runs a gate that predates fixes already merged upstream, and a
# red result you did not cause is indistinguishable from one you did. #1661's
# evidence: a worktree cut before #1637-#1640 reported 12 TestCiWorkflows::*
# failures that were already fixed on `production`, and that read as a
# pre-existing bug in the PR body.
#
# `make verify` calls this FIRST, before any test output, so the drift is named as
# a candidate cause before a failure gets interpreted.
#
# Contract:
#   - ADVISORY ONLY. Always exits 0, whatever happens. It must never turn a gate red.
#   - Never network-dependent in a way that can fail the gate: EVERY network call it
#     can reach is bounded (the fetch here, the `gh repo view` pair in
#     git-base-branch.sh), and a failed, expired or absent call falls back to local
#     refs. If nothing resolves (offline, no remote, not a git repo), it prints
#     nothing.
#   - Cheap enough to front every gate run: the base-branch answer is cached per
#     worktree, so the second and later runs make no network call at all (#1753).
#   - A current checkout prints nothing at all.
#
# Usage: worktree-drift-advisory.sh [--no-fetch]
#
# Env:
#   RPW_WORKTREE_DRIFT_COMMITS        commits-behind threshold (default 10)
#   RPW_WORKTREE_DRIFT_DAYS           base-tip age threshold in days (default 2)
#   RPW_WORKTREE_DRIFT_FETCH_TIMEOUT  seconds the bounded fetch may take (default 10)
#   RPW_WORKTREE_DRIFT_NO_FETCH=1     FULLY OFFLINE — the one switch that makes this
#                                     script touch the network zero times: it skips
#                                     the fetch AND the `gh repo view` pair and
#                                     `ls-remote` fallback in git-base-branch.sh
#                                     (via RPW_BASE_BRANCH_OFFLINE=1). `--no-fetch`
#                                     is equivalent.
#   RPW_WORKTREE_DRIFT_CACHE_TTL      seconds a cached base answer stays fresh
#                                     (default 86400)
#   RPW_WORKTREE_DRIFT_NO_CACHE=1     neither read nor write the cache
#   RPW_BASE_BRANCH_GH_TIMEOUT        seconds one `gh repo view` may take (default 5,
#                                     enforced in git-base-branch.sh)
#   GIT / GH                          injectable, as in git-base-branch.sh

set -uo pipefail

_da_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT="${GIT:-git}"

_da_git() { "$GIT" "$@"; }

# Bounded fetch: macOS has no `timeout`, and an offline fetch can hang for minutes.
# Never fail the advisory on it — the cached remote-tracking ref is the fallback.
_da_bounded_fetch() {
  local remote="$1" branch="$2" secs="${RPW_WORKTREE_DRIFT_FETCH_TIMEOUT:-10}"
  case "$secs" in ''|*[!0-9]*) secs=10 ;; esac

  # Bounded by polling from THIS shell, not by a watcher subshell: a watcher that
  # is killed while inside `sleep` keeps `wait` blocked for the full timeout, so a
  # local fetch that finishes in 50ms would still cost `secs`. The fetch process is
  # the only one spawned, and it is always reaped here.
  _da_git fetch --no-tags --quiet "$remote" "$branch" 2>/dev/null &
  local pid=$!
  local ticks=0 max_ticks=$((secs * 5))   # 0.2s per tick
  while kill -0 "$pid" 2>/dev/null; do
    [ "$ticks" -ge "$max_ticks" ] && { kill "$pid" 2>/dev/null; break; }
    sleep 0.2
    ticks=$((ticks + 1))
  done
  wait "$pid" 2>/dev/null
  return $?
}

_da_is_uint() { case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }

# ---------------------------------------------------------------------------
# Base-branch cache (#1753)
# ---------------------------------------------------------------------------
#
# Which remote and default branch this worktree is based on does not change while
# the worktree lives, but resolving it costs two-to-three `gh repo view` round
# trips — measured at ~1.3s on the front of EVERY gate run, before a single line
# of test output. So resolve once and remember.
#
# It lives in the worktree's own git dir (`--git-dir` is per-worktree for a linked
# worktree), so it is never tracked, never shared with a sibling worktree, and is
# deleted with the worktree. Three bounds keep a stale entry from ever being worse
# than no entry at all:
#   1. a TTL, so a renamed default branch self-heals;
#   2. a fingerprint of the remote set, so adding an `upstream` invalidates it;
#   3. the value is only ever used for an advisory, and the caller still verifies
#      the ref exists before printing anything.
_da_cache_file() {
  local gitdir
  gitdir="$(_da_git rev-parse --git-dir 2>/dev/null)" || return 1
  [ -n "$gitdir" ] || return 1
  [ -d "$gitdir" ] || return 1
  printf '%s/rpw-drift-base.cache\n' "$gitdir"
}

_da_cache_fingerprint() {
  local fp
  fp="$(_da_git remote -v 2>/dev/null | cksum 2>/dev/null | tr -cd '0-9')"
  printf '%s\n' "${fp:-none}"
}

# Prints "<remote>\t<branch>" on a fresh, matching hit; nonzero on any miss.
_da_cache_read() {
  [ "${RPW_WORKTREE_DRIFT_NO_CACHE:-}" = "1" ] && return 1

  local file
  file="$(_da_cache_file)" || return 1
  [ -f "$file" ] || return 1

  local ttl="${RPW_WORKTREE_DRIFT_CACHE_TTL:-86400}"
  _da_is_uint "$ttl" || ttl=86400

  local stamp fp remote branch now
  IFS=$'\t' read -r stamp fp remote branch < "$file" || return 1
  _da_is_uint "$stamp" || return 1
  [ -n "$remote" ] && [ -n "$branch" ] || return 1
  [ "$fp" = "$(_da_cache_fingerprint)" ] || return 1

  # Timestamp stored in the file, not read off the inode: `stat` flags differ
  # between macOS and GNU (#1088).
  now="$(date +%s 2>/dev/null)"
  _da_is_uint "$now" || return 1
  [ "$now" -ge "$stamp" ] || return 1
  [ "$((now - stamp))" -lt "$ttl" ] || return 1

  printf '%s\t%s\n' "$remote" "$branch"
}

_da_cache_write() {
  [ "${RPW_WORKTREE_DRIFT_NO_CACHE:-}" = "1" ] && return 0

  local file now
  file="$(_da_cache_file)" || return 0
  now="$(date +%s 2>/dev/null)"
  _da_is_uint "$now" || return 0
  printf '%s\t%s\t%s\t%s\n' "$now" "$(_da_cache_fingerprint)" "$1" "$2" \
    >"$file" 2>/dev/null || true
  return 0
}

_advisory() {
  local do_fetch=1 offline=0
  [ "${1:-}" = "--no-fetch" ] && do_fetch=0
  [ "${RPW_WORKTREE_DRIFT_NO_FETCH:-}" = "1" ] && do_fetch=0
  [ "$do_fetch" -eq 0 ] && offline=1

  _da_git rev-parse --git-dir >/dev/null 2>&1 || return 0

  local remote="" branch="" cached
  if cached="$(_da_cache_read)"; then
    IFS=$'\t' read -r remote branch <<<"$cached"
  fi

  if [ -z "$remote" ] || [ -z "$branch" ]; then
    # One switch, both halves of the network cost: the `gh repo view` pair inside
    # git-base-branch.sh was the other unbounded call fronting every gate (#1753),
    # so "no fetch" has to reach it too.
    [ "$offline" -eq 1 ] && export RPW_BASE_BRANCH_OFFLINE=1

    # Reuse the one base-branch resolution: fork-aware, no hardcoded branch names.
    # shellcheck source=/dev/null
    . "$_da_script_dir/git-base-branch.sh" 2>/dev/null || return 0

    remote="$(base_remote 2>/dev/null)" || return 0
    branch="$(base_default_branch "$remote" 2>/dev/null)" || return 0
    [ -n "$remote" ] && [ -n "$branch" ] || return 0

    # Only cache an answer that could consult GitHub. An offline resolution comes
    # from local refs that may themselves be stale, and caching it would spread
    # that staleness to the next online run.
    [ "$offline" -eq 0 ] && _da_cache_write "$remote" "$branch"
  fi

  local base="$remote/$branch"
  [ "$do_fetch" -eq 1 ] && _da_bounded_fetch "$remote" "$branch"

  _da_git rev-parse --verify --quiet "$base" >/dev/null 2>&1 || return 0
  _da_git merge-base HEAD "$base" >/dev/null 2>&1 || return 0

  local behind
  behind="$(_da_git rev-list --count "HEAD..$base" 2>/dev/null)" || return 0
  _da_is_uint "$behind" || return 0
  [ "$behind" -gt 0 ] || return 0

  local threshold="${RPW_WORKTREE_DRIFT_COMMITS:-10}"
  local days="${RPW_WORKTREE_DRIFT_DAYS:-2}"
  _da_is_uint "$threshold" || threshold=10
  _da_is_uint "$days" || days=2

  local head_ts base_ts age_days=0
  head_ts="$(_da_git log -1 --format=%ct HEAD 2>/dev/null)" || head_ts=""
  base_ts="$(_da_git log -1 --format=%ct "$base" 2>/dev/null)" || base_ts=""
  if _da_is_uint "$head_ts" && _da_is_uint "$base_ts" && [ "$base_ts" -gt "$head_ts" ]; then
    age_days=$(( (base_ts - head_ts) / 86400 ))
  fi

  # A small, recent drift is normal and must not add noise. Only a drift big enough
  # to plausibly explain a red gate earns a banner.
  if [ "$behind" -lt "$threshold" ] && [ "$age_days" -lt "$days" ]; then
    return 0
  fi

  printf '\n'
  printf '%s\n' \
    '⚠️  WORKTREE DRIFT (advisory only, not a gate failure) — #1661' \
    "    This checkout is $behind commit(s) behind $base." \
    '    A red gate here may be a STALE COPY of the gate, already fixed upstream' \
    '    — stashing your diff cannot tell the two apart (#1661). Before diagnosing' \
    '    a failure you did not expect, rebase:' \
    "        git fetch $remote $branch && git rebase $base"
  printf '\n'
  return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  _advisory "${1:-}"
  exit 0
fi
