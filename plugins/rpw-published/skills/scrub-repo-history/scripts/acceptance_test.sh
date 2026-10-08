#!/usr/bin/env bash
# acceptance_test.sh — end-to-end check of the scrub-repo-history skill.
#
# Builds its OWN disposable repository in a temp directory and rewrites that.
# It never touches the repo you are working in, and never talks to a real remote
# (the "remote" is a local bare repo). Safe to run anywhere.
#
# The fixture is deliberately awkward: a secret-bearing file touched by several
# commits, living on two branches, with an annotated tag on an affected commit,
# and a working-tree deletion that (as expected) leaves the content in history.
#
# Checks:
#   1. the preview names exactly the affected commits, blobs, branches and tags
#   2. the preview does NOT name unaffected commits
#   3. after the rewrite the path is gone from --all, by path AND by content
#   4. unaffected history survives
#   5. the tag survives, remapped to a rewritten commit (the documented default)
#   6. the force-push gate refuses without confirmation, with the wrong phrase,
#      and with a missing backup — and pushes nothing in those cases
#   7. the gate pushes once the correct phrase is given
#
# Usage: acceptance_test.sh          Exit: 0 all checks passed, 1 otherwise.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PREVIEW="$HERE/scrub_preview.sh"
FORCE_PUSH="$HERE/scrub_force_push.sh"
SECRET_PATH="secrets/deploy.key"
# Deliberately inert: a realistic-looking credential would trip the secret
# scanners this repo (and any sane repo) runs on commit.
SECRET_VALUE="PLACEHOLDER-NOT-A-REAL-CREDENTIAL"

PASS=0
FAIL=0

