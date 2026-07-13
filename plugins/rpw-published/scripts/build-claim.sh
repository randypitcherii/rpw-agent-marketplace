#!/usr/bin/env bash
# Build claim protocol — automatic in-progress claim + dispatch honor-check.
#
# GitHub Issue #188. The problem: parallel Superset workspaces / builds
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
#       comment carrying branch / worktree / host / ISO-timestamp / Superset
#       workspace id / agent. Idempotent: re-running on an issue this branch
#       already claimed does not repost. Best-effort — NEVER fails its caller
#       (build-init must succeed offline / in tests), so a claim that can't be
#       written degrades to a warning.
#
#   build_honor_check <issue>
#       Read the issue's labels + claim comments and decide whether it is
#       already claimed by a DIFFERENT branch. Exits nonzero on
#       claimed-by-other (a skip/warn signal for dispatch points); exits 0 for
#       clear / own-claim / unsentineled (a bare manual label warns, never
#       blocks — pre-protocol issues like #188 itself carry a manual label and
#       must not false-alarm).
#
#   build_claim_audit
#       Fail-loud backstop. Scan sibling worktrees' recent commits for `#N`
#       references and ALARM when an issue carries in-progress commits but no
#       `status: in-progress` label (= the claim protocol was skipped — the
#       exact signal that actually caught that incident). Best-effort
#       Superset cross-ref when the CLI is present. Bounded gh calls so it
#       stays inside the /build Phase 0 budget.
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
  # Prefer the Superset-provided path; fall back to git.
  if [ -n "${SUPERSET_WORKSPACE_PATH:-}" ]; then
    echo "$SUPERSET_WORKSPACE_PATH"
  else
    git rev-parse --show-toplevel 2>/dev/null || echo "unknown"
  fi
}

# ---------------------------------------------------------------------------
# Pure rendering
# ---------------------------------------------------------------------------

# _claim_sentinel <branch> <worktree> <host> <ts> <workspace> <agent>
# Machine-parseable marker embedded in the claim comment. Each key=value pair
# is space-delimited so a fixed-string `grep -F "branch=$b "` is reliable.
_claim_sentinel() {
  printf '<!-- rpw-claim branch=%s worktree=%s host=%s ts=%s workspace=%s agent=%s -->' \
    "$1" "$2" "$3" "$4" "${5:-none}" "${6:-none}"
}

# _claim_comment_body <issue> <branch> <worktree> <host> <ts> <workspace> <agent>
_claim_comment_body() {
  local issue="$1" branch="$2" worktree="$3" host="$4" ts="$5" ws="$6" agent="$7"
  cat <<BODY
🔒 **Claimed for active work** by a \`/build\` session / Superset workspace.

| field | value |
|-------|-------|
| branch | \`${branch}\` |
| worktree | \`${worktree}\` |
| host | \`${host}\` |
| workspace | \`${ws:-none}\` |
| agent | \`${agent:-none}\` |
| claimed | \`${ts}\` |

A second dispatch that finds this claim should **skip or warn** rather than
double-pick the issue. If this claim is stale (the workspace was abandoned),
clear it with:

\`\`\`
gh issue edit ${issue} --remove-label "${CLAIM_LABEL}"
\`\`\`

$(_claim_sentinel "$branch" "$worktree" "$host" "$ts" "$ws" "$agent")
BODY
}

# ---------------------------------------------------------------------------
# Pure decision logic
# ---------------------------------------------------------------------------

# _honor_decide <current_branch>   (reads `gh issue view --json labels,comments`
# JSON on stdin)
# Prints one of:
#   clear                               (no in-progress label)
#   own-claim branch=<b>                (claimed by this branch)
#   unsentineled                        (label present, no structured claim)
#   claimed-by-other branch=<b> ts=<t> workspace=<w>
# Exit 0 for the first three; nonzero (3) for claimed-by-other.
_honor_decide() {
  local current_branch="${1:?Usage: _honor_decide <current_branch>}"
  # NOTE: program goes via `-c` (an argv arg) so stdin stays the issue JSON.
  local prog
  prog=$(cat <<'PY'
import json, re, sys
current = sys.argv[1]
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

print(f"claimed-by-other branch={b} ts={claim.get('ts','?')} "
      f"workspace={claim.get('workspace','?')}")
sys.exit(3)
PY
)
  python3 -c "$prog" "$current_branch"
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

# build_claim <issue> — claim an issue (label + idempotent comment).
# Best-effort: always returns 0 so it can be folded into build-init.
build_claim() {
  local issue="${1:-}"
  if [ -z "$issue" ]; then
    echo "build-claim: usage: build_claim <issue>" >&2
    return 0
  fi

  if ! command -v "${GH:-gh}" >/dev/null 2>&1; then
    echo "build-claim: gh unavailable — skipping claim of #$issue (best-effort)" >&2
    return 0
  fi

  local branch worktree host ts ws agent
  branch="$(_claim_current_branch)"
  worktree="$(_claim_worktree_root)"
  host="$(hostname 2>/dev/null || echo unknown)"
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  ws="${SUPERSET_WORKSPACE_ID:-none}"
  agent="${SUPERSET_AGENT_ID:-none}"

  # Surface any conflicting claim loudly, but never block (warn-only at claim
  # time — the worktree already exists; prevention happens earlier at dispatch).
  build_honor_check "$issue" || true

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
  body="$(_claim_comment_body "$issue" "$branch" "$worktree" "$host" "$ts" "$ws" "$agent")"
  if _gh issue comment "$issue" --body "$body" >/dev/null 2>&1; then
    echo "build-claim: claimed #$issue (label + comment) on branch '$branch'"
  else
    echo "build-claim: labeled #$issue but could not post claim comment (best-effort)" >&2
  fi
  return 0
}

# build_honor_check <issue> — dispatch-time check. Nonzero on claimed-by-other.
build_honor_check() {
  local issue="${1:?Usage: build_honor_check <issue>}"

  if ! command -v "${GH:-gh}" >/dev/null 2>&1; then
    echo "build-claim: honor-check #$issue skipped (gh unavailable)" >&2
    return 0
  fi

  local view verdict rc
  view="$(_gh issue view "$issue" --json labels,comments 2>/dev/null || echo '{}')"
  verdict="$(printf '%s' "$view" | _honor_decide "$(_claim_current_branch)")"
  rc=$?

  echo "build-claim: honor-check #$issue: $verdict"
  case "$verdict" in
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
