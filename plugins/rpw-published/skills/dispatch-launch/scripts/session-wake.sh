#!/usr/bin/env bash
# Wake a path-A session and prove the wake landed (#2030).
#
#   session-wake.sh <session-id> <message...>
#
# `POST /v1/sessions` only seeds history; the wake is a second call to
# `POST /v1/sessions/{id}/events`. That call can lose a race on a claude-home
# host: the Seatbelt sandbox hides managed-settings.json on purpose, Claude Code
# opens a "Settings Error" dialog at startup, and the auto-dismisser presses
# "Continue without these settings" a few seconds later. A wake that arrives
# first is refused ("Claude Code is waiting for an answer in its terminal
# (Settings Error)") and the session is marked `failed` — which reads exactly
# like a dead spawn, but the pane is healthy seconds later. The cure is to
# re-post the wake, never to relaunch. Measured 2026-09-28 (one session:
# refused ~20:51:50Z, dismissed 20:51:55Z, re-post worked).
#
# Exit codes:
#   0  the session is running (the wake landed)
#   2  usage
#   3  auth could not be resolved (from omni-api.sh)
#   4  an API call failed
#   6  failed for a reason other than the Settings Error race — a real dead spawn
#   7  still idle after the timeout — not started; poll again before concluding
set -euo pipefail

# How long to wait for `running`, how often to poll, and how long to give the
# auto-dismisser before a re-post. Overridable for tests and slow hosts.
WAKE_TIMEOUT="${WAKE_TIMEOUT:-90}"
WAKE_POLL="${WAKE_POLL:-5}"
WAKE_RETRY_DELAY="${WAKE_RETRY_DELAY:-10}"
WAKE_MAX_REPOSTS="${WAKE_MAX_REPOSTS:-2}"

# The dialog's own title, as the harness quotes it in the refusal.
RACE_MARKER="Settings Error"

usage() {
  cat >&2 <<'USAGE'
usage: session-wake.sh <session-id> <message...>

  Posts the wake event, then polls until the session is running. A refusal
  caused by the claude-home "Settings Error" dialog is re-posted after
  WAKE_RETRY_DELAY seconds (at most WAKE_MAX_REPOSTS times).

env: WAKE_TIMEOUT (90) WAKE_POLL (5) WAKE_RETRY_DELAY (10) WAKE_MAX_REPOSTS (2)
     plus the omni-api.sh variables (OMNIGENT_API_BASE, RUNNER_SERVER_URL, ...)
USAGE
  exit 2
}

[[ $# -ge 2 ]] || usage
SID="$1"; shift
MESSAGE="$*"

# shellcheck source=SCRIPTDIR/omni-api.sh
source "$(dirname "${BASH_SOURCE[0]}")/omni-api.sh"

post_wake() {
  local payload out code
  payload="$(MESSAGE="$MESSAGE" python3 -c '
import json, os
print(json.dumps({"type": "message", "data": {"role": "user",
    "content": [{"type": "input_text", "text": os.environ["MESSAGE"]}]}}))')"
  out="$(api POST "/v1/sessions/$SID/events" "$payload")"
  code="${out##*$'\n'}"
  [[ "$code" == 2* ]] || die "POST /v1/sessions/$SID/events -> HTTP $code: ${out%$'\n'*}" 4
}

session_status() {
  local out code
  out="$(api GET "/v1/sessions/$SID")"
  code="${out##*$'\n'}"
  [[ "$code" == 2* ]] || die "GET /v1/sessions/$SID -> HTTP $code: ${out%$'\n'*}" 4
  printf '%s' "${out%$'\n'*}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status") or "")'
}

# Prints "<error item id><TAB><message>" for the newest error item, or nothing.
# The id, not the text, tells a fresh refusal from the one already handled:
# two races produce byte-identical messages.
latest_error() {
  local out code
  out="$(api GET "/v1/sessions/$SID/items?limit=20")"
  code="${out##*$'\n'}"
  [[ "$code" == 2* ]] || die "GET /v1/sessions/$SID/items -> HTTP $code: ${out%$'\n'*}" 4
  printf '%s' "${out%$'\n'*}" | python3 -c '
import json, sys
data = json.load(sys.stdin)
rows = data.get("data", []) if isinstance(data, dict) else data
errs = [r for r in rows if isinstance(r, dict) and r.get("type") == "error"]
if errs:
    errs.sort(key=lambda r: r.get("created_at") or 0)
    last = errs[-1]
    msg = (last.get("message") or "").replace("\t", " ").replace("\n", " ")
    print(str(last.get("id") or "") + "\t" + msg)
'
}

post_wake
reposts=0
handled_error_id=""
deadline=$(( $(date +%s) + WAKE_TIMEOUT ))
while :; do
  status="$(session_status)"
  case "$status" in
    running)
      printf 'woke %s (status running, %d re-post(s))\n' "$SID" "$reposts"
      exit 0
      ;;
    failed)
      line="$(latest_error)"
      err_id="${line%%$'\t'*}"; err="${line#*$'\t'}"
      if [[ "$err" == *"$RACE_MARKER"* && "$err_id" != "$handled_error_id" ]] &&
         (( reposts < WAKE_MAX_REPOSTS )); then
        handled_error_id="$err_id"
        reposts=$(( reposts + 1 ))
        printf 'wake refused by the claude-home "%s" dialog — re-posting in %ss (%d/%d, #2030)\n' \
          "$RACE_MARKER" "$WAKE_RETRY_DELAY" "$reposts" "$WAKE_MAX_REPOSTS" >&2
        sleep "$WAKE_RETRY_DELAY"
        post_wake
        deadline=$(( $(date +%s) + WAKE_TIMEOUT ))
      elif [[ "$err" == *"$RACE_MARKER"* && "$err_id" == "$handled_error_id" ]]; then
        : # the old refusal is still the newest error; the re-post has not landed yet
      elif [[ "$err" == *"$RACE_MARKER"* ]]; then
        printf 'session %s: the "%s" dialog refused %d re-post(s); the auto-dismisser is not firing.\n' \
          "$SID" "$RACE_MARKER" "$reposts" >&2
        printf '  check ~/.claude-home/auto-dismiss.log, answer the pane by hand, then re-run this.\n' >&2
        exit 6
      else
        printf 'session %s failed, and not on the Settings Error race — a dead spawn.\n' "$SID" >&2
        [[ -n "$err" ]] && printf '  last error: %s\n' "${err:0:400}" >&2
        exit 6
      fi
      ;;
  esac
  if (( $(date +%s) >= deadline )); then
    printf 'session %s still "%s" after %ss — not started yet; poll again before concluding.\n' \
      "$SID" "${status:-unknown}" "$WAKE_TIMEOUT" >&2
    exit 7
  fi
  sleep "$WAKE_POLL"
done
