#!/usr/bin/env bash
# Build claim protocol — automatic in-progress claim + dispatch honor-check.
#
# GitHub Issue #188. The problem: parallel dispatched sessions / builds
# double-pick issues because the claim step is *manual* and gets skipped (the
# 2026-06 no-claim dispatch incident — four issues built locally with zero GitHub
# markers). GitHub has no server-side primitive that rejects a second
# claimant, so enforcement lives in OUR dispatch logic: make every claim
# visible in GitHub, and make every dispatch path honor that visibility.
#
# Entry points (sourceable; all gh I/O via ${GH:-gh} so they're mockable):
#
#   build_claim <issue>
#       Apply the `status: in-progress` label and post a structured claim
#       comment carrying branch / worktree / host / ISO-timestamp / optional
#       session + agent id. Idempotent: re-running on an issue this branch
#       already claimed does not repost. Best-effort — NEVER fails its caller
#       (build-init must succeed offline / in tests), so a claim that can't be
#       written degrades to a warning.
#
#   build_honor_check <issue> [my_supervisor]
#       Read the issue's labels + claim comments and decide whether it is
#       already claimed by a DIFFERENT branch. Exits nonzero on
#       claimed-by-other (a skip/warn signal for dispatch points); exits 0 for
#       clear / own-claim / unsentineled (a bare manual label warns, never
#       blocks — pre-protocol issues like #188 itself carry a manual label and
#       must not false-alarm).
#
#       A branch alone cannot tell "another worker of MY wave" from "another
#       wave's supervisor" (#822), and those need opposite responses: the first
#       is the inherited pre-claim every wave worker expects, the second is the
#       #823 P0 — two supervisors dispatching the same issue. So claims carry
#       the owning supervisor and claimed-by-other reports a `relation=`:
#       sibling-worker (same supervisor, exit 3) / foreign-supervisor (a
#       different live supervisor, exit 4 — report and skip, never overwrite) /
#       unknown (pre-#822 claim with no supervisor recorded, exit 3).
#
#   build_claim_audit
#       Fail-loud backstop. Scan sibling worktrees' recent commits for `#N`
#       references and ALARM when an issue carries in-progress commits but no
#       `status: in-progress` label (= the claim protocol was skipped — the
#       exact signal that actually caught that incident). Bounded gh calls so
#       it stays inside the /build Phase 0 budget.
#
# Log prefix: 'build-claim:'

CLAIM_LABEL="status: in-progress"
# Max distinct issues to label-check in an audit pass (keeps Phase 0 < ~5s).
_CLAIM_AUDIT_MAX_ISSUES="${RPW_CLAIM_AUDIT_MAX_ISSUES:-12}"

_gh() { "${GH:-gh}" "$@"; }

_claim_current_branch() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown"
}

_claim_worktree_root() {
  # Prefer the workspace an omnigent session was bound to; fall back to git.
  if [ -n "${OMNIGENT_RUNNER_WORKSPACE:-}" ]; then
    echo "$OMNIGENT_RUNNER_WORKSPACE"
  else
    git rev-parse --show-toplevel 2>/dev/null || echo "unknown"
  fi
}

# _claim_supervisor_id — which wave supervisor session this claim belongs to.
#
# Same ladder as scripts/wave_owner.py's supervisor_id(), kept in sync by
# intent, not import: this file is a standalone plugin script that must run in a
# repo with no Python of ours (#840 is the portability half of that story).
#   1. RPW_WAVE_SUPERVISOR — set by the supervisor; survives every dispatch path
#      because a spawned claim inherits its env.
#   2. the Omnigent session id, recovered from the runner log filename (the same
#      id `sys_session_list` reports), which is stable across a resumed session.
#   3. the harness session id.
#   4. none — an ad-hoc claim outside a wave, which is the common case.
_claim_supervisor_id() {
  if [ -n "${RPW_WAVE_SUPERVISOR:-}" ]; then
    printf '%s' "${RPW_WAVE_SUPERVISOR}" | tr -s '[:space:]' '_'
    return 0
  fi
  local log id
  log="$(basename "${OMNIGENT_PROCESS_LOG_FILE:-}" 2>/dev/null || echo "")"
  id="$(printf '%s' "$log" | sed -nE 's/^runner-([0-9a-f]{16,})-[0-9]{8}-.*$/\1/p')"
  [ -n "$id" ] && { printf '%s' "$id"; return 0; }
  for var in CLAUDE_CODE_SESSION_ID CODEX_SESSION_ID CURSOR_SESSION_ID \
             OPENCODE_SESSION_ID GEMINI_SESSION_ID; do
    eval "id=\${$var:-}"
    [ -n "$id" ] && { printf '%s' "$id" | tr -s '[:space:]' '_'; return 0; }
  done
  printf 'none'
}

