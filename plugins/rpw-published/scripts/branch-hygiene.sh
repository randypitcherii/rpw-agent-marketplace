#!/usr/bin/env bash
# Branch/worktree hygiene sweep — repo-level, dry-run by default (GitHub Issue #1231).
#
# The problem this exists for: nothing in the repo ever reconciles refs across
# ALL worktrees. `/session-cleanup` is well-built but reasons about the CURRENT
# worktree only, so the other N are never visited — the observed state was 121
# local branches (74 with a `[gone]` upstream) and 26 worktrees (14 on a branch
# already merged and remote-deleted). Three mechanical failures, none of them an
# agent being sloppy, produce that drift:
#
#   1. `gh pr merge --squash --delete-branch` ALWAYS fails its local half from a
#      worktree ("'production' is already used by worktree at ..."), because gh
#      checks out the base to delete the local ref. Worktree development is the
#      house standard, so the local branch survives every single merge.
#   2. `ExitWorktree` no-ops on worktrees it did not create, so the agent that
#      finishes the work is exactly the agent that cannot tear it down.
#   3. Squash-merge rewrites the SHA, so `git branch -d` refuses forever. Safe
#      cleanup needs `-D`, which correctly requires a proof.
#
# The squash-safe proof used here needs no reachability check at all, which is
# what lets a cheap sweep exist without weakening /session-cleanup's per-file
# equivalence proof for ambiguous cases:
#
#     upstream is `[gone]`  AND  exactly one PR for the branch, state MERGED
#     AND that PR has a NON-EMPTY headRefOid equal to the branch tip
#     AND (any worktree) unlocked, `git status` SUCCEEDS and reports clean
#     AND that worktree holds NO ignored content (`.env`, `.venv`, `uv.lock`)
#     AND no live process's argv names the worktree path
#     AND no OPEN issue it references is actively claimed
#
# Every clause is a REFUSAL when it does not hold, and the reason is printed.
# `[gone]` alone is not enough: it says the remote ref vanished, not that the
# work landed (a remote branch deleted by hand looks identical). The tip-vs-
# headRefOid comparison is how unpushed commits are caught — with the upstream
# gone, `@{u}` is unusable, so the PR's recorded head is the only honest record
# of what was actually pushed.
#
# EVERY clause FAILS CLOSED. That is a load-bearing distinction from "fails to
# find a problem", and three specific ways to accidentally fail open are guarded
# by name because each one silently authorizes `git branch -D`:
#
#   - an EMPTY or unparseable `headRefOid` is a refusal, never a pass. A missing
#     field means gh told us nothing about what was pushed, which is the exact
#     opposite of proof that the tip is contained in the merge.
#   - a FAILING `git status` is a refusal, never "clean". Piping status into
#     `grep -c .` turns a permission error, a corrupt index, or a vanished
#     worktree into a count of zero — the very answer that means "safe".
#   - an UNREADABLE process table is a refusal, never "no processes". Absence of
#     evidence is not evidence of absence when the mutation is irreversible. Two
#     readers are tried — `pgrep -f -l` first, then `ps` — because `/bin/ps` is
#     DENIED in the sandbox agent sessions run inside, and a single-reader sweep
#     refused every candidate there on a box where `pgrep` answers fine (#1850).
#   - IGNORED content is a refusal, and it needs its OWN scan: `git status
#     --porcelain` does not report it and `git worktree remove` does not stop
#     for it, so a worktree holding `.env` with a live secret reports clean and
#     is then deleted, secret and all. Ignored is not a synonym for regenerable
#     — `.env` holds secrets, and a local `uv.lock` is gitignored precisely
#     because it is environment-specific — so there is no allowlist of "safe"
#     ignored patterns. Any ignored entry refuses; count and paths are reported,
#     file content never is.
#   - a FAILED claim lookup is a refusal, never "no claim". A gh call that dies on
#     a rate limit or an expired token used to be indistinguishable from an issue
#     with no claim label, in the one clause whose job is knowing whether a human
#     is still working in the tree. Only "no such issue" is a real answer here.
#   - only an ISSUE-SPECIFIC not-found is "no such issue". `could not resolve` and
#     `not found` also describe an unresolvable repository, a bad node id, an HTTP
#     404 and an unauthenticated call — visibility failures, where the issue may
#     exist and hold a live claim. Matching them as "issue absent" skipped the ref,
#     and a skipped ref is a claim never found. The match now needs gh's Issue
#     phrasing AND the number that was queried; everything else refuses.
#   - a branch name encodes AT MOST ONE issue number, by convention (the leading or
#     trailing digit run of its last path segment, ISO dates excluded). Scraping
#     every digit group turned `wave/2026-08-29-backlog` into the refs 2026/08/29
#     and spent three of the five capped lookups on a date, displacing the real
#     `#N` refs that could have reported a claim.
#   - a FAILING `git log` while enumerating commit refs is REF-LOOKUP-FAILED, never
#     an empty ref list. `git log ... | grep -oE '#[0-9]+'` reported the pipeline's
#     status, so a missing default branch or an unreadable object store produced no
#     refs — the same text as "this branch mentions no issues", and the claim clause
#     then had nothing to ask about.
#   - the claim-lookup CAP must never displace the branch's own issue. The cap kept
#     the five numerically smallest refs, so five older `#N` mentions in the commit
#     bodies pushed `worker/1231-*`'s own #1231 off the list — and a lookup that
#     never runs cannot report a claim. The branch's issue is queried first, always.
#
# The same "a missing answer is not a passing answer" reading applies to inputs.
# `RPW_HYGIENE_PROTECT` is split unquoted, so an entry carrying a glob
# metacharacter is expanded against the cwd — which DELETES the operator's entry
# and substitutes matching filenames, leaving the branch they named unprotected
# and some unrelated branch protected instead. Metacharacters are therefore a
# loud fatal, and the split runs under `set -f` so entries stay literal.
#
# TOCTOU: judgment and mutation are separated in time (the report prints in
# full, and a human may sit on it before running --apply), so a proof from the
# planning pass is stale by the time it would authorize a deletion. The plan
# therefore records the exact tip, PR number and PR head it proved, and
# `hygiene_prove` runs AGAIN immediately before each removal with those values
# as expectations. A commit landing after planning, a tree going dirty, a claim
# appearing, a worktree being locked, or the branch moving to another worktree
# all turn the deletion back into a refusal. Judgment and revalidation are
# literally the same function, so the two can never drift apart.
#
# Revalidation shrinks that window but cannot close it: a ref can still move
# between `hygiene_prove` returning OK and the deletion running. So the deletion
# itself is a compare-and-swap — `git update-ref -d refs/heads/<b> <proven-oid>`,
# never `git branch -D`, which would delete whatever the name happens to point at
# by then. A moved ref makes the delete fail, and a failed delete is reported.
#
# Deliberately NOT done here:
#   - no `--force` anywhere; a refusal from git is a failed safety check
#   - never the main worktree, never the invoking worktree, never the default or
#     protected branches, never a locked worktree
#   - no process *killing* (#644) — that stays with /session-cleanup, which runs
#     inside the worktree it is about and can see its own background tasks. This
#     sweep only ever REFUSES on a live process, and its evidence is argv-based:
#     a process that no longer names the path in its argv (an interactive shell
#     merely `cd`-ed into it, an inherited file descriptor, a daemon that
#     chdir-ed and re-exec'd) is invisible to it. That is a known lower bound,
#     not a guarantee of quiescence.
#
# Usage:
#   branch-hygiene.sh [--apply] [--no-fetch] [-h|--help]
#
# Dry run (the default) prints a verdict + evidence line per candidate and the
# exact apply command. Only `--apply` mutates. All gh I/O goes through ${GH:-gh}
# so the whole script is testable against a fake gh in a fixture repo.
#
# Env:
#   GH                            gh binary (tests inject a fake)
#   RPW_HYGIENE_DEFAULT_BRANCH    override default-branch detection
#   RPW_HYGIENE_PROTECT           space-separated EXACT extra branch names to
#                                 never touch. Not patterns — a glob
#                                 metacharacter is a fatal error, not a match
#                                 rule (see above for why it fails open).
#   RPW_HYGIENE_MAX_ISSUE_LOOKUPS per-branch cap on claim lookups (default 5;
#                                 unset or empty means the default). Must be a
#                                 strictly positive base-10 integer — 0, a
#                                 negative, or a non-numeric value is a fatal
#                                 usage error, because it makes the cap drop
#                                 EVERY ref and a claim that is never looked up
#                                 cannot refuse a deletion. The branch's own
#                                 issue number is always queried first, so a
#                                 valid cap only ever drops commit-body
#                                 references, never the branch's own claim.
#   RPW_HYGIENE_PGREP             pgrep binary — the PREFERRED process-table
#                                 reader (tests inject a fake)
#   RPW_HYGIENE_PS                ps binary — the fallback reader, used only when
#                                 pgrep did not answer (tests inject a fake)
#   RPW_HYGIENE_PRE_APPLY_HOOK    test seam: an executable INVOKED (not eval'd)
#                                 once after planning and before the first
#                                 mutation, so a test can mutate the repo in the
#                                 TOCTOU window and prove revalidation refuses.
#                                 Not for humans.
#   RPW_HYGIENE_PRE_DELETE_HOOK   test seam: a command invoked (not eval'd) with
#                                 the branch name, after that branch's final
#                                 proof and before its delete, so a test can move
#                                 the ref in the last window. Not for humans.
#
# Log prefix: 'branch-hygiene:'
# bash-3.2 safe (no associative arrays) — macOS ships /bin/bash 3.2.

