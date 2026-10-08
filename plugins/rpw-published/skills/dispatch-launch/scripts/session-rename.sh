#!/usr/bin/env bash
# One-step manual rename of an omnigent session (#1613).
#
#   session-rename.sh <session-id> <new title...>
#   session-rename.sh --list
#
# Renames through `PATCH /v1/sessions/{id}`, which is the *manual* rename route.
# It is not the route `sys_session_rename` uses (that one is the automatic
# titler, `POST /v1/sessions/{id}/auto-title`) and it does not share its limits:
#
#   PATCH /v1/sessions/{id}   title cap 200, no seed-title precondition
#   POST  .../auto-title      title cap 100 server-side (60 in the MCP tool
#                             schema), and refuses unless the current title is
#                             still the deterministic first-message title
#
# The server also stores "/" as a space in any title (create and rename alike),
# so a branch segment is normalized here before sending — otherwise every
# structured title read back as a mismatch.
#
# Measured 2026-09-16 against the managed server — see session-lifecycle.md.
set -euo pipefail

# The cap the manual rename route enforces (422 `string_too_long` beyond it).
TITLE_MAX=200
TITLE_MIN=2

usage() {
  cat >&2 <<'USAGE'
usage: session-rename.sh <session-id> <new title...>
       session-rename.sh --list

  <session-id>   omnigent conversation id (see --list)
  <new title>    remaining args are joined with spaces; quoting is optional

env:
  OMNIGENT_API_BASE          override the API base URL
  RUNNER_SERVER_URL          managed-server base, injected in omnigent sessions
  OMNIGENT_API_TOKEN         bearer token; otherwise `databricks auth token`
  OMNIGENT_PROFILE           databricks profile (default: host's first DNS label)
  OMNIGENT_RUNNER_SLICE_KEY  host id for the shard header, injected in sessions
USAGE
  exit 2
}

# Base URL, auth and `api` are shared with the other session scripts.
# shellcheck source=SCRIPTDIR/omni-api.sh
source "$(dirname "${BASH_SOURCE[0]}")/omni-api.sh"

# --- --list -----------------------------------------------------------------
if [[ "${1:-}" == "--list" ]]; then
  out="$(api GET /v1/sessions)"
  code="${out##*$'\n'}"; payload="${out%$'\n'*}"
  [[ "$code" == 2* ]] || die "GET /v1/sessions -> HTTP $code: $payload" 4
  printf '%s' "$payload" | python3 -c '
import json, sys
data = json.load(sys.stdin)
rows = data["data"] if isinstance(data, dict) else data
for s in rows:
    print("{:<20} {:<10} {}".format(
        s.get("id"), str(s.get("status")), s.get("title") or "(untitled)"))
'
  exit 0
fi

[[ $# -ge 2 ]] || usage
SID="$1"; shift
TITLE="$*"

# --- title checks -----------------------------------------------------------
# The server collapses nothing but does strip trailing whitespace, so strip it
# here too — otherwise the read-back looks like a mismatch.
TITLE="${TITLE%"${TITLE##*[![:space:]]}"}"
[[ ${#TITLE} -ge $TITLE_MIN ]] || die "title must be at least $TITLE_MIN characters" 2


if (( ${#TITLE} > TITLE_MAX )); then
  dropped="${TITLE:$TITLE_MAX}"
  TITLE="${TITLE:0:$TITLE_MAX}"
  TITLE="${TITLE%"${TITLE##*[![:space:]]}"}"
  printf '⚠️  title truncated to the %d-char rename cap (dropped %d chars: "%s")\n' \
    "$TITLE_MAX" "${#dropped}" "$dropped" >&2
  printf '    the kept prefix is the leading segments, so repo::branch survives\n' >&2
fi
# The server stores "/" as a space, so a branch segment never round-trips
# verbatim. Substitute up front and say so, rather than reporting a mismatch
# the caller cannot act on.
if [[ "$TITLE" == */* ]]; then
  TITLE="${TITLE//\// }"
  printf 'note: "/" is stored as a space by the server; sending "%s"\n' "$TITLE" >&2
fi

# --- rename -----------------------------------------------------------------
before="$(api GET "/v1/sessions/$SID")"
bcode="${before##*$'\n'}"; bpayload="${before%$'\n'*}"
[[ "$bcode" == 2* ]] || die "GET /v1/sessions/$SID -> HTTP $bcode: $bpayload" 4
old="$(printf '%s' "$bpayload" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("title") or "(untitled)")')"

payload="$(TITLE="$TITLE" python3 -c 'import json,os; print(json.dumps({"title": os.environ["TITLE"]}))')"
out="$(api PATCH "/v1/sessions/$SID" "$payload")"
code="${out##*$'\n'}"; resp="${out%$'\n'*}"
if [[ "$code" != 2* ]]; then
  printf '%s\n' "$resp" >&2
  die "PATCH /v1/sessions/$SID -> HTTP $code (rename refused)" 4
fi

stored="$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("title") or "")')"
printf 'renamed %s\n  from: %s\n    to: %s\n' "$SID" "$old" "$stored"
if [[ "$stored" != "$TITLE" ]]; then
  printf '⚠️  server stored a different string than was sent (sent %d chars, stored %d)\n' \
    "${#TITLE}" "${#stored}" >&2
  exit 5
fi