# ---------------------------------------------------------------------------
# Pure rendering
# ---------------------------------------------------------------------------

# _claim_sentinel <branch> <worktree> <host> <ts> <workspace> <agent> [supervisor]
# Machine-parseable marker embedded in the claim comment. Each key=value pair
# is space-delimited so a fixed-string `grep -F "branch=$b "` is reliable.
# `supervisor` is appended LAST and defaults to `none`: readers key on
# `branch=` first, and a pre-#822 claim simply has no supervisor field.
_claim_sentinel() {
  printf '<!-- rpw-claim branch=%s worktree=%s host=%s ts=%s workspace=%s agent=%s supervisor=%s -->' \
    "$1" "$2" "$3" "$4" "${5:-none}" "${6:-none}" "${7:-none}"
}

# _claim_comment_body <issue> <branch> <worktree> <host> <ts> <workspace> <agent> [supervisor]
_claim_comment_body() {
  local issue="$1" branch="$2" worktree="$3" host="$4" ts="$5" ws="$6" agent="$7"
  local supervisor="${8:-none}"
  cat <<BODY
🔒 **Claimed for active work** by a \`/build\` session / dispatched agent session.

| field | value |
|-------|-------|
| branch | \`${branch}\` |
| worktree | \`${worktree}\` |
| host | \`${host}\` |
| workspace | \`${ws:-none}\` |
| agent | \`${agent:-none}\` |
| supervisor | \`${supervisor}\` |
| claimed | \`${ts}\` |

A second dispatch that finds this claim should **skip or warn** rather than
double-pick the issue. If this claim is stale (the worktree was abandoned),
clear it with:

\`\`\`
gh issue edit ${issue} --remove-label "${CLAIM_LABEL}"
\`\`\`

$(_claim_sentinel "$branch" "$worktree" "$host" "$ts" "$ws" "$agent" "$supervisor")
BODY
}

# ---------------------------------------------------------------------------
# Pure decision logic
# ---------------------------------------------------------------------------

# _honor_decide <current_branch> [my_supervisor]
#   (reads `gh issue view --json labels,comments` JSON on stdin)
# Prints one of:
#   clear                               (no in-progress label)
#   own-claim branch=<b>                (claimed by this branch)
#   unsentineled                        (label present, no structured claim)
#   claimed-by-other branch=<b> ts=<t> workspace=<w> supervisor=<s> relation=<r>
# Exit 0 for the first three. claimed-by-other exits 3, or 4 when `relation` is
# foreign-supervisor — a different wave's live supervisor already holds this
# issue, which a caller must report and skip rather than overwrite (#822).
_honor_decide() {
  local current_branch="${1:?Usage: _honor_decide <current_branch> [my_supervisor]}"
  local my_supervisor="${2:-}"
  # NOTE: program goes via `-c` (an argv arg) so stdin stays the issue JSON.
  local prog
  prog=$(cat <<'PY'
import json, re, sys
current = sys.argv[1]
mine = (sys.argv[2] if len(sys.argv) > 2 else "").strip() or "none"
try:
    data = json.load(sys.stdin)
except Exception:
    print("clear"); sys.exit(0)

labels = {l.get("name") for l in (data.get("labels") or [])}
if "status: in-progress" not in labels:
    print("clear"); sys.exit(0)

# Find the most recent structured claim sentinel.
claim = None
for c in (data.get("comments") or []):
    body = c.get("body") or ""
    m = re.search(r"<!--\s*rpw-claim\b(.*?)-->", body, re.S)
    if m:
        claim = dict(re.findall(r"(\w+)=(\S+)", m.group(1)))  # keep last (most recent)

if claim is None:
    # Label set manually with no structured claim (pre-protocol). Warn, never
    # block — this is the state of every issue claimed before the protocol.
    print("unsentineled"); sys.exit(0)

b = claim.get("branch", "")
if b == current:
    print(f"own-claim branch={b}"); sys.exit(0)

# Whose claim is it? A branch alone cannot separate the inherited pre-claim a
# wave worker is TOLD to expect from a second wave racing the same issue (#822).
theirs = claim.get("supervisor", "none")
if "none" in (theirs, mine) or "unknown" in (theirs, mine):
    relation, rc = "unknown", 3          # pre-#822 claim, or no wave context
elif theirs == mine:
    relation, rc = "sibling-worker", 3   # my own wave's claim; my brief names it
else:
    relation, rc = "foreign-supervisor", 4

print(f"claimed-by-other branch={b} ts={claim.get('ts','?')} "
      f"workspace={claim.get('workspace','?')} supervisor={theirs} "
      f"relation={relation}")
sys.exit(rc)
PY
)
  python3 -c "$prog" "$current_branch" "$my_supervisor"
}

# _claim_has_branch_sentinel <branch>   (reads issue JSON with comments on stdin)
# Exit 0 if a claim comment for <branch> already exists (idempotency guard).
_claim_has_branch_sentinel() {
  local prog
  prog=$(cat <<'PY'
import json, re, sys
branch = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for c in (data.get("comments") or []):
    body = c.get("body") or ""
    for m in re.finditer(r"<!--\s*rpw-claim\b(.*?)-->", body, re.S):
        if dict(re.findall(r"(\w+)=(\S+)", m.group(1))).get("branch") == branch:
            sys.exit(0)
sys.exit(1)
PY
)
  python3 -c "$prog" "$1"
}

# _audit_issue_status   (reads `gh issue view --json state,labels` JSON on stdin)
# Prints exactly one of: closed | claimed | unclaimed
#   closed    — issue is CLOSED; never a double-pick concern (drops the
#               squash-merge-stale false positive: merged work is closed).
#   claimed   — OPEN and carries the in-progress label.
#   unclaimed — OPEN with no in-progress label (= the skipped-claim alarm).
_audit_issue_status() {
  local prog
  prog=$(cat <<'PY'
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("unclaimed"); sys.exit(0)
if (data.get("state") or "").upper() == "CLOSED":
    print("closed"); sys.exit(0)
labels = {l.get("name") for l in (data.get("labels") or [])}
print("claimed" if "status: in-progress" in labels else "unclaimed")
PY
)
  python3 -c "$prog"
}

# _claim_default_branch — resolve the repo's default branch. Order:
#   1. .rpw/build.yml `default_branch:` (grep, no yaml dep)
#   2. origin/HEAD symbolic ref
#   3. first existing local branch of production / main / master
_claim_default_branch() {
  local root yml from b
  root="$(git rev-parse --show-toplevel 2>/dev/null)"
  yml="$root/.rpw/build.yml"
  if [ -f "$yml" ]; then
    from="$(grep -E '^default_branch:[[:space:]]*' "$yml" 2>/dev/null \
      | sed -E 's/^default_branch:[[:space:]]*//; s/[[:space:]]+$//')"
    [ -n "$from" ] && { echo "$from"; return 0; }
  fi
  from="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
  [ -n "$from" ] && { echo "$from"; return 0; }
  for b in production main master; do
    if git rev-parse --verify --quiet "refs/heads/$b" >/dev/null 2>&1; then
      echo "$b"; return 0
    fi
  done
  echo "production"
}

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

# build_claim <issue> [supervisor] — claim an issue (label + idempotent comment).
# Best-effort: always returns 0 so it can be folded into build-init.
# `supervisor` names the wave supervisor this claim belongs to; omitted, it is
# derived from the environment the claim inherited (_claim_supervisor_id).
build_claim() {
  local issue="${1:-}"
  local supervisor="${2:-}"
  if [ -z "$issue" ]; then
    echo "build-claim: usage: build_claim <issue> [supervisor]" >&2
    return 0
  fi
  [ -n "$supervisor" ] || supervisor="$(_claim_supervisor_id)"

  if ! command -v "${GH:-gh}" >/dev/null 2>&1; then
    echo "build-claim: gh unavailable — skipping claim of #$issue (best-effort)" >&2
    return 0
  fi

  local branch worktree host ts ws agent
  branch="$(_claim_current_branch)"
  worktree="$(_claim_worktree_root)"
  host="$(hostname 2>/dev/null || echo unknown)"
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  # Omnigent injects no session-id env var (ADR-2026-08-14), so a dispatcher
  # that knows the conversation_id passes it in explicitly. NEVER source these
  # from any runner authentication value; those are credentials, not session ids.
  ws="${RPW_SESSION_ID:-none}"
  agent="${RPW_AGENT_ID:-none}"

  # Surface any conflicting claim loudly, but never block (warn-only at claim
  # time — the worktree already exists; prevention happens earlier at dispatch).
  build_honor_check "$issue" "$supervisor" || true

  # Label is idempotent: --add-label on an already-present label is a no-op.
  if ! _gh issue edit "$issue" --add-label "$CLAIM_LABEL" >/dev/null 2>&1; then
    echo "build-claim: could not add '$CLAIM_LABEL' to #$issue (best-effort)" >&2
  fi

  # Idempotent comment: skip if this branch already posted a claim.
  local view
  view="$(_gh issue view "$issue" --json comments 2>/dev/null || echo '{}')"
  if printf '%s' "$view" | _claim_has_branch_sentinel "$branch"; then
    echo "build-claim: #$issue already claimed by branch '$branch' — not reposting"
    return 0
  fi

  local body
  body="$(_claim_comment_body "$issue" "$branch" "$worktree" "$host" "$ts" "$ws" \
    "$agent" "$supervisor")"
  if _gh issue comment "$issue" --body "$body" >/dev/null 2>&1; then
    echo "build-claim: claimed #$issue (label + comment) on branch '$branch'"
  else
    echo "build-claim: labeled #$issue but could not post claim comment (best-effort)" >&2
  fi
  return 0
}

# build_honor_check <issue> [my_supervisor] — dispatch-time check.
# Nonzero on claimed-by-other: 3 normally, 4 for a foreign live supervisor.
build_honor_check() {
  local issue="${1:?Usage: build_honor_check <issue> [my_supervisor]}"
  local my_supervisor="${2:-}"
  [ -n "$my_supervisor" ] || my_supervisor="$(_claim_supervisor_id)"

  if ! command -v "${GH:-gh}" >/dev/null 2>&1; then
    echo "build-claim: honor-check #$issue skipped (gh unavailable)" >&2
    return 0
  fi

  local view verdict rc
  view="$(_gh issue view "$issue" --json labels,comments 2>/dev/null || echo '{}')"
  verdict="$(printf '%s' "$view" | _honor_decide "$(_claim_current_branch)" "$my_supervisor")"
  rc=$?

  echo "build-claim: honor-check #$issue: $verdict"
  case "$verdict" in
    *relation=foreign-supervisor*)
      {
        echo "⛔ build-claim: #$issue is claimed by a DIFFERENT wave's supervisor:"
        echo "     $verdict"
        echo "   Two supervisors on one issue is the #823 P0. Report this claim and"
        echo "   SKIP the issue — never overwrite another supervisor's claim."
      } >&2
      ;;
    *relation=sibling-worker*)
      {
        echo "⚠️  build-claim: #$issue is already claimed by another branch of THIS"
        echo "   wave (same supervisor):"
        echo "     $verdict"
        echo "   Expected for an inherited pre-claim (#568); a surprise otherwise."
      } >&2
      ;;
    claimed-by-other*)
      {
        echo "⛔ build-claim: #$issue is already claimed by another workspace:"
        echo "     $verdict"
        echo "   Skip/warn before dispatching — surface this claim to the user."
      } >&2
      ;;
    unsentineled)
      echo "build-claim: #$issue carries a manual 'status: in-progress' label with no" >&2
      echo "   structured claim comment — proceeding, but verify it isn't another" >&2
      echo "   workspace's work." >&2
      ;;
  esac
  return $rc
}

# build_claim_audit — fail-loud backstop across sibling worktrees.
#
# Scans each OTHER worktree's commits that are AHEAD of the default branch
# (`<default>..HEAD`) for `#N` references and ALARMS on any OPEN issue with no
# in-progress label (= in-flight work that never got claimed).
# Scoping to ahead-of-default is load-bearing: this repo squash-merges with
# `(#N)` in subjects, so a raw `git log` would leak every merged issue from
# shared history and flood Phase 0 with false alarms. CLOSED issues are skipped
# (a merged/closed issue is never a double-pick concern). bash-3.2 safe (no
# associative arrays — macOS `make` runs recipes under /bin/bash 3.2).
build_claim_audit() {
  command -v git >/dev/null 2>&1 || return 0

  local self default
  self="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
  default="$(_claim_default_branch)"

  # rows: one "issue<TAB>branch<TAB>worktree" line per (#N) reference ahead of
  # the default branch in a sibling worktree.
  local rows="" cur_path="" cur_branch="" line
  while IFS= read -r line; do
    case "$line" in
      "worktree "*) cur_path="${line#worktree }" ;;
      "branch "*)   cur_branch="${line#branch refs/heads/}" ;;
      "")  # end of a worktree block
        if [ -n "$cur_path" ] && [ "$cur_path" != "$self" ]; then
          local range="HEAD" nums num
          if [ -n "$default" ] && \
             git -C "$cur_path" rev-parse --verify --quiet "$default" >/dev/null 2>&1; then
            range="$default..HEAD"
          fi
          nums="$(git -C "$cur_path" log --oneline "$range" 2>/dev/null \
                  | grep -oE '#[0-9]+' | tr -d '#' | sort -u)"
          while IFS= read -r num; do
            [ -n "$num" ] || continue
            rows="${rows}${num}	${cur_branch:-detached}	${cur_path}
