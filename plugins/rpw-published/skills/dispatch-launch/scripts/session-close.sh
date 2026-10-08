#!/usr/bin/env bash
# Close any session you own, including ones outside your spawn tree (#2030).
#
#   session-close.sh <session-id>
#
# `sys_session_close` only closes a session in the caller's spawn tree, so it
# returns `session_out_of_tree` for anything created over REST — which is every
# path-A session, including the wave-kickoff write probe. The omni CLI (0.16)
# has no close command either. This sends the same PATCH `sys_session_close`
# sends: the `omnigent.closed` label plus `archived: true`, which also triggers
# the server's reaper for the session's harness / tmux / bridge processes.
#
# Exit codes: 0 closed and read back archived · 2 usage · 3 auth · 4 API error
#             5 the server answered 2xx but the session is not archived
set -euo pipefail

[[ $# -eq 1 && -n "$1" ]] || { echo "usage: session-close.sh <session-id>" >&2; exit 2; }
SID="$1"

# shellcheck source=SCRIPTDIR/omni-api.sh
source "$(dirname "${BASH_SOURCE[0]}")/omni-api.sh"

out="$(api PATCH "/v1/sessions/$SID" '{"labels":{"omnigent.closed":"true"},"archived":true}')"
code="${out##*$'\n'}"; resp="${out%$'\n'*}"
[[ "$code" == 2* ]] || die "PATCH /v1/sessions/$SID -> HTTP $code: $resp" 4

# Read back: a 2xx that did not archive must not pass for a close.
out="$(api GET "/v1/sessions/$SID")"
code="${out##*$'\n'}"; resp="${out%$'\n'*}"
[[ "$code" == 2* ]] || die "GET /v1/sessions/$SID -> HTTP $code: $resp" 4
archived="$(printf '%s' "$resp" | python3 -c 'import json,sys; print(str(json.load(sys.stdin).get("archived")).lower())')"
[[ "$archived" == "true" ]] || die "session $SID answered 2xx but is not archived" 5
printf 'closed %s (archived, omnigent.closed=true)\n' "$SID"