set -uo pipefail

APPLY=0
FETCH=1
PROTECT_DEFAULT="production main master"
MAX_ISSUE_LOOKUPS="${RPW_HYGIENE_MAX_ISSUE_LOOKUPS:-5}"
TAB="$(printf '\t')"

# Counters, filled by the sweep and read by the summary.
N_REAP=0
N_REFUSE=0
N_SKIP=0
N_FAIL=0

_gh() { "${GH:-gh}" "$@"; }

log() { echo "branch-hygiene: $*"; }
err() { echo "branch-hygiene: $*" >&2; }

usage() {
  # The header block is delimited, not line-numbered: every comment line after the
  # shebang, ending at the first line that is not a comment. The old form was a
  # hardcoded `sed -n '2,Np'`, and a hardcoded range is wrong the moment the header
  # changes length in either direction — too small silently TRUNCATES the help
  # (the range once ended mid-Env-block, so the documented behavior of half this
  # script's environment variables simply did not print), too large leaks code into
  # it. Nothing here needs updating when the header grows.
  awk '
    NR == 1  { next }                       # shebang
    /^#/     { sub(/^# ?/, ""); print; next }
             { exit }                       # first non-comment line ends the header
  ' "${BASH_SOURCE[0]}"
}

# ---------------------------------------------------------------------------
# Repo facts
# ---------------------------------------------------------------------------

# hygiene_default_branch — the integration branch, never hardcoded (#1164 spirit).
# Resolution order: explicit override, origin/HEAD's symbolic ref, then the main
# worktree's checked-out branch. A wrong answer here would offer the integration
# branch itself as a reap candidate, so an unresolvable default is fatal.
hygiene_default_branch() {
  if [ -n "${RPW_HYGIENE_DEFAULT_BRANCH:-}" ]; then
    echo "$RPW_HYGIENE_DEFAULT_BRANCH"
    return 0
  fi
  local ref
  ref="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || echo "")"
  if [ -n "$ref" ]; then
    echo "${ref#origin/}"
    return 0
  fi
  local main_wt fallback
  main_wt="$(hygiene_main_worktree)"
  fallback="$(git -C "$main_wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  # A detached main worktree answers the literal string "HEAD", which is not a
  # branch name — treat it as unresolved rather than sweeping against a fiction.
  [ "$fallback" = "HEAD" ] && fallback=""
  echo "$fallback"
}

# hygiene_main_worktree — first entry of `git worktree list --porcelain`, which
# git guarantees is the main clone. It is never a removal candidate.
hygiene_main_worktree() {
  git worktree list --porcelain 2>/dev/null | awk '/^worktree /{print substr($0,10); exit}'
}

# hygiene_worktree_for <branch> — path of the worktree that has <branch> checked
# out, or empty. Emitted as "path<TAB>locked" (locked = 1 when git marks it so).
#
# The whole record is buffered before matching, deliberately: git emits `locked`
# AFTER `branch` within a record, so deciding on the `branch` line would report
# every locked worktree as unlocked — and an unlocked verdict is what turns a
# refusal into a deletion.
hygiene_worktree_for() {
  local want="$1"
  git worktree list --porcelain 2>/dev/null | awk -v want="refs/heads/$want" '
    function flush() {
      if (path != "" && branch == want) { print path "\t" locked; found = 1 }
    }
    /^worktree /{ flush(); if (found) exit; path = substr($0, 10); branch = ""; locked = 0; next }
    /^locked/   { locked = 1; next }
    /^branch /  { branch = substr($0, 8); next }
    END         { if (!found) flush() }
  '
}

# ---------------------------------------------------------------------------
# GitHub proofs (all via _gh, all bounded)
# ---------------------------------------------------------------------------

# hygiene_pr_rows <branch> — one "number<TAB>state<TAB>headRefOid" row per PR
# whose head is <branch>, across ALL states. Every state is requested on purpose:
# zero rows and an OPEN/CLOSED row are different refusals, and more than one row
# is the ambiguous case that must never be guessed at.
hygiene_pr_rows() {
  _gh pr list --head "$1" --state all \
    --json number,state,headRefOid \
    --jq '.[] | [.number, .state, .headRefOid] | @tsv' 2>/dev/null
}