"
          done <<INNER
$nums
INNER
        fi
        cur_path=""; cur_branch="" ;;
    esac
  done < <(git worktree list --porcelain 2>/dev/null; printf '\n')

  # Dedup by issue (keep first branch/worktree seen).
  rows="$(printf '%s' "$rows" | awk -F'\t' 'NF && !seen[$1]++')"
  [ -n "$rows" ] || { echo "build-claim: audit clean — no in-flight issue references ahead of $default."; return 0; }

  if ! command -v "${GH:-gh}" >/dev/null 2>&1; then
    echo "build-claim: audit found in-flight issue references but gh is unavailable —" >&2
    echo "   cannot verify their claim labels." >&2
    return 0
  fi

  local count
  count="$(printf '%s\n' "$rows" | wc -l | tr -d ' ')"
  if [ "$count" -gt "$_CLAIM_AUDIT_MAX_ISSUES" ]; then
    echo "build-claim: audit checking first $_CLAIM_AUDIT_MAX_ISSUES of $count referenced issues (bounded for Phase 0)" >&2
    rows="$(printf '%s\n' "$rows" | head -n "$_CLAIM_AUDIT_MAX_ISSUES")"
  fi

  local alarms=0 n br wt sv
  while IFS=$'\t' read -r n br wt; do
    [ -n "$n" ] || continue
    sv="$(printf '%s' "$(_gh issue view "$n" --json state,labels 2>/dev/null || echo '{}')" | _audit_issue_status)"
    if [ "$sv" = "unclaimed" ]; then
      alarms=$((alarms + 1))
      {
        echo "⛔ build-claim: CLAIM PROTOCOL SKIPPED for #$n"
        echo "   In-progress commits on branch '$br'"
        echo "   (worktree $wt) reference #$n, but the OPEN issue carries no"
        echo "   '$CLAIM_LABEL' label — this work is invisible to GitHub dispatch."
        echo "   Claim it: gh issue edit $n --add-label \"$CLAIM_LABEL\""
      } >&2
    fi
  done <<EOF
