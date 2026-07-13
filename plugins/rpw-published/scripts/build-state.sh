#!/usr/bin/env bash
# Build state library — plugin-owned canonical version.
# Sourced by hooks, Makefile, and CLI entrypoints.
#
# Vocabulary (post-#77):
#   receipt  — agent-asserted JSON claim (e.g., "I reviewed for security")
#   artifact — tool-emitted output (e.g., pytest log)
#   phase    — a stage of the build cycle (plan, implement, check, retro, etc.)
#
# Storage layout:
#   .rpw/build/state.json         — coordinator ledger (current cycle metadata)
#   .rpw/build/receipts/<phase>.json
#   .rpw/build.yml                — project-declared gates (check target, etc.)
#
# Artifact storage convention: agents may write tool-emitted artifacts (pytest
# logs, gh CLI output, etc.) wherever they like under the build worktree. The
# library does not manage an artifacts directory — adding one is unfinished
# scaffolding until a real consumer exists.
#
# Coordinator escape hatch:
#   RPW_BUILD_COORDINATOR_DIR=/abs/path  — when set, state lookups resolve
#   against this directory first. Used by subagents that legitimately need to
#   emit a receipt back to the coordinator's ledger.

# Capture this file's own directory at source time. Functions can't rely on
# BASH_SOURCE at call time (it's empty when called from interactive shell).
_RPW_BUILD_STATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

_build_git_root() {
  # Resolve to the CURRENT worktree root, not the main repo.
  git rev-parse --show-toplevel 2>/dev/null || {
    echo "error: not in a git repository" >&2
    return 1
  }
}

_build_root_dir() {
  # Coordinator escape hatch first, then current worktree.
  if [ -n "${RPW_BUILD_COORDINATOR_DIR:-}" ]; then
    echo "$RPW_BUILD_COORDINATOR_DIR"
    return 0
  fi
  _build_git_root
}

_build_state_file() {
  # Test isolation override.
  if [ -n "${BUILD_STATE_FILE:-}" ]; then
    echo "$BUILD_STATE_FILE"
    return 0
  fi
  local root
  root=$(_build_root_dir) || return 1
  echo "$root/.rpw/build/state.json"
}

_build_receipts_dir() {
  if [ -n "${BUILD_RECEIPTS_DIR:-}" ]; then
    echo "$BUILD_RECEIPTS_DIR"
    return 0
  fi
  local root
  root=$(_build_root_dir) || return 1
  echo "$root/.rpw/build/receipts"
}

_build_yml_file() {
  local root
  root=$(_build_root_dir) || return 1
  echo "$root/.rpw/build.yml"
}

_build_skill_version() {
  # Read version from the rpw-published plugin manifest. Best-effort.
  local manifest="${_RPW_BUILD_STATE_DIR}/../.claude-plugin/plugin.json"
  if [ -f "$manifest" ]; then
    python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('version','unknown'))" "$manifest" 2>/dev/null || echo "unknown"
  else
    echo "unknown"
  fi
}

# ---------------------------------------------------------------------------
# State (ledger) operations
# ---------------------------------------------------------------------------

build_state_init() {
  local issue_id="${1:?Usage: build_state_init <issue-number> [feature-branch]}"
  local feature_branch="${2:-}"
  local state_file
  state_file=$(_build_state_file) || return 1

  if [ -f "$state_file" ]; then
    local existing_issue
    existing_issue=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1])).get('issue_id','unknown'))" "$state_file" 2>/dev/null || echo "unknown")
    echo "error: active build already exists (issue: $existing_issue). Run build_state_clear first." >&2
    return 1
  fi

  if [ -z "$feature_branch" ]; then
    feature_branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")
  fi

  mkdir -p "$(dirname "$state_file")"
  python3 -c "
import json, datetime, sys
state = {
    'issue_id': sys.argv[1],
    'phases': {},
    'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'feature_branch': sys.argv[3] or None,
    'skill_version': sys.argv[4],
}
if not state['feature_branch']:
    del state['feature_branch']
with open(sys.argv[2], 'w') as f:
    json.dump(state, f, indent=2)
" "$issue_id" "$state_file" "$feature_branch" "$(_build_skill_version)"
  echo "build-state: initialized for issue $issue_id"
}