# hygiene_branch_issue <branch> — the ONE issue number a branch name asserts
# ownership of, under a narrow convention, or nothing.
#
# The convention is the repo's own branch spelling: the issue number is the
# leading or trailing digit run of the branch's LAST path segment —
# `worker/1231-hygiene-x` -> 1231, `feature/wt-108` -> 108. At least two digits,
# and at most one number per branch.
#
# It used to be `grep -oE '[0-9]{2,}'` over the whole name, i.e. EVERY digit group
# anywhere in it. That is not a convention, it is a scrape, and it fails open by
# spending the claim-lookup cap on numbers that were never issues: a supervisor
# branch named `wave/2026-08-29-backlog` yields 2026, 08 and 29, which is three of
# the five available lookups burned on a date. Under a tight cap those junk refs
# displace a real `#N` from the commit bodies, and a ref that is never queried
# cannot report a claim — the same fail-open shape the cap-priority fix closed,
# arriving through the extractor instead of the sort.
#
# A leading date is therefore rejected explicitly rather than merely deprioritized:
# `2026-08-29-backlog` leads with digits, so a leading-run rule alone would read
# the year as an issue number.
hygiene_branch_issue() {
  local leaf="${1##*/}"
  case "$leaf" in
    # ISO date leaf (`wave/2026-08-29-...`): a date, never an issue.
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*) return 0 ;;
  esac
  case "$leaf" in
    # Leading run wins — `worker/1231-slug` is the primary house spelling.
    [0-9][0-9]*) printf '%s\n' "${leaf%%[!0-9]*}"; return 0 ;;
  esac
  # Trailing run, e.g. `feature/some-slug-108`. Two digits minimum, and only when
  # the leaf actually ENDS in digits — `fix-100-wip` encodes no issue number.
  local trail="${leaf##*[!0-9]}"
  case "$trail" in
    ?? | ???*) printf '%s\n' "$trail" ;;
  esac
  return 0
}

# hygiene_issue_refs <branch> <default> — issue numbers this branch plausibly
# owns: the one number its name encodes (see hygiene_branch_issue) plus `#N` in
# the messages of its own commits. Bounded by MAX_ISSUE_LOOKUPS so a long-lived
# branch cannot turn the sweep into a hundred gh calls.
#
# A FAILING `git log` emits the REF-LOOKUP-FAILED sentinel instead of an empty
# list. Collecting commit refs through `git log ... 2>/dev/null | grep -oE ...`
# discarded the exit status entirely, so a broken or missing default branch, an
# unreadable object store, or a ref that vanished mid-run produced no output —
# textually identical to "this branch mentions no issues", which is the answer
# that lets the claim clause pass. Same reading as status-failed and PS-FAILED:
# the list of things to ask about is itself evidence, and failing to build it is
# not the same as building an empty one.
#
# PRIORITY IS THE POINT, and it used to be absent. The old form merged both
# sources and ran the whole set through `sort -un | head -n 5`, i.e. it kept the
# five NUMERICALLY SMALLEST refs. The branch's own issue — the one whose claim is
# most likely to be live, and the only one the branch name asserts ownership of —
# is typically the newest and therefore the LARGEST number, so five references to
# older issues in the commit bodies pushed it off the end of the list. It was then
# never looked up, and a lookup that never happens cannot report a claim: the cap
# meant to bound cost was silently authorizing deletion of a claimed branch.
#
# So the branch-encoded number is emitted FIRST and unconditionally, and commit
# refs only fill whatever slots remain under the cap. Deduplication is
# order-preserving (awk, not `sort -u`) for the same reason.
hygiene_issue_refs() {
  local branch="$1" default="$2" log_out log_rc
  # Captured and status-checked SEPARATELY, then piped — never `git log | grep`,
  # whose exit status is grep's and whose empty output means both "no refs" and
  # "the enumeration failed".
  log_out="$(git log --format='%s%n%b' "$default..$branch" 2>/dev/null)"
  log_rc=$?
  if [ "$log_rc" -ne 0 ]; then
    echo "REF-LOOKUP-FAILED branch=$branch rc=$log_rc"
    return 0
  fi
  {
    # The branch's own issue first — never displaced by the cap.
    hygiene_branch_issue "$branch"
    printf '%s\n' "$log_out" | grep -oE '#[0-9]{2,}' | tr -d '#' || true
  } | awk 'NF && !seen[$0]++' | head -n "$MAX_ISSUE_LOOKUPS"
}

# hygiene_issue_absent <n> <stderr_file> — true only for "issue #<n> does not
# exist", the ONE gh failure that is a complete answer rather than a missing one.
#
# The old test was `grep -qiE 'could not resolve|not found|no such issue'`, three
# substrings so generic that most of gh's real failures satisfy them while saying
# nothing at all about issue <n>:
#
#   Could not resolve to a Repository with the name 'owner/repo'.   <- wrong repo
#   Could not resolve to a node with the global id of '...'         <- bad node id
#   gh: Not Found (HTTP 404)                                        <- REST 404
#   HTTP 401: Bad credentials / Not Found (auth-shaped visibility)  <- no token
#
# Every one of those is a VISIBILITY or CONFIGURATION failure — the issue may well
# exist and carry a live claim; we simply were not allowed to see it, or asked the
# wrong place. Reading them as "issue absent" made the loop `continue`, and a ref
# that is skipped is a claim that is never found: the branch reached `update-ref -d`
# with its worker still in the tree. A repo the sweep cannot resolve is the WORST
# case to fail open on, because it fails that way for every ref at once.
#
# So the match requires both halves of the real message: gh's issue-specific
# "could not resolve to an Issue" phrasing AND the number we actually queried, with
# no other digits between them. Anything else — including a 404 that never names an
# issue — falls through to the caller's LOOKUP-FAILED, which refuses.
hygiene_issue_absent() {
  local n="$1" errf="$2"
  grep -qiE "could not resolve to an issue[^0-9]*${n}([^0-9]|\$)" "$errf"
}

