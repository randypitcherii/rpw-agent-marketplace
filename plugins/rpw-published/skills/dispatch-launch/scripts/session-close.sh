#!/usr/bin/env bash
# Close any session you own, including ones outside your spawn tree (#2030).
#
#   session-close.sh [--force] <session-id>
#
# `sys_session_close` only closes a session in the caller's spawn tree, so it
# returns `session_out_of_tree` for anything created over REST — which is every
# path-A session, including the wave-kickoff write probe. The omni CLI (0.16)
# has no close command either. This sends the same PATCH `sys_session_close`
# sends: the `omnigent.closed` label plus `archived: true`, which also triggers
# the server's reaper for the session's harness / tmux / bridge processes.
#
# Archiving DELETES the session's bound worktree by default (#2571, #2580): Omnigent's
# archive cleanup runs `git worktree remove --force` — no dirty check, branch kept, failed
# sessions included. So before archiving, the bound workspace is guarded: a linked
# worktree on this host is refused while it holds uncommitted/untracked changes or
# the gitignored wave records (WAVE-BRIEF.md, WAVE-STATE.md, WORKER-BRIEF.md, a
# non-empty .wave/). `--force` accepts the loss. Commits are not checked: the
# removal keeps the branch, so they survive it (wave-close-children is stricter).
# Not guarded: an already-archived session, no workspace, a path not on this host,
# a non-git directory, the main checkout (the server never removes it).
#
# Exit codes: 0 closed and read back archived · 2 usage (incl. SID=self) · 3 auth · 4 API error
#             5 the server answered 2xx but the session is not archived
#             6 refused: the bound worktree holds work an archive would delete
set -euo pipefail

usage() { echo "usage: session-close.sh [--force] <session-id>" >&2; exit 2; }
FORCE=0
[[ "${1:-}" == "--force" ]] && { FORCE=1; shift; }
[[ $# -eq 1 && -n "$1" && "$1" != -* ]] || usage
SID="$1"
# `self` is refused, never resolved (#2542): closing the session running this
# ends your turn mid-command and can archive the worktree it is bound to. To
# self-terminate, follow session-lifecycle.md and pass your id explicitly.
[[ "$SID" != "self" ]] || {
  echo "session-close: SID=self is refused — closing your own session ends your turn and can archive its bound worktree; pass the explicit id if you really mean it (session-lifecycle.md, self-termination)" >&2
  exit 2
}

# shellcheck source=SCRIPTDIR/omni-api.sh
source "$(dirname "${BASH_SOURCE[0]}")/omni-api.sh"

field() { python3 -c 'import json,sys; v=json.load(sys.stdin).get(sys.argv[1]); print("" if v is None else str(v).lower() if isinstance(v,bool) else v)' "$1"; }

# Prints why the worktree is unsafe to lose (one line), or nothing when it is safe.
worktree_risk() {
  local ws="$1" top gitdir common dirty
  [[ -d "$ws" ]] || return 0
  command -v git >/dev/null || { echo "git is not available to read $ws — unprovable"; return 0; }
  top="$(git -C "$ws" rev-parse --show-toplevel 2>/dev/null)" || return 0   # not git
  gitdir="$(cd "$ws" && cd "$(git rev-parse --git-dir)" && pwd -P)" || { echo "cannot read git state in $ws"; return 0; }
  common="$(cd "$ws" && cd "$(git rev-parse --git-common-dir)" && pwd -P)" || { echo "cannot read git state in $ws"; return 0; }
  [[ "$gitdir" != "$common" ]] || return 0      # main checkout: the server never removes it
  dirty="$(git -C "$top" status --porcelain 2>/dev/null)" || { echo "\`git status\` failed in $top — unprovable"; return 0; }
  if [[ -n "$dirty" ]]; then
    echo "$top has $(printf '%s\n' "$dirty" | wc -l | tr -d ' ') uncommitted path(s) (e.g. $(printf '%s\n' "$dirty" | head -1 | cut -c4-))"
    return 0
  fi
  local rec
  for rec in WAVE-BRIEF.md WAVE-STATE.md WORKER-BRIEF.md; do
    [[ -e "$top/$rec" ]] && { echo "$top holds $rec (gitignored, so no remote has it)"; return 0; }
  done
  if [[ -d "$top/.wave" && -n "$(ls -A "$top/.wave" 2>/dev/null)" ]]; then
    echo "$top holds .wave/ logs (gitignored, so no remote has them)"
  fi
  return 0
}

out="$(api GET "/v1/sessions/$SID")"
code="${out##*$'\n'}"; resp="${out%$'\n'*}"
[[ "$code" == 2* ]] || die "GET /v1/sessions/$SID -> HTTP $code: $resp" 4
workspace="$(printf '%s' "$resp" | field workspace)"
if [[ "$(printf '%s' "$resp" | field archived)" != "true" && -n "$workspace" ]]; then
  risk="$(worktree_risk "$workspace")"
  if [[ -n "$risk" ]]; then
    if [[ "$FORCE" != 1 ]]; then
      echo "session-close: REFUSED — archiving $SID may delete its bound worktree with \`git worktree remove --force\`, and $risk. Commit and push (or move) that work first, or re-run with --force (make session-close SID=$SID FORCE=1) to accept losing it (#2571)." >&2
      exit 6
    fi
    echo "session-close: --force: archiving despite the guard — $risk" >&2
  fi
fi

out="$(api PATCH "/v1/sessions/$SID" '{"labels":{"omnigent.closed":"true"},"archived":true}')"
code="${out##*$'\n'}"; resp="${out%$'\n'*}"
[[ "$code" == 2* ]] || die "PATCH /v1/sessions/$SID -> HTTP $code: $resp" 4

# Read back: a 2xx that did not archive must not pass for a close.
out="$(api GET "/v1/sessions/$SID")"
code="${out##*$'\n'}"; resp="${out%$'\n'*}"
[[ "$code" == 2* ]] || die "GET /v1/sessions/$SID -> HTTP $code: $resp" 4
archived="$(printf '%s' "$resp" | field archived)"
[[ "$archived" == "true" ]] || die "session $SID answered 2xx but is not archived" 5
printf 'closed %s (archived, omnigent.closed=true)\n' "$SID"
[[ -z "$workspace" ]] || printf 'note: the server may delete its bound worktree %s (branch kept) — never relaunch onto that path without re-creating it\n' "$workspace"