$rows
EOF

  if [ "$alarms" -gt 0 ]; then
    echo "build-claim: audit found $alarms unclaimed in-flight issue(s)." >&2
    return 2
  fi

  echo "build-claim: audit clean — all in-flight worktree commits are claimed."
  return 0
}

# ---------------------------------------------------------------------------
# CLI entry point (#840/#842) — the claim protocol without a Makefile
# ---------------------------------------------------------------------------
#
# Everything above is a sourceable library, and for a long time `make
# build-claim` / `make build-honor-check` were the ONLY way to reach it. Those
# targets live in one repo's Makefile, so a supervisor running a wave anywhere
# else found nothing to call and improvised a bare `status: in-progress` label
# (#840): a read-then-write with no compare-and-swap, which is how two
# supervisors each read "unclaimed" and both dispatched at the same issue on
# 2026-08-05.
#
# So this file is also a program. Executed directly it dispatches verbs; sourced
# it is unchanged, which is what keeps `make build-claim` and every existing
# caller working:
#
#   bash build-claim.sh claim <issue> [supervisor]
#   bash build-claim.sh honor-check <issue> [supervisor]
#   bash build-claim.sh audit
#
# It deliberately needs nothing of ours: bash, git, gh, and the system `python3`
# for the JSON decisions. No `make`, no uv, no venv, no repo layout — it runs in
# a repo that has none of our Python (the portability half of #840). All git/gh
# I/O is relative to the CURRENT working directory, so `( cd <worktree> && bash
# build-claim.sh claim 6 )` stamps that worktree's branch, which is the #568
# ordering the wave protocol depends on.
#
# `honor-check` exits with the library's real codes — 0 dispatchable, 3
# claimed-by-other, 4 foreign-supervisor — because there is no `make` in the
# middle to collapse them to 2 (#1100). Callers may still parse the
# `relation=<r>` token on stdout; that contract is unchanged and remains the one
# that works through `make`.