# hygiene_active_claim <branch> <default> — echo the blocking claim, or nothing.
#
# "Active" is deliberately the CONSERVATIVE reading: an OPEN issue carrying
# `status: in-progress` or `wave: owned` blocks, even though a merged branch's
# own claim label often lingers until wave close-out. The asymmetry is the point
# — a lingering label costs one branch left behind until the supervisor closes
# the issue, while reaping under a live claim destroys a worker's in-flight
# workspace. CLOSED issues never block: a closed issue is nobody's live work.
#
# EXACT-STRING COUPLING (deliberate, and pinned by a test). Both literals below
# are owned elsewhere, and neither owner can be sourced from bash without side
# effects — one is a Python module, the other a script whose top level parses
# arguments and calls gh:
#
#   "status: in-progress"  <- plugins/rpw-published/scripts/build-claim.sh
#                             (CLAIM_LABEL), the worker claim sentinel
#   "wave: owned"          <- scripts/wave_owner.py (OWNER_LABEL), the
#                             supervisor lease label
#
# So they are duplicated here as literals, and `tests/test_branch_hygiene.py`
# asserts each canonical owner still spells its label exactly this way. That test
# is the failure mode's only backstop: a rename at the owner would otherwise make
# the `case` arm below match nothing, and a claim guard that matches nothing does
# not report a problem — it silently authorizes `update-ref -d` on a branch whose
# worker is still holding it. Renaming a label means updating BOTH literals here.
# Convention + why the two labels are distinct: docs/process/issue-conventions.md.
#
# A FAILED OR UNPARSEABLE LOOKUP IS ITS OWN ANSWER, distinct from "no claim". The
# old form did `[ -n "$row" ] || continue`, so a gh call that died — rate limit,
# expired token, network gone, API 500 — was indistinguishable from an issue with
# no claim label on it, and the loop fell through to the OK verdict. That is the
# same fail-open shape as the status and ps guards, arriving through the one clause
# whose entire job is knowing whether a human is still working in the tree. This
# function therefore emits the sentinel LOOKUP-FAILED, and hygiene_prove turns it
# into a REFUSE in BOTH the planning pass and the pre-delete revalidation.
#
# The one exception is narrow and deliberate: a number that is not an issue AT ALL
# is a real, complete answer meaning "nobody's work", and it must not be
# fail-closed. hygiene_issue_refs reads numbers out of branch names and commit
# bodies, so non-issue numbers are ordinary — treating them as lookup failures
# would refuse nearly every branch and the tool would be useless, which is its own
# way of being ignored. That exception is exactly as wide as hygiene_issue_absent:
# gh's issue-specific not-found naming the queried number, and nothing else. Every
# other nonzero exit — a 404 that names no issue, an unresolvable repository, an
# auth failure — and any successful call whose `state` field is not a state we
# recognize, fails closed.
hygiene_active_claim() {
  local branch="$1" default="$2" n row rc state labels errf refs
  # The ref list is built BEFORE anything else, because a list we could not build
  # is its own distinct answer — propagated verbatim so hygiene_prove can name the
  # real failure (`ref-lookup-failed`) instead of blaming gh.
  refs="$(hygiene_issue_refs "$branch" "$default")"
  case "$refs" in
    REF-LOOKUP-FAILED*) echo "$refs"; return 0 ;;
  esac
  errf="$(mktemp 2>/dev/null)" || {
    echo "LOOKUP-FAILED issue=? detail=mktemp-failed"
    return 0
  }
  for n in $refs; do
    row="$(_gh issue view "$n" --json state,labels \
      --jq '[.state, ([.labels[].name] | join(","))] | @tsv' 2>"$errf")"
    rc=$?
    if [ "$rc" -ne 0 ]; then
      if hygiene_issue_absent "$n" "$errf"; then
        continue
      fi
      rm -f "$errf"
      echo "LOOKUP-FAILED issue=#$n rc=$rc"
      return 0
    fi
    state="$(printf '%s' "$row" | cut -f1)"
    labels="$(printf '%s' "$row" | cut -f2)"
    # A zero exit with an answer we cannot read is not a passing answer either: an
    # empty or unrecognized state is exactly what an empty `row` produced before,
    # and it told us nothing about whether the issue is open.
    case "$state" in
      OPEN|CLOSED) ;;
      *) rm -f "$errf"
         echo "LOOKUP-FAILED issue=#$n detail=unparseable-state state=${state:-<empty>}"
         return 0 ;;
    esac
    [ "$state" = "OPEN" ] || continue
    case ",$labels," in
      *",status: in-progress,"*) rm -f "$errf"; echo "#$n status: in-progress"; return 0 ;;
      *",wave: owned,"*)         rm -f "$errf"; echo "#$n wave: owned"; return 0 ;;
    esac
  done
  rm -f "$errf"
  return 0
}

# ---------------------------------------------------------------------------
# Live-process evidence
# ---------------------------------------------------------------------------

#: The "print the full command line" flag for `pgrep -f`, passed as its OWN argv
#: word. BSD/macOS pgrep prints the whole argv for `-l` when paired with `-f`;
#: GNU/Linux pgrep's `-l` prints only the process NAME and needs `-a` for the
#: full line, while BSD's `-a` means something unrelated. So one intent needs two
#: flags. Kept in a variable rather than spelled inline because `-f$FLAG` builds
#: the single token `-f-l`, which pgrep rejects with `illegal option -- -`; that
#: one-character mistake meant `wave_worker.py`'s pgrep leg had never once run
#: between #1785 and #1839. Here the word is passed separately, and
#: `test_the_real_pgrep_leg_runs` runs the real binary so no stub can hide it.
if [ "$(uname -s)" = "Darwin" ]; then
  HYGIENE_PGREP_LIST_FLAG="-l"
else
  HYGIENE_PGREP_LIST_FLAG="-a"
fi

#: An ERE matching every command line (all of them have >= 1 character). `pgrep`
#: takes a pattern and has no "list everything" flag. Matching everything and
#: filtering afterwards — rather than passing the worktree path as the pattern —
#: is deliberate: a path is not a regex, so an unescaped `.` in a directory name
#: would silently widen the match, and both readers must agree on what a match
#: is. One awk substring filter, applied identically to whichever leg answered.
HYGIENE_PGREP_MATCH_ALL="."

# hygiene_procs_using <abs_path> — print one "pid argv" line per live process
# whose argv mentions <abs_path>, or the literal token PS-FAILED when NO reader
# could produce the process table.
#
# Why this is here at all: /session-cleanup owns process sweeping (#644) because
# it runs INSIDE the worktree it is about. This sweep is the opposite — it
# deletes worktrees it does not own and cannot see the background tasks of. So it
# does not kill anything; it refuses. `git worktree remove` yanking the checkout
# out from under a running dev server or agent is data loss with a confusing
# stack trace attached.
#
# TWO readers, pgrep first (#1850). `/bin/ps` is denied by the sandbox agent
# sessions run inside — measured on this machine it exits 127 — so the original
# single-`ps` read turned EVERY worktree candidate into `process-check-failed` on
# exactly the boxes this sweep is meant to run on. `pgrep` is not denied there,
# and it is the better reader anyway: it matches and prints the FULL command
# line, so there is no fixed-width `COMMAND` column for Linux to truncate
# (#1750/#1088) — a truncated argv drops the path and a dropped path is a live
# process reported as quiescent, which is fail-OPEN on a fail-closed clause.
# `ps` stays as the second leg for wherever pgrep is the missing tool.
#
# A leg counts as having answered only when it exits 0 AND prints something. For
# pgrep that is stricter than "rc 0 or 1", on purpose: the pattern matches every
# process, so an empty table is not a credible claim on a live system, and the
# house rule here is that a missing answer is never a passing answer.
#
# PS-FAILED (the name predates the second leg; it means "no reader answered") is
# deliberately indistinguishable from "found something" to the caller: when we
# cannot enumerate processes we have no evidence of quiescence, and no evidence
# must not read as good news.
#
# Own-PID exclusion: this script's argv is the script path plus flags, never a
# candidate worktree path, but $$ is excluded anyway so a future caller that
# passes a path as an argument cannot make the sweep refuse on itself.
hygiene_procs_using() {
  local path="$1" out
  out="$(${RPW_HYGIENE_PGREP:-pgrep} -f "$HYGIENE_PGREP_LIST_FLAG" "$HYGIENE_PGREP_MATCH_ALL" 2>/dev/null)"
  if [ $? -ne 0 ] || [ -z "$out" ]; then
    out="$(${RPW_HYGIENE_PS:-ps} -Ao pid=,args= 2>/dev/null)"
    if [ $? -ne 0 ] || [ -z "$out" ]; then
      echo "PS-FAILED"
      return 0
    fi
  fi
  printf '%s\n' "$out" | awk -v want="$path" -v self="$$" '
    index($0, want) == 0 { next }
    { if (($1 + 0) == self) next; print }
  '
}

# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

emit() { # <verdict> <rest...>
  local verdict="$1"; shift
  printf '%-8s %s\n' "$verdict" "$*"
  case "$verdict" in
    REAP)   N_REAP=$((N_REAP + 1)) ;;
    REFUSE) N_REFUSE=$((N_REFUSE + 1)) ;;
    SKIP)   N_SKIP=$((N_SKIP + 1)) ;;
  esac
}

# hygiene_protect_validate — reject a protect list that is not exact names.
#
# The documented contract is space-separated EXACT branch names, and the loop
# below splits the variable unquoted, so an entry carrying a glob metacharacter
# is subject to pathname expansion against the invoking directory. That failed
# OPEN in two directions at once, and both were reproduced before this guard
# existed. With a file `production-notes` in the cwd, `RPW_HYGIENE_PROTECT=
# 'production*'`:
#
#   - the entry the operator wrote is GONE — bash replaced the word with the
#     filenames it matched, so the branch they meant to protect is swept as
#     though they had never named it.
#   - an unrelated branch that happens to share a filename's spelling
#     (`production-notes`) becomes protected instead.
#
# A silently-not-protected branch is the destructive half, so this is fatal
# rather than a warning: an operator who reaches for a wildcard is expressing an
# intent this tool does not implement, and guessing at it authorizes deletions.
hygiene_protect_validate() {
  local pat rc=0 had_f=1
  # Globbing OFF for the split itself, so the metacharacter reaches the check
  # instead of being expanded away before it can be rejected. Restore whatever
  # the caller had, exactly as hygiene_is_protected does: a caller that had
  # already disabled globbing on purpose must not have it silently re-enabled
  # underneath it just because this function ran.
  case "$-" in *f*) ;; *) had_f=0 ;; esac
  set -f
  for pat in ${RPW_HYGIENE_PROTECT:-}; do
    case "$pat" in
      *[\*\?\[\]]*)
        err "RPW_HYGIENE_PROTECT entry '$pat' contains a glob metacharacter."
        err "  this variable takes EXACT space-separated branch names, not patterns."
        err "  a pattern would be expanded against the current directory, which"
        err "  silently DROPS the branch you meant to protect. Refusing to sweep."
        rc=2 ;;
    esac
  done
  [ "$had_f" = 0 ] && set +f
  return $rc
}

# hygiene_max_lookups_validate — the claim cap must be a strictly positive integer.
#
# MAX_ISSUE_LOOKUPS is spent as `head -n "$MAX_ISSUE_LOOKUPS"` at the end of
# hygiene_issue_refs, inside a command substitution. That failed OPEN for every
# value that is not a positive integer, and destructively so:
#
#   - `0`         — GNU head prints nothing and exits 0; BSD/macOS head rejects
#                   the count and exits 1. Either way the substitution captures
#                   NO refs, and the caller cannot distinguish "this branch owns
#                   no issue" from "the cap threw the list away".
#   - `-3`, `abc` — head rejects the argument and writes to stderr, which is not
#                   captured; the substitution is again empty.
#
# An empty ref list means hygiene_active_claim queries nothing, and a claim that
# is never looked up cannot report itself. So an actively claimed worker branch
# — `status: in-progress`, a live workspace — reached delete with the sweep
# reporting no claim at all. The cost guard was authorizing the exact deletion
# the claim check exists to prevent.
#
# Fatal, and fatal BEFORE any planning or proof, for the same reason the protect
# guard is: the failure it produces is a silent deletion, so there is no safe
# reading of the operator's intent to guess at. Unset or empty keeps the default
# (applied at assignment) — only an actively-supplied bad value is an error.
# Leading zeros are rejected too rather than normalized: `08` is not a base-10
# integer everywhere in shell, and a cap is not worth a second parsing dialect.
hygiene_max_lookups_validate() {
  # Valid iff: non-empty, every character a digit, and not starting with 0.
  # `*[!0-9]*` is what rejects `abc`, `-3`, `5x`, `1 2` and a trailing newline;
  # `0*` rejects both `0` itself and any leading-zero spelling.
  case "$MAX_ISSUE_LOOKUPS" in
    '' | *[!0-9]* | 0*) ;;   # invalid — fall through to the fatal message
    *) return 0 ;;
  esac
  err "RPW_HYGIENE_MAX_ISSUE_LOOKUPS='$MAX_ISSUE_LOOKUPS' is not a positive integer."
  err "  this is the per-branch cap on claim lookups; it must be >= 1 (default 5),"
  err "  written in base 10 with no leading zero, sign, or space."
  err "  a cap of 0 or a value head cannot parse drops EVERY issue ref, so no claim"
  err "  is ever looked up and a CLAIMED branch would be deleted. Refusing to sweep."
  return 2
}

# hygiene_is_protected <branch> — exact-name match against the protect lists.
#
# `set -f` is what makes the unquoted split honest: it still splits on IFS (which
# is how a space-separated list becomes entries) but performs no pathname
# expansion, so every entry is compared as the literal the operator typed.
# hygiene_protect_validate has already made a metacharacter fatal; this keeps the
# comparison literal regardless of how the function is reached.
hygiene_is_protected() {
  local branch="$1" pat had_f=1
  case "$-" in *f*) ;; *) had_f=0 ;; esac
  set -f
  for pat in $PROTECT_DEFAULT ${RPW_HYGIENE_PROTECT:-}; do
    if [ "$branch" = "$pat" ]; then
      [ "$had_f" = 0 ] && set +f
      return 0
    fi
  done
  [ "$had_f" = 0 ] && set +f
  return 1
}

