#!/usr/bin/env bash
# Wave mechanics entry point — the claim + spawn machinery, from any directory.
#
# GitHub Issues #842 / #840. The `wave-supervisor` skill ships to every repo;
# its mechanics did not. `wave_worker.py` (`make wave-spawn` / `make wave-land`)
# and the claim protocol (`make build-claim` / `make build-honor-check`) were
# reachable ONLY through one repo's Makefile, so a supervisor following the
# skill in any other repo found nothing to call and improvised. The improvisation
# was a bare `status: in-progress` label via `gh issue edit` — a read-then-write
# with no compare-and-swap — and on 2026-08-05, on a repo with no Makefile at
# all, two supervisors each read "unclaimed", each dispatched a worker at issue
# #6, and the repo got duplicate implementations on two branches. Three
# supervisors ended up dispatching against the same issues. Nothing warned
# anyone: the degradation removed the safety mechanism, not the convenience, and
# the supervisor reported normal progress throughout.
#
# This script is the single documented entry point. It does two jobs:
#
#   1. RESOLVE the machinery from wherever the plugin is installed, so the
#      supervisor's cwd stops mattering. `$0` is inside the plugin, so the claim
#      library is always beside it; the Python tooling is found through the
#      ladder in `resolve_tools` below.
#   2. PREFLIGHT it and FAIL LOUD. `preflight` is what the skill runs before the
#      first dispatch: it exits non-zero when the machinery is not resolvable so
#      a wave that cannot claim atomically does not run. That is #840's
#      recommendation and it is not negotiable down to a warning.
#
# Every verb operates on the git repo of the CURRENT directory — never on the
# repo this script happens to live in. `( cd <worker-worktree> && wave-mechanics
# claim 6 )` stamps that worktree's branch, which is the #568 ordering the wave
# protocol depends on.
#
#   wave-mechanics.sh preflight [--json]      resolve everything; nonzero = STOP
#   wave-mechanics.sh which <component>       print a resolved path
#   wave-mechanics.sh claim <issue> [sup]     claim an issue (label + sentinel)
#   wave-mechanics.sh honor-check <issue>     is it taken? 0 / 3 / 4
#   wave-mechanics.sh audit                   unclaimed in-flight work alarm
#   wave-mechanics.sh spawn|land|state-workers|record-status [args]
#   wave-mechanics.sh lease <verb> [args]     wave_owner.py (the wave mutex)
#
# `wave-mechanics.sh help` prints the full verb list; `wm_usage` declares it.
#
# Components, and why each is REQUIRED before a multi-worker wave runs:
#
#   claim   `build-claim.sh` — the ATTRIBUTION layer: which branch and which
#           supervisor holds an issue, and whether a competing claim is a
#           sibling worker or a foreign supervisor. Ships inside the plugin, so
#           it resolves wherever the plugin is installed.
#   lease   `wave_owner.py` — the only genuine MUTEX in the protocol:
#           `refs/wave-owner/<wave>` created via create-only `POST /git/refs`,
#           which GitHub answers 422 on contention, server-side (#886). Labels,
#           comments and assignees are all applied unconditionally, so two
#           supervisors both "win" them; the ref is the one primitive that can
#           fail on contention. Missing lease = no atomicity = do not run.
#   worker  `wave_worker.py` — spawn/land and the `.wave/worker-<n>.meta.json`
#           ledger. Its absence is what left the 2026-08-05 supervisor with no
#           machine-readable record of what it had dispatched (a contributing
#           factor in #827's false "worker dead" inference).
#
# NOT a new carrier — an interim launcher. #907 (P0 epic) owns the strategic
# question "is Make the right vehicle for invariant plugin mechanics?", recommends
# Option D (invariant behavior becomes `rpw` CLI verbs delivered by uvx; Make stays
# the project-varying surface), and gates it behind an ADR as its Phase 1. That
# decision is NOT made here and must not be inferred from this file. What this
# script does is deliver #907's Phase 3 shape — the skill stops depending on a
# `make` target that exists in one repo — without pre-empting Phase 2's packaging
# choice. When the `rpw wave …` verb group lands, this file becomes a shim over it
# or is deleted; the verbs and exit codes are the contract worth keeping either way.
#
# Known limit, stated rather than papered over: the PUBLIC mirror's include-list is
# `plugins/rpw-published/` only, so a mirror-only install carries this script and
# `build-claim.sh` but none of the root `scripts/*.py`. There the claim layer
# resolves and the lease/ledger do not, and `preflight` reports exactly that with a
# remedy. Making the Python travel inside the plugin artifact is #907 Phase 2's job.
#
# Log prefix: 'wave-mechanics:'

set -u