build_phase_set() {
  local phase="${1:?Usage: build_phase_set <phase>}"
  local state_file
  state_file=$(_build_state_file) || return 1

  if [ ! -f "$state_file" ]; then
    echo "error: no active build state. Run build_state_init first." >&2
    return 1
  fi

  python3 -c "
import json, datetime, sys
sf, p = sys.argv[1], sys.argv[2]
with open(sf, 'r') as f:
    state = json.load(f)
if p not in state['phases']:
    state['phases'][p] = {
        'set_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    with open(sf, 'w') as f:
        json.dump(state, f, indent=2)
print(f'build-state: {state[\"issue_id\"]} phase {p} set')
" "$state_file" "$phase"
}

build_phase_get() {
  local state_file
  state_file=$(_build_state_file) || return 1

  if [ ! -f "$state_file" ]; then
    echo "error: no active build state." >&2
    return 1
  fi

  if [ $# -eq 0 ]; then
    python3 -c "import json, sys; print(json.dumps(json.load(open(sys.argv[1])), indent=2))" "$state_file"
  else
    local phase="$1"
    python3 -c "
import json, sys
state = json.load(open(sys.argv[1]))
sys.exit(0 if sys.argv[2] in state['phases'] else 1)
" "$state_file" "$phase"
  fi
}

build_phase_require() {
  local phase="${1:?Usage: build_phase_require <phase>}"
  local state_file
  state_file=$(_build_state_file) || return 1

  if [ ! -f "$state_file" ]; then
    echo "error: no active build state. Cannot require '$phase'." >&2
    return 1
  fi

  python3 -c "
import json, sys
state = json.load(open(sys.argv[1]))
p = sys.argv[2]
if p not in state['phases']:
    done = list(state['phases'].keys()) or ['none']
    print(f'error: phase {p!r} not set. Completed: {\", \".join(done)}', file=sys.stderr)
    sys.exit(1)
" "$state_file" "$phase"
}

# ---------------------------------------------------------------------------
# Receipt operations (shell-safe)
# ---------------------------------------------------------------------------

# build_receipt_save <phase> [json-string]
# If json-string is omitted or "-", read JSON from stdin (heredoc safe).
# Stamps the receipt with skill_version and saved_at.
build_receipt_save() {
  local phase="${1:?Usage: build_receipt_save <phase> [<json>|-]}"
  local payload
  if [ $# -lt 2 ] || [ "$2" = "-" ]; then
    payload=$(cat)
  else
    payload="$2"
  fi

  local receipts_dir
  receipts_dir=$(_build_receipts_dir) || return 1

  # Validate + stamp via python (preserves arbitrary characters safely).
  local stamped
  stamped=$(python3 -c "
import json, sys, datetime
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except json.JSONDecodeError as e:
    print(f'error: receipt payload is not valid JSON: {e}', file=sys.stderr)
    sys.exit(1)
if not isinstance(data, dict):
    print('error: receipt payload must be a JSON object', file=sys.stderr)
    sys.exit(1)
data.setdefault('_skill_version', sys.argv[1])
data.setdefault('_saved_at', datetime.datetime.now(datetime.timezone.utc).isoformat())
print(json.dumps(data, indent=2))
" "$(_build_skill_version)" <<< "$payload") || return 1

  mkdir -p "$receipts_dir"
  printf '%s\n' "$stamped" > "$receipts_dir/$phase.json"
  echo "build-receipt: saved $phase.json"
}

# build_receipts_check — fail if any of the canonical 6 receipts are missing.
build_receipts_check() {
  local receipts_dir
  receipts_dir=$(_build_receipts_dir) || return 1
  local missing=()
  for phase in check security-review simplification human-validation docs-review retro; do
    if [ ! -s "$receipts_dir/$phase.json" ]; then
      missing+=("$phase")
    fi
  done
  if [ ${#missing[@]} -gt 0 ]; then
    echo "missing: ${missing[*]}" >&2
    return 1
  fi
  return 0
}

build_receipts_clear() {
  local receipts_dir
  receipts_dir=$(_build_receipts_dir) || return 1
  rm -rf "$receipts_dir"
  echo "build-receipts: cleared"
}

# ---------------------------------------------------------------------------
# build.yml — project gate declaration
# ---------------------------------------------------------------------------

# build_yml_check_target — print the configured check target ('check' default).
# Fail-open: prints 'check' if .rpw/build.yml missing or unparseable.
build_yml_check_target() {
  local yml
  yml=$(_build_yml_file) || { echo "check"; return 0; }
  if [ ! -f "$yml" ]; then
    echo "check"
    return 0
  fi
  python3 -c "
import sys
try:
    import yaml
except ImportError:
    print('check')
    sys.exit(0)
try:
    data = yaml.safe_load(open(sys.argv[1])) or {}
except Exception:
    print('check')
    sys.exit(0)
gates = data.get('gates') or {}
print(gates.get('check') or 'check')
" "$yml"
}

# build_yml_bootstrap — write a sensible default .rpw/build.yml if missing.
build_yml_bootstrap() {
  local yml
  yml=$(_build_yml_file) || return 1
  if [ -f "$yml" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$yml")"
  # Detect a likely gate target by inspecting the project's Makefile.
  local detected="check"
  if [ -f "Makefile" ]; then
    if grep -qE "^check:" Makefile; then
      detected="check"
    elif grep -qE "^verify:" Makefile; then
      detected="verify"
    elif grep -qE "^test:" Makefile; then
      detected="test"
    fi
  fi
  cat > "$yml" <<YML
# rpw-agent-marketplace / rpw-published build config.
# Declares the project's verification gate target for the /build skill.
gates:
  check: $detected
YML
  echo "build-state: scaffolded $yml (gate target: $detected)"
}

# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------

build_state_clear() {
  local state_file
  state_file=$(_build_state_file) || return 1

  if [ -f "$state_file" ]; then
    local issue_id
    issue_id=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1])).get('issue_id','unknown'))" "$state_file" 2>/dev/null || echo "unknown")
    rm -f "$state_file"
    build_receipts_clear 2>/dev/null || true
    echo "build-state: cleared (was issue $issue_id)"
  else
    echo "build-state: no active state to clear"
  fi
}

# ---------------------------------------------------------------------------
# Worktree cleanup (post-Build-Worker)
# ---------------------------------------------------------------------------

# build_worker_cleanup <worktree_path> [branch]
#
# Unlocks and removes a Build Worker worktree left locked by the agent harness,
# then optionally deletes the task branch and prunes dangling worktree state.
# Safe to re-run — all steps are idempotent.
#
# The agent harness marks worktrees locked with reason "claude agent agent-<id>
# (pid N)". git worktree remove --force fails on locked worktrees; this helper
# performs unlock first, falling back to double-force if needed (issue #126).
build_worker_cleanup() {
  local worktree_path="${1:-}"
  local branch="${2:-}"

  if [ -z "$worktree_path" ]; then
    echo "Usage: build_worker_cleanup <worktree_path> [branch]" >&2
    return 2
  fi

  # Normalize to absolute path for reliable porcelain matching.
  worktree_path="$(cd "$worktree_path" 2>/dev/null && pwd || echo "$worktree_path")"

  # Check whether the path is a known worktree.
  local _is_worktree=0
  if git worktree list --porcelain 2>/dev/null | grep -q "^worktree $worktree_path$"; then
    _is_worktree=1
  fi

  if [ "$_is_worktree" -eq 0 ]; then
    echo "worktree-cleanup: warning: '$worktree_path' is not a registered worktree — skipping unlock/remove" >&2
  else
    # Unlock — safe to ignore "not locked" errors.
    git worktree unlock "$worktree_path" 2>/dev/null || true

    # Remove — try single-force first, fall back to double-force.
    if ! git worktree remove --force "$worktree_path" 2>/dev/null; then
      echo "worktree-cleanup: single --force failed; escalating to double --force for '$worktree_path'" >&2
      git worktree remove --force --force "$worktree_path"
    fi
  fi

  # Branch delete (optional).
  local _branch_deleted=0
  if [ -n "$branch" ]; then
    if git show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
      git branch -D "$branch"
      _branch_deleted=1
    else
      echo "worktree-cleanup: warning: branch '$branch' not found — skipping delete" >&2
    fi
  fi

  # Prune dangling administrative state.
  git worktree prune

  # Summary line.
  local _summary="worktree-cleanup: removed $worktree_path"
  if [ "$_branch_deleted" -eq 1 ]; then
    _summary="$_summary, deleted branch $branch"
  fi
  echo "$_summary"
}