# hygiene_prove <branch> <default> <main_wt> [exp_tip exp_pr exp_head exp_wt]
#
# The entire destructive-path proof for one `[gone]` branch. Prints exactly one
# TAB-separated record:
#
#   OK<TAB>tip<TAB>pr_num<TAB>pr_head<TAB>wt_path     safe to delete, right now
#   REFUSE<TAB>reason=...                             do not delete
#   SKIP<TAB>reason=...                               not ours to consider
#
# Called twice per candidate. With no expectation arguments it is the planning
# judgment. With them it is revalidation immediately before the mutation, and
# any drift from what was proved — a new commit, a different PR head, the branch
# moving to another worktree, the branch vanishing — is `changed-since-plan`.
#
# Re-deriving and then comparing is the point: re-running the clauses alone would
# happily approve a deletion of a branch that grew a commit since planning, since
# the new tip might legitimately match a newer PR head. The recorded expectation
# is what makes "the thing I judged" and "the thing I am deleting" the same
# object.
hygiene_prove() {
  local branch="$1" default="$2" main_wt="$3"
  local exp_tip="${4:-}" exp_pr="${5:-}" exp_head="${6:-}" exp_wt="${7:-}"
  local revalidate=0
  [ -n "$exp_tip" ] && revalidate=1

  local tip wt_row wt_path wt_locked rows count pr_num state pr_head
  local status_out status_rc dirty procs claim
  local ignored_out ignored_rc ignored_list n_ignored ignored_sample

  # --- the ref still exists and still points where it was proved to point ----
  tip="$(git rev-parse --verify --quiet "refs/heads/$branch" 2>/dev/null)"
  if [ -z "$tip" ]; then
    echo "REFUSE${TAB}reason=branch-vanished branch=$branch"
    return 0
  fi
  if [ "$revalidate" = 1 ] && [ "$tip" != "$exp_tip" ]; then
    echo "REFUSE${TAB}reason=changed-since-plan detail=tip-moved planned=$exp_tip now=$tip"
    return 0
  fi

  # --- worktree identity, lock state -----------------------------------------
  wt_row="$(hygiene_worktree_for "$branch")"
  wt_path="$(printf '%s' "$wt_row" | cut -f1)"
  wt_locked="$(printf '%s' "$wt_row" | cut -f2)"

  if [ -n "$wt_path" ] && [ "$wt_path" = "$main_wt" ]; then
    echo "SKIP${TAB}reason=main-worktree wt=$wt_path"
    return 0
  fi
  if [ "$revalidate" = 1 ] && [ "$wt_path" != "$exp_wt" ]; then
    echo "REFUSE${TAB}reason=changed-since-plan detail=worktree-moved planned=${exp_wt:-none} now=${wt_path:-none}"
    return 0
  fi
  if [ -n "$wt_path" ] && [ "$wt_locked" = "1" ]; then
    echo "REFUSE${TAB}reason=worktree-locked wt=$wt_path"
    return 0
  fi

  # --- the merged-PR proof ---------------------------------------------------
  rows="$(hygiene_pr_rows "$branch")"
  count="$(printf '%s' "$rows" | grep -c . )"
  if [ "$count" -eq 0 ]; then
    echo "REFUSE${TAB}reason=no-pr-found (upstream [gone] is not proof the work landed)"
    return 0
  fi
  if [ "$count" -gt 1 ]; then
    echo "REFUSE${TAB}reason=ambiguous-pr prs=$(printf '%s' "$rows" | cut -f1 | tr '\n' ',' | sed 's/,$//')"
    return 0
  fi
  pr_num="$(printf '%s' "$rows" | cut -f1)"
  state="$(printf '%s' "$rows" | cut -f2)"
  pr_head="$(printf '%s' "$rows" | cut -f3)"
  if [ "$state" != "MERGED" ]; then
    echo "REFUSE${TAB}reason=pr-not-merged pr=#$pr_num state=$state"
    return 0
  fi

  # An absent or malformed head OID is the finding that used to fail open: the
  # old guard was `[ -n "$pr_head" ] && [ "$pr_head" != "$tip" ]`, so an empty
  # field skipped the comparison entirely and the branch was reaped on the
  # strength of a proof that was never evaluated. Require a full hex OID.
  case "$pr_head" in
    *[!0-9a-fA-F]* | "")
      echo "REFUSE${TAB}reason=unusable-pr-head pr=#$pr_num head=${pr_head:-<empty>} (no proof of what was pushed)"
      return 0 ;;
  esac
  if [ "${#pr_head}" -lt 7 ]; then
    echo "REFUSE${TAB}reason=unusable-pr-head pr=#$pr_num head=$pr_head (too short to identify a commit)"
    return 0
  fi
  if [ "$pr_head" != "$tip" ]; then
    echo "REFUSE${TAB}reason=unpushed-commits tip=$tip pr=#$pr_num head=$pr_head"
    return 0
  fi
  if [ "$revalidate" = 1 ] && { [ "$pr_num" != "$exp_pr" ] || [ "$pr_head" != "$exp_head" ]; }; then
    echo "REFUSE${TAB}reason=changed-since-plan detail=pr-proof-moved planned=#$exp_pr@$exp_head now=#$pr_num@$pr_head"
    return 0
  fi

  # --- worktree state: clean tree, no live process ---------------------------
  if [ -n "$wt_path" ]; then
    if [ ! -d "$wt_path" ]; then
      echo "REFUSE${TAB}reason=worktree-path-missing wt=$wt_path (registered but not on disk — prune first)"
      return 0
    fi
    # `git status` is captured and its exit status checked SEPARATELY. The old
    # `git status --porcelain 2>/dev/null | grep -c .` reported zero — i.e.
    # "clean" — for a status that failed outright, so an unreadable index or a
    # half-removed worktree authorized deletion.
    status_out="$(git -C "$wt_path" status --porcelain 2>/dev/null)"
    status_rc=$?
    if [ "$status_rc" -ne 0 ]; then
      echo "REFUSE${TAB}reason=status-failed wt=$wt_path rc=$status_rc (cannot prove the tree is clean)"
      return 0
    fi
    dirty="$(printf '%s' "$status_out" | grep -c . )"
    if [ "$dirty" -gt 0 ]; then
      echo "REFUSE${TAB}reason=dirty-worktree wt=$wt_path files=$dirty"
      return 0
    fi

    # IGNORED content is a SEPARATE scan, because the clean check above cannot
    # see it and `git worktree remove` will not stop for it. Reproduced before
    # this guard existed: a worktree holding `.env` with a live secret and a
    # populated `.venv/` reported `git status --porcelain` EMPTY (rc 0, i.e.
    # "clean"), and `git worktree remove` then exited 0 having deleted both. The
    # proof said clean and the secret was gone — the exact fail-open shape this
    # script's other guards exist to prevent, arriving through the one file class
    # nobody diffs.
    #
    # This tool's contract is that it touches nothing uncommitted, and ignored is
    # not the same claim as regenerable. `.env`, `dev.env`, and a local `uv.lock`
    # are all ignored here and none of them can be reconstructed from the repo —
    # `.env` holds secrets by definition, and `uv.lock` is gitignored precisely
    # BECAUSE it is environment-specific (AGENTS.md: each environment resolves its
    # own registry). So there is no allowlist of "safe" ignored patterns: any
    # ignored entry is a refusal, and the operator deletes the worktree by hand
    # once they have looked at it.
    #
    # Count and paths are reported; file CONTENT never is. The likeliest thing
    # found here is a secrets file, and this report is meant to be pasted around.
    ignored_out="$(git -C "$wt_path" status --porcelain --ignored=matching 2>/dev/null)"
    ignored_rc=$?
    # Exit status checked separately, for the same reason as the clean scan: a
    # status that FAILS produces no `!!` lines, which is textually identical to
    # "there is no ignored content here" — the answer that authorizes deletion.
    if [ "$ignored_rc" -ne 0 ]; then
      echo "REFUSE${TAB}reason=ignored-scan-failed wt=$wt_path rc=$ignored_rc (cannot prove no ignored content would be destroyed)"
      return 0
    fi
    ignored_list="$(printf '%s\n' "$ignored_out" | awk '/^!! /{print substr($0, 4)}')"
    n_ignored="$(printf '%s' "$ignored_list" | grep -c . )"
    if [ "$n_ignored" -gt 0 ]; then
      ignored_sample="$(printf '%s\n' "$ignored_list" | head -n 3 | tr '\n' ' ' | sed 's/ $//')"
      [ "$n_ignored" -gt 3 ] && ignored_sample="$ignored_sample ..."
      echo "REFUSE${TAB}reason=ignored-files wt=$wt_path count=$n_ignored paths=$ignored_sample (ignored is not regenerable — remove by hand)"
      return 0
    fi

    procs="$(hygiene_procs_using "$wt_path")"
    if [ "$procs" = "PS-FAILED" ]; then
      echo "REFUSE${TAB}reason=process-check-failed wt=$wt_path (cannot enumerate processes)"
      return 0
    fi
    if [ -n "$procs" ]; then
      echo "REFUSE${TAB}reason=live-process wt=$wt_path pids=$(printf '%s' "$procs" | awk '{print $1}' | tr '\n' ',' | sed 's/,$//')"
      return 0
    fi
  fi

  # --- claims ---------------------------------------------------------------
  claim="$(hygiene_active_claim "$branch" "$default")"
  # A lookup we could not complete is a refusal, never "no claim". Same reading as
  # status-failed and process-check-failed: we have no evidence nobody is working
  # in this tree, and no evidence must not read as good news when the mutation is
  # `update-ref -d`. This arm is reached from planning AND from revalidation,
  # because hygiene_prove is literally the same function in both passes.
  case "$claim" in
    # Distinct from a failed gh call: here we could not even build the LIST of
    # issues to ask about, so no lookup was attempted. Reported under its own
    # reason so the operator fixes git, not their token. Reached from planning AND
    # revalidation, same as every other arm in this function.
    REF-LOOKUP-FAILED*)
      echo "REFUSE${TAB}reason=ref-lookup-failed ${claim#REF-LOOKUP-FAILED } (cannot enumerate the issues this branch references)"
      return 0 ;;
    LOOKUP-FAILED*)
      echo "REFUSE${TAB}reason=claim-lookup-failed ${claim#LOOKUP-FAILED } (cannot prove no worker holds this branch)"
      return 0 ;;
  esac
  if [ -n "$claim" ]; then
    echo "REFUSE${TAB}reason=active-claim claim=$claim"
    return 0
  fi

  echo "OK${TAB}${tip}${TAB}${pr_num}${TAB}${pr_head}${TAB}${wt_path}"
  return 0
}