build_claim_usage() {
  cat >&2 <<'USAGE'
usage: build-claim.sh <verb> [args]

  claim <issue> [supervisor]        apply the in-progress label + claim comment
  honor-check <issue> [supervisor]  is this issue claimed by another branch?
                                    exit 0 dispatchable / 3 claimed-by-other /
                                    4 a different wave's live supervisor
  audit                             alarm on in-flight commits with no claim
  help                              this message

Runs against the git repo of the CURRENT directory. No make, no uv, no venv.
USAGE
}

build_claim_main() {
  local verb="${1:-help}"
  shift 2>/dev/null || true
  case "$verb" in
    claim)
      [ -n "${1:-}" ] || { echo "build-claim: claim needs an issue number" >&2; build_claim_usage; return 64; }
      build_claim "$@"
      ;;
    honor-check|honor_check)
      [ -n "${1:-}" ] || { echo "build-claim: honor-check needs an issue number" >&2; build_claim_usage; return 64; }
      build_honor_check "$@"
      ;;
    audit|claim-audit)
      build_claim_audit
      ;;
    help|-h|--help)
      build_claim_usage; return 0
      ;;
    *)
      echo "build-claim: unknown verb '$verb'" >&2
      build_claim_usage
      return 64
      ;;
  esac
}

# Sourced (`source build-claim.sh`) -> library only, nothing runs.
# Executed (`bash build-claim.sh <verb>`) -> dispatch.
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
  build_claim_main "$@"
  exit $?
fi