ok()   { PASS=$((PASS + 1)); echo "  ok   — $1"; }
bad()  { FAIL=$((FAIL + 1)); echo "  FAIL — $1"; }
check() { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3 (expected '$2', got '$1')"; fi; }
contains() { if printf '%s' "$1" | grep -qF -- "$2"; then ok "$3"; else bad "$3 (missing '$2')"; fi; }
lacks() { if printf '%s' "$1" | grep -qF -- "$2"; then bad "$3 (unexpectedly found '$2')"; else ok "$3"; fi; }

# git-filter-repo is frequently not installed; uvx runs it without one.
if git filter-repo --version >/dev/null 2>&1; then
    filter_repo() { git -C "$1" filter-repo "${@:2}"; }
    echo "using: installed git-filter-repo"
elif command -v uvx >/dev/null 2>&1; then
    filter_repo() { (cd "$1" && uvx --from git-filter-repo git-filter-repo "${@:2}"); }
    echo "using: uvx --from git-filter-repo (not installed locally)"
else
    echo "SKIP: neither git-filter-repo nor uvx is available" >&2
    exit 1
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/scrub-acceptance.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
echo "workspace: $WORK"

# ------------------------------------------------------------- the fixture ---
FIXTURE="$WORK/fixture"
NO_HOOKS="$WORK/no-hooks"
mkdir -p "$FIXTURE" "$NO_HOOKS"
git -C "$FIXTURE" init -q
git -C "$FIXTURE" symbolic-ref HEAD refs/heads/main
git -C "$FIXTURE" config user.name "Scrub Acceptance"
git -C "$FIXTURE" config user.email "scrub@example.invalid"
git -C "$FIXTURE" config commit.gpgsign false
# Local core.hooksPath overrides a global one. Without this, a machine-wide
# pre-commit secret scanner silently rejects the fixture commits and every
# later assertion fails for the wrong reason.
git -C "$FIXTURE" config core.hooksPath "$NO_HOOKS"

fixture_commit() {
    git -C "$FIXTURE" add -A
    if ! git -C "$FIXTURE" commit -q --no-verify -m "$1"; then
        echo "FATAL: fixture commit failed: $1" >&2
        exit 1
    fi
}

echo "readme" >"$FIXTURE/README.md"
fixture_commit "c1: readme"
C1=$(git -C "$FIXTURE" rev-parse HEAD)

mkdir -p "$FIXTURE/secrets"
echo "key = $SECRET_VALUE" >"$FIXTURE/$SECRET_PATH"
fixture_commit "c2: add deploy key"
C2=$(git -C "$FIXTURE" rev-parse HEAD)

echo "key = $SECRET_VALUE  # rotated-but-not-really" >"$FIXTURE/$SECRET_PATH"
fixture_commit "c3: touch deploy key"
C3=$(git -C "$FIXTURE" rev-parse HEAD)
git -C "$FIXTURE" tag -a v1.0 -m "release 1.0" "$C3"

# a side branch that also carries the secret
git -C "$FIXTURE" checkout -q -b feature "$C3"
echo "key = $SECRET_VALUE  # feature branch copy" >"$FIXTURE/$SECRET_PATH"
fixture_commit "c4: feature touches deploy key"
C4=$(git -C "$FIXTURE" rev-parse HEAD)
mkdir -p "$FIXTURE/src"
echo "def feature(): pass" >"$FIXTURE/src/feature.py"
fixture_commit "c5: feature code"
C5=$(git -C "$FIXTURE" rev-parse HEAD)

git -C "$FIXTURE" checkout -q main
mkdir -p "$FIXTURE/src"
echo "def app(): pass" >"$FIXTURE/src/app.py"
fixture_commit "c6: app code"
C6=$(git -C "$FIXTURE" rev-parse HEAD)

# the mistake this skill exists for: deleted from the working tree only
git -C "$FIXTURE" rm -q "$FIXTURE/$SECRET_PATH" 2>/dev/null || git -C "$FIXTURE" rm -q "$SECRET_PATH"
fixture_commit "c7: delete deploy key from the working tree"
C7=$(git -C "$FIXTURE" rev-parse HEAD)

echo
echo "== 1. preview =="
PREVIEW_OUT=$("$PREVIEW" --repo "$FIXTURE" --path "$SECRET_PATH" 2>&1) || true
echo "$PREVIEW_OUT" | sed 's/^/    | /'

contains "$PREVIEW_OUT" "affected commits (4)" "preview counts the 4 commits that touched the path"
for sha in "$C2" "$C3" "$C4" "$C7"; do
    contains "$PREVIEW_OUT" "$(git -C "$FIXTURE" rev-parse --short "$sha")" "preview names affected commit ${sha:0:7}"
done
for sha in "$C1" "$C5" "$C6"; do
    lacks "$PREVIEW_OUT" "$(git -C "$FIXTURE" rev-parse --short "$sha")" "preview omits unaffected commit ${sha:0:7}"
done
contains "$PREVIEW_OUT" "affected blobs (3)" "preview counts the 3 distinct blob versions"
contains "$PREVIEW_OUT" "refs/heads/main" "preview names the main branch"
contains "$PREVIEW_OUT" "refs/heads/feature" "preview names the feature branch"
contains "$PREVIEW_OUT" "v1.0" "preview names the affected tag"
contains "$PREVIEW_OUT" "absent: $SECRET_PATH" "preview reports the working-tree deletion"

# Content mode finds the secret by value, not by path: every commit whose TREE
# still carries it (so c7, which deleted it, is correctly absent).
PATTERN_OUT=$("$PREVIEW" --repo "$FIXTURE" --pattern "$SECRET_VALUE" 2>&1) || true
contains "$PATTERN_OUT" "affected commits (5)" "content search counts the 5 commits whose tree holds the secret"
contains "$PATTERN_OUT" "$(git -C "$FIXTURE" rev-parse --short "$C2")" "content search names the commit that added it"
lacks "$PATTERN_OUT" "$(git -C "$FIXTURE" rev-parse --short "$C7")" "content search omits the commit that deleted it"
lacks "$PATTERN_OUT" "$(git -C "$FIXTURE" rev-parse --short "$C1")" "content search omits history before the secret existed"

# a path that was never committed must produce a clean no-op verdict
NOOP_OUT=$("$PREVIEW" --repo "$FIXTURE" --path "does/not/exist" 2>&1) || true
contains "$NOOP_OUT" "NOTHING MATCHED" "preview reports a no-op for an unmatched path"

echo
echo "== 2. backup + rewrite =="
BACKUP="$WORK/backup.git"
WORKING="$WORK/working.git"
git clone -q --mirror "$FIXTURE" "$BACKUP"
git clone -q --mirror "$FIXTURE" "$WORKING"
backup_commits=$(git -C "$BACKUP" rev-list --all --count)
if [ "$backup_commits" -ge 7 ]; then ok "backup mirror holds all $backup_commits commits"; else bad "backup mirror is short ($backup_commits commits)"; fi

TAG_BEFORE=$(git -C "$WORKING" rev-parse v1.0^{commit})
filter_repo "$WORKING" --path "$SECRET_PATH" --invert-paths >/dev/null 2>&1 \
    && ok "filter-repo rewrite completed" \
    || bad "filter-repo rewrite failed"

echo
echo "== 3. verification =="
LOG_AFTER=$(git -C "$WORKING" log --all --full-history --oneline -- "$SECRET_PATH" 2>/dev/null)
check "$(printf '%s' "$LOG_AFTER" | wc -c | tr -d ' ')" "0" "git log --all -- path is empty"

OBJ_AFTER=$(git -C "$WORKING" rev-list --objects --all | grep -F "$SECRET_PATH" || true)
check "$(printf '%s' "$OBJ_AFTER" | wc -c | tr -d ' ')" "0" "no object in --all still carries the path"

REVS=$(git -C "$WORKING" rev-list --all)
# shellcheck disable=SC2086
GREP_AFTER=$(git -C "$WORKING" grep -I -l -F "$SECRET_VALUE" $REVS -- 2>/dev/null || true)
check "$(printf '%s' "$GREP_AFTER" | wc -c | tr -d ' ')" "0" "the secret value is gone from every reachable blob"

README_LOG=$(git -C "$WORKING" log --all --oneline -- README.md)
if [ -n "$README_LOG" ]; then ok "unaffected history survives (README.md)"; else bad "README.md history was lost"; fi
APP_LOG=$(git -C "$WORKING" log --all --oneline -- src/app.py)
if [ -n "$APP_LOG" ]; then ok "unaffected history survives (src/app.py)"; else bad "src/app.py history was lost"; fi
FEATURE_LOG=$(git -C "$WORKING" log --all --oneline -- src/feature.py)
if [ -n "$FEATURE_LOG" ]; then ok "side-branch history survives (src/feature.py)"; else bad "src/feature.py history was lost"; fi
BRANCHES_AFTER=$(git -C "$WORKING" for-each-ref --format='%(refname)' refs/heads)
contains "$BRANCHES_AFTER" "refs/heads/main" "main survives the rewrite"
contains "$BRANCHES_AFTER" "refs/heads/feature" "feature survives the rewrite"

# Tag decision: tags are rewritten, never left pointing at pre-rewrite history.
if git -C "$WORKING" rev-parse -q --verify v1.0 >/dev/null; then
    ok "tag v1.0 still exists after the rewrite"
    TAG_AFTER=$(git -C "$WORKING" rev-parse v1.0^{commit})
    if [ "$TAG_AFTER" != "$TAG_BEFORE" ]; then
        ok "tag v1.0 was remapped off its pre-rewrite commit"
    else
        bad "tag v1.0 still points at pre-rewrite commit $TAG_BEFORE — the secret stays reachable"
    fi
    if git -C "$WORKING" cat-file -e "$TAG_AFTER^{commit}" 2>/dev/null; then
        ok "the remapped tag points at a real commit"
    else
        bad "the remapped tag does not resolve"
    fi
else
    bad "tag v1.0 disappeared"
fi

echo
echo "== 4. the force-push gate =="
REMOTE="$WORK/remote.git"
git init -q --bare "$REMOTE"
git -C "$WORKING" remote add origin "$REMOTE" 2>/dev/null || git -C "$WORKING" remote set-url origin "$REMOTE"

remote_refs() { git -C "$REMOTE" for-each-ref --format='%(refname)' | wc -l | tr -d ' '; }

"$FORCE_PUSH" --repo "$WORKING" --remote origin --branch main --backup "$BACKUP" >/dev/null 2>&1
check "$?" "2" "refuses to push with no --confirm"
check "$(remote_refs)" "0" "nothing was pushed without confirmation"

"$FORCE_PUSH" --repo "$WORKING" --remote origin --branch main --backup "$BACKUP" \
    --confirm "yes do it" >/dev/null 2>&1
check "$?" "2" "refuses to push on a mismatched confirmation phrase"
check "$(remote_refs)" "0" "nothing was pushed on a wrong phrase"

"$FORCE_PUSH" --repo "$WORKING" --remote origin --branch main --backup "$WORK/no-such-backup" \
    --confirm "force-push origin/main — rewritten history, irreversible, everyone re-clones" \
    >/dev/null 2>&1
check "$?" "3" "refuses to push when the backup is missing"
check "$(remote_refs)" "0" "nothing was pushed without a backup"

"$FORCE_PUSH" --repo "$WORKING" --remote origin --branch main --backup "$BACKUP" --dry-run \
    --confirm "force-push origin/main — rewritten history, irreversible, everyone re-clones" \
    >/dev/null 2>&1
check "$?" "0" "--dry-run passes the gate"
check "$(remote_refs)" "0" "--dry-run pushes nothing"

"$FORCE_PUSH" --repo "$WORKING" --remote origin --branch main --backup "$BACKUP" --tags \
    --confirm "force-push origin/main — rewritten history, irreversible, everyone re-clones" \
    >/dev/null 2>&1
check "$?" "0" "pushes once the exact confirmation phrase is given"
if git -C "$REMOTE" rev-parse -q --verify refs/heads/main >/dev/null; then
    ok "the rewritten branch landed on the remote"
else
    bad "the rewritten branch is not on the remote"
fi
REMOTE_LOG=$(git -C "$REMOTE" log --all --full-history --oneline -- "$SECRET_PATH" 2>/dev/null)
check "$(printf '%s' "$REMOTE_LOG" | wc -c | tr -d ' ')" "0" "the remote's history is scrubbed too"

echo
echo "== result: $PASS passed, $FAIL failed =="
[ "$FAIL" -eq 0 ]