# hygiene_sweep — the whole decision table, one branch at a time.
#
# Reap candidates are collected into REAP_PLAN (newline-separated
# "branch<TAB>tip<TAB>pr_num<TAB>pr_head<TAB>worktree" rows) rather than acted on
# inline: the full report must print even when apply is off, and apply must never
# interleave with judgment.
#
# The plan carries the PROOF, not just the target. Recording tip/pr/head is what
# lets apply verify it is deleting the same object the sweep judged, instead of
# re-deriving a fresh verdict for whatever the branch has since become.
hygiene_sweep() {
  local default current_branch main_wt
  default="$(hygiene_default_branch)"
  if [ -z "$default" ]; then
    err "cannot resolve the default branch — refusing to sweep."
    err "  set RPW_HYGIENE_DEFAULT_BRANCH=<branch> or fix refs/remotes/origin/HEAD"
    return 2
  fi
  current_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  main_wt="$(hygiene_main_worktree)"

  log "default branch: $default   apply: $([ "$APPLY" = 1 ] && echo yes || echo "no (dry run)")"

  REAP_PLAN=""

  # Field order is load-bearing: bash's `read` treats TAB as IFS *whitespace*, so
  # consecutive tabs collapse and an empty field mid-row shifts every field after
  # it. Only the possibly-empty fields (upstream, track) may sit at the end —
  # trailing empties collapse harmlessly, a middle one silently put a SHA in
  # `track`.
  local branch tip upstream track record verdict rest p_tip p_pr p_head p_wt
  while IFS="$TAB" read -r branch tip upstream track; do
    [ -n "$branch" ] || continue

    if hygiene_is_protected "$branch" || [ "$branch" = "$default" ]; then
      emit SKIP "branch=$branch reason=protected-branch"
      continue
    fi
    if [ "$branch" = "$current_branch" ]; then
      emit SKIP "branch=$branch reason=current-branch (the sweep never reaps what it runs from)"
      continue
    fi
    if [ -z "$upstream" ]; then
      emit SKIP "branch=$branch reason=no-upstream (never pushed — nothing to prove it landed)"
      continue
    fi
    if [ "$track" != "[gone]" ]; then
      emit SKIP "branch=$branch reason=upstream-live upstream=$upstream track=${track:-in-sync}"
      continue
    fi

    # `[gone]` from here down: the full proof, which refuses on every unmet
    # clause. Exactly the function apply re-runs before mutating.
    record="$(hygiene_prove "$branch" "$default" "$main_wt")"
    verdict="$(printf '%s' "$record" | cut -f1)"
    if [ "$verdict" != "OK" ]; then
      rest="$(printf '%s' "$record" | cut -f2-)"
      emit "$verdict" "branch=$branch $rest"
      continue
    fi

    p_tip="$(printf '%s' "$record" | cut -f2)"
    p_pr="$(printf '%s' "$record" | cut -f3)"
    p_head="$(printf '%s' "$record" | cut -f4)"
    p_wt="$(printf '%s' "$record" | cut -f5)"

    emit REAP "branch=$branch pr=#$p_pr MERGED tip=$p_tip wt=${p_wt:-none} tree=clean"
    REAP_PLAN="${REAP_PLAN}${branch}${TAB}${p_tip}${TAB}${p_pr}${TAB}${p_head}${TAB}${p_wt}
"
  done <<EOF
$(git for-each-ref refs/heads \
    --format='%(refname:short)%09%(objectname)%09%(upstream:short)%09%(upstream:track)' 2>/dev/null)
EOF

  return 0
}