_wm_script_dir() {
  # Resolve symlinks so an entry point linked onto PATH still finds its siblings.
  local src="${BASH_SOURCE[0]:-$0}" dir
  while [ -L "$src" ]; do
    dir="$(cd -P "$(dirname "$src")" && pwd)"
    src="$(readlink "$src")"
    case "$src" in /*) ;; *) src="$dir/$src" ;; esac
  done
  cd -P "$(dirname "$src")" && pwd
}

WM_DIR="$(_wm_script_dir)"

# The claim library always ships beside this script. RPW_CLAIM_LIB overrides it
# for tests and for a deliberately relocated install.
WM_CLAIM_LIB="${RPW_CLAIM_LIB:-$WM_DIR/build-claim.sh}"

# resolve_tools — print the directory holding wave_worker.py, or nothing.
#
# Ordered ladder, most explicit first. Each rung answers a different install
# shape, and the reason a plain "look in the repo" rung is NOT enough is the
# whole bug: the target repo is exactly where the tooling isn't.
#
#   1. $RPW_WAVE_TOOLS      — explicit override; the escape hatch for any layout
#                             this ladder does not anticipate.
#   2. $CLAUDE_PLUGIN_ROOT  — set for plugin hooks and MCP servers. Not exported
#                             into a skill's Bash environment, which is why it
#                             cannot be the only rung.
#   3. this script's own checkout — `plugins/rpw-published/scripts/` sits three
#                             levels under the repo root, so this rung resolves
#                             both a source checkout AND an installed
#                             marketplace clone (which carries the whole repo).
#                             This is the rung that fixes the observed incident:
#                             a wave run from a foreign repo on a machine that
#                             has the marketplace installed.
#   4. the target repo      — for a repo that genuinely vendors the tooling.
#   5. known marketplace clones under ~/.claude/plugins/marketplaces/.
#
# A public mirror that ships `plugins/` only carries no Python at rungs 3 and 5;
# there the tooling is honestly `absent` and `preflight` says so with a
# remediation rather than letting the wave run without a ledger or a lease.
resolve_tools() {
  local cand target
  target="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  for cand in \
    "${RPW_WAVE_TOOLS:-}" \
    "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/../../scripts}" \
    "$WM_DIR/../../../scripts" \
    "${target:+$target/scripts}" \
    "$HOME"/.claude/plugins/marketplaces/*/scripts
  do
    [ -n "$cand" ] || continue
    # EITHER file identifies the tooling directory, and each component is then
    # checked independently. Keying only on wave_worker.py would collapse two
    # different failures into one: a dir with the lease but no ledger would read
    # as "no tooling at all", so `preflight` could never report the softer
    # ledger-only failure (exit 4) that has a different remedy.
    if [ -f "$cand/wave_worker.py" ] || [ -f "$cand/wave_owner.py" ]; then
      ( cd -P "$cand" 2>/dev/null && pwd ) && return 0
    fi
  done
  return 1
}

# _wm_python — the interpreter for the stdlib-only tooling.
#
# Plain `python3`, not `uv run python`: the scripts import nothing outside the
# stdlib on purpose, and a foreign repo has no uv project for `uv run` to
# resolve. RPW_WAVE_PYTHON overrides.
_wm_python() { printf '%s' "${RPW_WAVE_PYTHON:-python3}"; }

