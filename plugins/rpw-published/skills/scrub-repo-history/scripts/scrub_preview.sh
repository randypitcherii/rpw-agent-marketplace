#!/usr/bin/env bash
# scrub_preview.sh — read-only blast-radius preview for a history scrub.
#
# Answers "what would a rewrite actually change?" before anything is rewritten:
# which commits, which blobs (and how big), which branches, which tags, and
# whether the content is still in the working tree.
#
# Read-only. It never writes to the repo, never rewrites, never pushes.
#
# Usage:
#   scrub_preview.sh [--repo DIR] --path <path> [--path <path> ...]
#   scrub_preview.sh [--repo DIR] --pattern <regex> [--pattern <regex> ...]
#   (paths and patterns may be combined)
#
# Exit: 0 preview ran (whether or not anything matched), 64 usage error.

set -euo pipefail

REPO="."
PATHS=()
PATTERNS=()

usage() {
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 64
}

while [ $# -gt 0 ]; do
    case "$1" in
        --repo)    REPO="${2:?--repo needs a directory}"; shift 2 ;;
        --path)    PATHS+=("${2:?--path needs a value}"); shift 2 ;;
        --pattern) PATTERNS+=("${2:?--pattern needs a value}"); shift 2 ;;
        -h|--help) usage ;;
        *) echo "unknown argument: $1" >&2; usage ;;
    esac
done

if [ ${#PATHS[@]} -eq 0 ] && [ ${#PATTERNS[@]} -eq 0 ]; then
    echo "error: give at least one --path or --pattern" >&2
    usage
fi

git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || {
    echo "error: $REPO is not a git repository" >&2
    exit 64
}

g() { git -C "$REPO" "$@"; }

# A --pattern IS the secret: the documented workflow passes the leaked value itself.
# Echoing it back would put it in terminal scrollback, agent transcripts, and any CI log
# capturing this run — re-leaking it into locations the scrub does not reach, and breaking
# this skill's own rule (reference/coordination.md: "the one thing you must not record is
# the scrubbed value itself"). Print a fingerprint that is enough to confirm you passed
# what you meant to, and useless to anyone reading the log.
pattern_fingerprint() {
    local p="$1" digest
    digest=$(printf %s "$p" | shasum -a 256 2>/dev/null | cut -c1-8) || digest="????????"
    printf 'pattern: <%d chars, sha256:%s>\n' "${#p}" "$digest"
}

echo "== scrub preview =="
echo "repo: $(cd "$REPO" && pwd)"
if [ ${#PATHS[@]} -gt 0 ]; then printf 'path: %s\n' "${PATHS[@]}"; fi
if [ ${#PATTERNS[@]} -gt 0 ]; then
    for _p in "${PATTERNS[@]}"; do pattern_fingerprint "$_p"; done
fi
echo

# ---------------------------------------------------------------- commits ----
# --full-history: without it, history simplification hides commits on side
# branches that also carried the content.
commits_file=""
objects_file=""
blobs_file=""
trap 'rm -f "$commits_file" "$objects_file" "$blobs_file" 2>/dev/null || true' EXIT
commits_file=$(mktemp)

if [ ${#PATHS[@]} -gt 0 ]; then
    g log --all --full-history --pretty=%H -- "${PATHS[@]}" >>"$commits_file"
fi
for pattern in ${PATTERNS[@]+"${PATTERNS[@]}"}; do
    # Content search across every reachable commit. Expensive on a large repo,
    # and the honest way to find a secret that moved between files.
    revs=$(g rev-list --all)
    if [ -n "$revs" ]; then
        # shellcheck disable=SC2086
        g grep -I -l -E -e "$pattern" $revs -- 2>/dev/null \
            | sed 's/:.*//' \
            | while read -r rev; do g rev-parse "$rev^{commit}" 2>/dev/null || true; done \
            >>"$commits_file" || true
    fi
done

sort -u "$commits_file" -o "$commits_file"
commit_count=$(wc -l <"$commits_file" | tr -d ' ')

echo "-- affected commits ($commit_count) --"
while read -r sha; do
    [ -n "$sha" ] || continue
    g log -1 --pretty='%h %ad %s' --date=short "$sha"
done <"$commits_file"
echo

# ------------------------------------------------------------------ blobs ----
objects_file=$(mktemp)
blobs_file=$(mktemp)
if [ ${#PATHS[@]} -gt 0 ]; then
    g rev-list --objects --all >"$objects_file"
    for p in "${PATHS[@]}"; do
        # exact file match, or anything under it when the path is a directory
        awk -v p="$p" '
            NF >= 2 {
                name = substr($0, index($0, " ") + 1)
                if (name == p || index(name, p "/") == 1) print $1 " " name
            }' "$objects_file" >>"$blobs_file"
    done
    sort -u "$blobs_file" -o "$blobs_file"
fi

blob_count=$(wc -l <"$blobs_file" | tr -d ' ')
echo "-- affected blobs ($blob_count) --"
while read -r sha name; do
    [ -n "$sha" ] || continue
    size=$(g cat-file -s "$sha" 2>/dev/null || echo '?')
    echo "$sha $size $name"
done <"$blobs_file"
echo

# --------------------------------------------------------- branches, tags ----
branches_out=""
tags_out=""
while read -r sha; do
    [ -n "$sha" ] || continue
    branches_out="$branches_out
$(g branch -a --contains "$sha" --format='%(refname)' 2>/dev/null || true)"
    tags_out="$tags_out
$(g tag --contains "$sha" 2>/dev/null || true)"
done <"$commits_file"

branches=$(printf '%s\n' "$branches_out" | grep -v '^$' | sort -u || true)
tags=$(printf '%s\n' "$tags_out" | grep -v '^$' | sort -u || true)

branch_count=0
tag_count=0
if [ -n "$branches" ]; then branch_count=$(printf '%s\n' "$branches" | wc -l | tr -d ' '); fi
if [ -n "$tags" ]; then tag_count=$(printf '%s\n' "$tags" | wc -l | tr -d ' '); fi

echo "-- affected branches ($branch_count) --"
if [ -n "$branches" ]; then printf '%s\n' "$branches"; fi
echo
echo "-- affected tags ($tag_count) --"
if [ -n "$tags" ]; then printf '%s\n' "$tags"; fi
echo

# ----------------------------------------------------------- working tree ----
echo "-- working tree --"
if [ ${#PATHS[@]} -gt 0 ]; then
    for p in "${PATHS[@]}"; do
        if [ -e "$REPO/$p" ]; then
            echo "present: $p"
        else
            echo "absent: $p"
        fi
    done
else
    echo "(no --path given; not checked)"
fi
echo

# --------------------------------------------------------------- verdict ----
if [ "$commit_count" -eq 0 ] && [ "$blob_count" -eq 0 ]; then
    echo "NOTHING MATCHED — no rewrite needed. Check the path/pattern before proceeding."
    exit 0
fi

cat <<EOF
A rewrite would change $commit_count commit(s), which means $commit_count new SHAs,
a force-push to every affected branch above, and a re-clone for everyone who has this repo.

Before rewriting:
  1. If this is a credential, ROTATE IT FIRST — the rewrite does not revoke anything.
  2. Take a backup: git clone --mirror <repo> <backup-dir>
  3. Get explicit approval naming this repo, these branches, and these paths/patterns.
  4. Force-push only via scrub_force_push.sh, which gates on a second confirmation.
EOF