# hygiene_apply — execute REAP_PLAN. Worktree first, then the branch: removing a
# worktree while its branch is gone leaves a prunable stub, but deleting the
# branch first makes `git worktree remove` operate on a detached leftover.
# Deleting an unmerged-looking ref is authorized by the merged-PR proof, not by
# git's own reachability check (a squash-merge never satisfies that) — hence
# `update-ref -d <proven-oid>` rather than either `-d` or `-D` on `git branch`.
#
# Each row is RE-PROVED against the proof recorded at planning time, immediately
# before its own mutation — not once for the batch. Two removals earlier in the
# loop take real time (a `git worktree remove` plus a `gh` round trip each), and
# that time is exactly the window in which a worker can commit into the third
# candidate. Per-row revalidation makes the window as small as it can be while
# still being a separate step, and a refusal here is an apply FAILURE (nonzero
# exit), not a silent skip: the operator asked for a deletion that the repo no
# longer permits, and that is news.
hygiene_apply() {
  local default main_wt branch tip pr head wt record verdict rest
  default="$(hygiene_default_branch)"
  main_wt="$(hygiene_main_worktree)"

  # Test seam only: lets a test mutate the repo inside the plan/apply window.
  # Invoked as a command, deliberately NOT `eval`, matching the pre-delete seam.
  # `eval` gave an environment variable the power to run arbitrary shell inside
  # the one function whose job is deleting refs — a seam that exists to prove the
  # safety guards work must not be a way around them. Command invocation keeps
  # the mutation seam (a test still runs whatever it wants) while removing the
  # string-to-shell step: the value is a path to an executable, nothing more.
  if [ -n "${RPW_HYGIENE_PRE_APPLY_HOOK:-}" ]; then
    log "pre-apply hook (test seam): $RPW_HYGIENE_PRE_APPLY_HOOK"
    "$RPW_HYGIENE_PRE_APPLY_HOOK" || true
  fi

  while IFS="$TAB" read -r branch tip pr head wt; do
    [ -n "$branch" ] || continue

    record="$(hygiene_prove "$branch" "$default" "$main_wt" "$tip" "$pr" "$head" "$wt")"
    verdict="$(printf '%s' "$record" | cut -f1)"
    if [ "$verdict" != "OK" ]; then
      rest="$(printf '%s' "$record" | cut -f2-)"
      err "ABORTED branch=$branch $rest"
      err "  the proof from the report no longer holds — nothing was deleted for this branch."
      N_FAIL=$((N_FAIL + 1))
      continue
    fi

    if [ -n "$wt" ]; then
      if git worktree remove "$wt" 2>&1; then
        log "removed worktree $wt"
      else
        err "FAILED to remove worktree $wt — leaving branch $branch alone"
        N_FAIL=$((N_FAIL + 1))
        continue
      fi
    fi
    # Test seam only: mutate the ref AFTER the final proof and BEFORE the delete,
    # i.e. inside the one window the compare-and-delete below exists to close.
    # Invoked as a command with the branch as its argument — deliberately not
    # `eval`, so nothing here can expand into a second git invocation.
    if [ -n "${RPW_HYGIENE_PRE_DELETE_HOOK:-}" ]; then
      log "pre-delete hook (test seam): $RPW_HYGIENE_PRE_DELETE_HOOK $branch"
      "$RPW_HYGIENE_PRE_DELETE_HOOK" "$branch" || true
    fi

    # Compare-and-delete against the OID the proof was made about. `git branch -D`
    # deletes whatever the ref names at execution time, so the re-proof above
    # still leaves a window: between `hygiene_prove` returning OK and the delete
    # running, a concurrent commit or `git update-ref` can replace the tip, and
    # `-D` would take the new, unproven commit with it. The expected-old-value
    # argument to `git update-ref -d` makes the check and the mutation one atomic
    # operation: if the ref moved at all, the delete FAILS and is counted, which
    # is the whole safety property. There is no `branch -D` fallback — falling
    # back would delete exactly the ref the failure was protecting.
    if git update-ref -d "refs/heads/$branch" "$tip" 2>/dev/null; then
      log "deleted branch $branch (was $tip)"
    else
      err "FAILED to delete branch $branch — ref is no longer at the proven $tip"
      err "  it moved after the proof; the new commit was left in place."
      N_FAIL=$((N_FAIL + 1))
    fi
  done <<EOF
$REAP_PLAN
EOF
  git worktree prune 2>/dev/null || true
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --apply)    APPLY=1 ;;
      --no-fetch) FETCH=0 ;;
      -h|--help)  usage; return 0 ;;
      *) err "unknown argument: $1"; usage >&2; return 1 ;;
    esac
    shift
  done

  git rev-parse --git-dir >/dev/null 2>&1 || { err "not a git repository"; return 1; }

  # Before any judgment: a protect list that is not exact names is fatal, because
  # the failure it produces is a branch that is swept as though never protected.
  hygiene_protect_validate || return $?

  # Same shape, same reason: a cap that is not a positive integer silently empties
  # the claim-ref list, so it is rejected before a single proof or mutation runs.
  hygiene_max_lookups_validate || return $?

  # Fetch before judging: `[gone]` is only true after a prune, so a sweep on
  # stale remote-tracking refs under-reports (never over-reports) reap
  # candidates. Best-effort — an offline machine still gets a correct, more
  # conservative report.
  if [ "$FETCH" = 1 ]; then
    git fetch --prune --quiet 2>/dev/null || log "fetch failed — judging on local remote-tracking refs (report may under-report)"
  fi

  hygiene_sweep || return $?

  echo ""
  log "reap: $N_REAP   refuse: $N_REFUSE   skip: $N_SKIP"

  if [ "$APPLY" = 1 ]; then
    if [ "$N_REAP" -eq 0 ]; then
      log "nothing to reap."
      return 0
    fi
    echo ""
    hygiene_apply
    [ "$N_FAIL" -eq 0 ] || { err "$N_FAIL removal(s) failed — see above."; return 1; }
    return 0
  fi

  if [ "$N_REAP" -gt 0 ]; then
    echo ""
    log "DRY RUN — nothing was deleted. To reap the $N_REAP above:"
    log "    make branch-hygiene APPLY=1"
  fi
  return 0
}

# Sourceable for tests; executable for humans and the Makefile.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