# ---------------------------------------------------------------------------
# preflight — the gate the skill runs before the first dispatch
# ---------------------------------------------------------------------------
#
# Exit codes are the contract, and they separate the two failures because they
# have different remedies:
#   0  every component resolved — a multi-worker wave may run.
#   3  the ATOMIC layer is missing (claim library or wave lease). A wave that
#      cannot claim atomically MUST NOT RUN (#840).
#   4  atomicity is fine but the ledger/spawn mechanics are missing. Dispatch is
#      hand-run and unrecorded; treat as a stop unless the operator has read the
#      remediation and accepted it.
preflight() {
  local json=0
  [ "${1:-}" = "--json" ] && json=1

  local claim_state="ready" claim_detail="$WM_CLAIM_LIB"
  if [ ! -f "$WM_CLAIM_LIB" ]; then
    claim_state="absent"
    claim_detail="no build-claim.sh beside $WM_DIR (set RPW_CLAIM_LIB)"
  fi

  local tools worker_state worker_detail lease_state lease_detail
  tools="$(resolve_tools || true)"
  if [ -n "$tools" ]; then
    if [ -f "$tools/wave_worker.py" ]; then
      worker_state="ready"; worker_detail="$tools/wave_worker.py"
    else
      worker_state="absent"; worker_detail="wave_worker.py not in $tools"
    fi
    if [ -f "$tools/wave_owner.py" ]; then
      lease_state="ready"; lease_detail="$tools/wave_owner.py"
    else
      lease_state="absent"; lease_detail="wave_owner.py not in $tools"
    fi
  else
    worker_state="absent"
    worker_detail="wave_worker.py not resolvable (set RPW_WAVE_TOOLS=<dir>)"
    lease_state="absent"
    lease_detail="wave_owner.py not resolvable (set RPW_WAVE_TOOLS=<dir>)"
  fi

  # Probe PATH FIRST, then ask for the version: invoking a missing interpreter
  # emits bash's own "command not found" on stderr, which lands in the middle of
  # the preflight report and reads like a crash rather than a finding.
  local py_state py_detail
  if command -v "$(_wm_python)" >/dev/null 2>&1; then
    py_state="ready"
    py_detail="$( _wm_python ) $("$(_wm_python)" -c 'import sys; print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null)"
  else
    py_state="absent"; py_detail="$(_wm_python) not on PATH"
  fi

  # git belongs to the atomic layer, not to a softer one. Without it the claim
  # sentinel cannot read the branch it is supposed to stamp, `resolve_tools`
  # cannot see the target repo, and every honor-check compares against an empty
  # branch name — which is the silent-degradation shape this whole gate exists
  # to refuse (#840).
  local git_state="ready" git_detail="git on PATH"
  if ! command -v git >/dev/null 2>&1; then
    git_state="absent"; git_detail="git not on PATH — no branch to stamp or compare"
  fi

  local gh_state="ready" gh_detail="gh on PATH"
  if ! command -v "${GH:-gh}" >/dev/null 2>&1; then
    gh_state="absent"; gh_detail="${GH:-gh} not on PATH — no claim can be written or read"
  fi

  if [ "$json" -eq 1 ]; then
    printf '{"component":"claim","state":"%s","detail":"%s"}\n'  "$claim_state"  "$claim_detail"
    printf '{"component":"lease","state":"%s","detail":"%s"}\n'   "$lease_state"  "$lease_detail"
    printf '{"component":"worker","state":"%s","detail":"%s"}\n'  "$worker_state" "$worker_detail"
    printf '{"component":"python","state":"%s","detail":"%s"}\n'  "$py_state"     "$py_detail"
    printf '{"component":"gh","state":"%s","detail":"%s"}\n'      "$gh_state"     "$gh_detail"
    printf '{"component":"git","state":"%s","detail":"%s"}\n'     "$git_state"    "$git_detail"
  else
    echo "wave-mechanics: preflight (target repo: $(git rev-parse --show-toplevel 2>/dev/null || echo 'not a git repo'))"
    printf '  %-7s %-8s %s\n' claim  "$claim_state"  "$claim_detail"
    printf '  %-7s %-8s %s\n' lease  "$lease_state"  "$lease_detail"
    printf '  %-7s %-8s %s\n' worker "$worker_state" "$worker_detail"
    printf '  %-7s %-8s %s\n' python "$py_state"     "$py_detail"
    printf '  %-7s %-8s %s\n' gh     "$gh_state"     "$gh_detail"
    printf '  %-7s %-8s %s\n' git    "$git_state"    "$git_detail"
  fi

  # The atomic layer first: without it a wave has no mutual exclusion at all.
  # `gh` and `python3` belong to this layer, not to a softer one: with either
  # missing no claim can be WRITTEN OR READ, so every claim silently succeeds at
  # nothing — indistinguishable from having no protocol.
  local broken=""
  [ "$claim_state" = "ready" ] || broken="$broken claim"
  [ "$lease_state" = "ready" ] || broken="$broken lease"
  [ "$py_state"    = "ready" ] || broken="$broken python"
  [ "$gh_state"    = "ready" ] || broken="$broken gh"
  [ "$git_state"   = "ready" ] || broken="$broken git"
  if [ -n "$broken" ]; then
    {
      echo "⛔ wave-mechanics: the atomic claim layer is NOT usable here —"
      echo "   unresolved:${broken}."
      echo "   A wave that cannot claim atomically MUST NOT RUN (#840): two"
      echo "   supervisors will each read 'unclaimed' and both dispatch. On"
      echo "   2026-08-05 that produced duplicate implementations of one issue on"
      echo "   two branches."
      echo "   Remedy, in order:"
      echo "     1. install the marketplace so the plugin ships its own tooling, or"
      echo "     2. RPW_WAVE_TOOLS=<dir containing wave_worker.py + wave_owner.py>, or"
      echo "     3. run ONE worker at a time, by hand, and say so in the wave plan."
      echo "   Do not substitute a bare 'status: in-progress' label: it is a"
      echo "   read-then-write with no compare-and-swap."
    } >&2
    return 3
  fi

  if [ "$worker_state" != "ready" ]; then
    {
      echo "⛔ wave-mechanics: claims are atomic but the spawn/land ledger is NOT"
      echo "   resolvable. Dispatch would be hand-run and the"
      echo "   .wave/worker-<n>.meta.json ledger unwritten, which is how a"
      echo "   supervisor loses track of what it dispatched (#827)."
      echo "   Set RPW_WAVE_TOOLS=<dir containing wave_worker.py>, or accept"
      echo "   hand-run dispatch explicitly in the wave plan."
    } >&2
    return 4
  fi

  echo "wave-mechanics: preflight OK — claim, lease and ledger all resolvable."
  return 0
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

_wm_require_tools() {
  local tools
  tools="$(resolve_tools || true)"
  if [ -z "$tools" ]; then
    {
      echo "⛔ wave-mechanics: cannot resolve wave_worker.py from $PWD."
      echo "   Run 'wave-mechanics.sh preflight' for the full report and remedy."
    } >&2
    return 3
  fi
  printf '%s' "$tools"
}

_wm_run_tool() {
  local script="$1"; shift
  local tools; tools="$(_wm_require_tools)" || return $?
  if [ ! -f "$tools/$script" ]; then
    echo "⛔ wave-mechanics: $script is not in $tools (run 'preflight')." >&2
    return 3
  fi
  # --repo-root defaults to the git root of the CURRENT directory inside
  # wave_worker.py, so the target repo is the caller's, not this script's.
  "$(_wm_python)" "$tools/$script" "$@"
}

# The usage text is DECLARED here, not scraped out of the header with a line
# range. `sed -n '2,40p'` printed 25 lines of incident history before the first
# verb and silently drifted every time a comment was added above it — a help
# message that has to be scrolled past is one nobody reads.
wm_usage() {
  cat >&2 <<'USAGE'
usage: wave-mechanics.sh <verb> [args]

  preflight [--json]              resolve claim + lease + ledger; REQUIRED before
                                  the first dispatch of any wave. Exit 0 ready /
                                  3 no atomic claim layer (DO NOT RUN A WAVE) /
                                  4 atomic but no spawn-land ledger
  which <claim|lease|worker|tools>  print where a component resolved to
  claim <issue> [supervisor]      claim an issue (label + sentinel). Run it with
                                  cwd INSIDE the worker's worktree (#568)
  honor-check <issue> [supervisor]  is it taken? exit 0 dispatchable /
                                  3 claimed-by-other / 4 foreign supervisor
  audit                           alarm on in-flight commits with no claim
  spawn|land|state-workers|record-status|gate|gate-check|brief-check|pr-check
                                  wave_worker.py verbs, passed through
  lease <verb> [args]             wave_owner.py — the wave mutex (claim|check|
                                  guard|heartbeat|release|state-append)
  help                            this message

Every verb acts on the git repo of the CURRENT directory, never on the repo this
script lives in. Needs bash, git, gh and the system python3 — no make, no uv, no
venv. Overrides: RPW_WAVE_TOOLS=<dir with wave_worker.py + wave_owner.py>,
RPW_CLAIM_LIB=<path to build-claim.sh>, RPW_WAVE_PYTHON=<interpreter>.
USAGE
}

wm_main() {
  local verb="${1:-preflight}"
  shift 2>/dev/null || true
  case "$verb" in
    preflight)      preflight "$@" ;;
    which)
      case "${1:-}" in
        claim)  printf '%s\n' "$WM_CLAIM_LIB" ;;
        lease)  local t; t="$(_wm_require_tools)" || return $?; printf '%s\n' "$t/wave_owner.py" ;;
        worker) local t2; t2="$(_wm_require_tools)" || return $?; printf '%s\n' "$t2/wave_worker.py" ;;
        tools)  local t3; t3="$(_wm_require_tools)" || return $?; printf '%s\n' "$t3" ;;
        *) echo "wave-mechanics: which <claim|lease|worker|tools>" >&2; return 64 ;;
      esac
      ;;
    claim|honor-check|audit|claim-audit)
      if [ ! -f "$WM_CLAIM_LIB" ]; then
        echo "⛔ wave-mechanics: no claim library at $WM_CLAIM_LIB (run 'preflight')." >&2
        return 3
      fi
      bash "$WM_CLAIM_LIB" "$verb" "$@"
      ;;
    spawn|land|state-workers|record-status|gate|gate-check|brief-check|pr-check)
      _wm_run_tool wave_worker.py "$verb" "$@"
      ;;
    lease)
      [ -n "${1:-}" ] || { echo "wave-mechanics: lease needs a verb (claim|check|guard|heartbeat|release|state-append)" >&2; return 64; }
      _wm_run_tool wave_owner.py "$@"
      ;;
    help|-h|--help)  wm_usage; return 0 ;;
    *)
      echo "wave-mechanics: unknown verb '$verb'" >&2
      wm_usage
      return 64
      ;;
  esac
}

if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
  wm_main "$@"
  exit $?
fi
