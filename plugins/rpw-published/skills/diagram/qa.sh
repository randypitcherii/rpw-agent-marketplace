#!/usr/bin/env bash
# Deterministically check diagram geometry and PNG dimensions in headless Chrome.
#
#   qa.sh <in.html> [in.png] [receipt.json]
#
# The receipt defaults to <in.png without .png>.qa.json. Exit 0 means every
# machine-checkable item passed; exit 1 means the receipt contains findings.
#
# Env overrides:
#   CHROME_PATH                    explicit Chrome/Chromium binary
#   RPW_SCALE                      expected device scale factor (default 2)
#   RPW_DIAGRAM_UNSAFE_NO_SANDBOX  UNSAFE: same root-in-a-container opt-in as render.sh
set -euo pipefail

if [[ "$#" -lt 1 || "$#" -gt 3 ]]; then
  echo "usage: qa.sh <in.html> [in.png] [receipt.json]" >&2
  exit 2
fi
IN="$1"
PNG="${2:-${IN%.html}.png}"
RECEIPT="${3:-${PNG%.png}.qa.json}"
SCALE="${RPW_SCALE:-2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKER="$SCRIPT_DIR/qa.js"

[[ "$SCALE" =~ ^[1-9][0-9]*$ ]] || {
  echo "qa.sh: RPW_SCALE must be a positive integer, got: $SCALE" >&2
  exit 2
}
[[ -f "$IN" ]] || { echo "qa.sh: no such HTML file: $IN" >&2; exit 2; }
[[ -f "$PNG" ]] || { echo "qa.sh: no such PNG file: $PNG" >&2; exit 2; }
[[ -f "$CHECKER" ]] || { echo "qa.sh: missing browser checker: $CHECKER" >&2; exit 2; }

IN_ABS="$(cd "$(dirname "$IN")" && pwd)/$(basename "$IN")"
PNG_ABS="$(cd "$(dirname "$PNG")" && pwd)/$(basename "$PNG")"

find_chrome() {
  if [[ -n "${CHROME_PATH:-}" ]]; then
    [[ -x "$CHROME_PATH" ]] && { printf '%s' "$CHROME_PATH"; return 0; }
    command -v "$CHROME_PATH" 2>/dev/null && return 0
    return 1
  fi
  local candidate
  for candidate in google-chrome google-chrome-stable chromium chromium-browser chrome; do
    command -v "$candidate" 2>/dev/null && return 0
  done
  for candidate in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "/opt/google/chrome/chrome"; do
    [[ -x "$candidate" ]] && { printf '%s' "$candidate"; return 0; }
  done
  return 1
}

CHROME="$(find_chrome)" || {
  echo "qa.sh: no Chrome/Chromium found; use render.sh's installation instructions." >&2
  exit 2
}

CHROME_FLAGS=(--headless --disable-gpu --hide-scrollbars)
if [[ "${RPW_DIAGRAM_UNSAFE_NO_SANDBOX:-0}" == "1" ]]; then
  echo "qa.sh: WARNING — running Chrome with --no-sandbox; renderer containment is disabled." >&2
  CHROME_FLAGS+=(--no-sandbox)
fi

TMPDIR_QA="$(mktemp -d)"
QA_HTML="$TMPDIR_QA/input.html"
QA_ERR="$TMPDIR_QA/chrome.err"
CDP_IN="$TMPDIR_QA/cdp.in"
CDP_OUT="$TMPDIR_QA/cdp.out"
PROFILE="$TMPDIR_QA/profile"
CDP_PID=""
cleanup() {
  # Capture first: with `set -e`, a later kill/wait/rm in this trap would
  # otherwise rewrite `exit 0` (PASS) into 1 after the receipt is already written.
  local rc=$?
  set +e
  if [[ -n "$CDP_PID" ]]; then
    kill "$CDP_PID" 2>/dev/null
    wait "$CDP_PID" 2>/dev/null
  fi
  exec 5>&- 2>/dev/null
  exec 6<&- 2>/dev/null
  if [[ "${RPW_DIAGRAM_QA_DEBUG:-0}" == "1" ]]; then
    echo "qa.sh: debug files kept in $TMPDIR_QA" >&2
  else
    rm -rf "$TMPDIR_QA"
  fi
  exit "$rc"
}
trap cleanup EXIT

PNG_SIGNATURE="$(od -An -tx1 -N8 "$PNG_ABS" | tr -d ' \n')"
[[ "$PNG_SIGNATURE" == "89504e470d0a1a0a" ]] || {
  echo "qa.sh: artifact is not a PNG: $PNG" >&2
  exit 2
}
PNG_BYTES=($(od -An -tu1 -j16 -N8 "$PNG_ABS"))
if [[ "${#PNG_BYTES[@]}" -ne 8 ]]; then
  echo "qa.sh: could not read PNG dimensions from $PNG" >&2
  exit 2
fi
PNG_WIDTH=$((PNG_BYTES[0] * 16777216 + PNG_BYTES[1] * 65536 + PNG_BYTES[2] * 256 + PNG_BYTES[3]))
PNG_HEIGHT=$((PNG_BYTES[4] * 16777216 + PNG_BYTES[5] * 65536 + PNG_BYTES[6] * 256 + PNG_BYTES[7]))
HTML_B64="$(printf '%s' "$IN_ABS" | base64 | tr -d '\n')"
PNG_B64="$(printf '%s' "$PNG_ABS" | base64 | tr -d '\n')"
# The artifact's own bytes, for the non-blank pixel read. Chrome decodes the PNG
# — no new dependency — but only if the bytes reach the isolated world, and a
# file:// subresource fetch from the page is both blocked and indistinguishable
# from the local-file reference external-resources exists to reject.
PNG_DATA_B64="$(base64 <"$PNG_ABS" | tr -d '\n')"
CHECKER_B64="$(base64 <"$CHECKER" | tr -d '\n')"
cp "$IN_ABS" "$QA_HTML"
mkfifo "$CDP_IN" "$CDP_OUT"

"$CHROME" "${CHROME_FLAGS[@]}" \
  --no-first-run --no-default-browser-check \
  --remote-debugging-pipe --user-data-dir="$PROFILE" \
  --window-size=600,600 about:blank \
  3<"$CDP_IN" 4>"$CDP_OUT" > /dev/null 2>"$QA_ERR" &
CDP_PID=$!
exec 5>"$CDP_IN"
exec 6<"$CDP_OUT"

CDP_ID=0
CDP_REPLY=""
PAGE_LOADED=0
EXTERNAL_NETWORK_COUNT=0
MAIN_DOCUMENT_FILE_REQUEST_SEEN=0
record_cdp_event() {
  local message="$1"
  local external_url_re='"url":"(https?|wss?):[^"]*"'
  local local_file_url_re='"url":"file:[^"]*"'
  if [[ "$message" == *'"method":"Page.loadEventFired"'* ]]; then
    PAGE_LOADED=1
  fi
  if {
    [[ "$message" == *'"method":"Network.requestWillBeSent"'* ]] ||
      [[ "$message" == *'"method":"Network.webSocketCreated"'* ]] ||
      [[ "$message" == *'"method":"Network.webTransportCreated"'* ]]
  } && [[ "$message" =~ $external_url_re ]]; then
    EXTERNAL_NETWORK_COUNT=$((EXTERNAL_NETWORK_COUNT + 1))
  elif [[ "$message" == *'"method":"Network.requestWillBeSent"'* ]] &&
    [[ "$message" =~ $local_file_url_re ]]; then
    if [[ "$message" == *'"type":"Document"'* && "$MAIN_DOCUMENT_FILE_REQUEST_SEEN" -eq 0 ]]; then
      MAIN_DOCUMENT_FILE_REQUEST_SEEN=1
    else
      EXTERNAL_NETWORK_COUNT=$((EXTERNAL_NETWORK_COUNT + 1))
    fi
  fi
}

cdp_call() {
  local body="$1"
  local message
  local deadline=$((SECONDS + 20))
  CDP_ID=$((CDP_ID + 1))
  printf '{"id":%s,%s}\0' "$CDP_ID" "$body" >&5
  while [[ "$SECONDS" -lt "$deadline" ]]; do
    if IFS= read -r -d '' -t 1 message <&6; then
      record_cdp_event "$message"
      if [[ "$message" == "{\"id\":$CDP_ID,"* ]]; then
        CDP_REPLY="$message"
        return 0
      fi
    fi
  done
  return 1
}

wait_for_page_load() {
  local message
  local deadline=$((SECONDS + 20))
  while [[ "$PAGE_LOADED" -eq 0 && "$SECONDS" -lt "$deadline" ]]; do
    if IFS= read -r -d '' -t 1 message <&6; then
      record_cdp_event "$message"
    fi
  done
  [[ "$PAGE_LOADED" -eq 1 ]]
}

tool_error() {
  echo "qa.sh: Chrome produced no authentic QA receipt for $IN" >&2
  if [[ "${RPW_DIAGRAM_QA_DEBUG:-0}" == "1" && -n "$CDP_REPLY" ]]; then
    echo "qa.sh: last DevTools response: $CDP_REPLY" >&2
  fi
  if grep -qi sandbox "$QA_ERR"; then
    echo "qa.sh: Chrome mentions its sandbox. In root-in-a-container only, set" >&2
    echo "  RPW_DIAGRAM_UNSAFE_NO_SANDBOX=1 (UNSAFE; disables renderer containment)." >&2
  fi
  [[ -s "$QA_ERR" ]] && cat "$QA_ERR" >&2
  exit 2
}

cdp_call '"method":"Target.getTargets"' || tool_error
TARGET_RE='"targetId":"([^"]+)","type":"page"'
[[ "$CDP_REPLY" =~ $TARGET_RE ]] || tool_error
TARGET_ID="${BASH_REMATCH[1]}"

cdp_call "\"method\":\"Target.attachToTarget\",\"params\":{\"targetId\":\"$TARGET_ID\",\"flatten\":true}" || tool_error
SESSION_RE='"sessionId":"([^"]+)"'
[[ "$CDP_REPLY" =~ $SESSION_RE ]] || tool_error
SESSION_ID="${BASH_REMATCH[1]}"

cdp_call "\"method\":\"Page.enable\",\"sessionId\":\"$SESSION_ID\"" || tool_error
cdp_call "\"method\":\"Network.enable\",\"sessionId\":\"$SESSION_ID\"" || tool_error
cdp_call "\"method\":\"Page.navigate\",\"params\":{\"url\":\"file://$QA_HTML\"},\"sessionId\":\"$SESSION_ID\"" || tool_error
FRAME_RE='"frameId":"([^"]+)"'
[[ "$CDP_REPLY" =~ $FRAME_RE ]] || tool_error
FRAME_ID="${BASH_REMATCH[1]}"
wait_for_page_load || tool_error

cdp_call "\"method\":\"Page.createIsolatedWorld\",\"params\":{\"frameId\":\"$FRAME_ID\",\"worldName\":\"rpw-diagram-qa\",\"grantUniveralAccess\":false},\"sessionId\":\"$SESSION_ID\"" || tool_error
CONTEXT_RE='"executionContextId":([0-9]+)'
[[ "$CDP_REPLY" =~ $CONTEXT_RE ]] || tool_error
CONTEXT_ID="${BASH_REMATCH[1]}"

SETTLE_SOURCE="$(cat <<'EOF'
(async () => {
  if (document.readyState !== "complete") {
    await new Promise((resolve) => window.addEventListener("load", resolve, { once: true }));
  }
  if (document.fonts && document.fonts.ready) {
    await document.fonts.ready;
  }
  await new Promise((resolve) => window.setTimeout(resolve, 2000));
  await new Promise((resolve) =>
    window.requestAnimationFrame(() => window.requestAnimationFrame(resolve))
  );
  return "RPWQA:READY";
})()
EOF
)"
SETTLE_B64="$(printf '%s' "$SETTLE_SOURCE" | base64 | tr -d '\n')"
cdp_call "\"method\":\"Runtime.evaluate\",\"params\":{\"expression\":\"eval(atob(\\\"$SETTLE_B64\\\"))\",\"contextId\":$CONTEXT_ID,\"awaitPromise\":true,\"returnByValue\":true},\"sessionId\":\"$SESSION_ID\"" || tool_error
READY_RE='^\{"id":([0-9]+),"result":\{"result":\{"type":"string","value":"RPWQA:READY"\}\},"sessionId":"([^"]+)"\}$'
[[ "$CDP_REPLY" =~ $READY_RE ]] || tool_error
[[ "${BASH_REMATCH[1]}" == "$CDP_ID" && "${BASH_REMATCH[2]}" == "$SESSION_ID" ]] || tool_error

# A command-response round trip drains Network events queued at the end of the
# observation window before their count is sealed into the checker metadata.
cdp_call "\"method\":\"Runtime.evaluate\",\"params\":{\"expression\":\"\\\"RPWQA:BARRIER\\\"\",\"contextId\":$CONTEXT_ID,\"returnByValue\":true},\"sessionId\":\"$SESSION_ID\"" || tool_error
BARRIER_RE='^\{"id":([0-9]+),"result":\{"result":\{"type":"string","value":"RPWQA:BARRIER"\}\},"sessionId":"([^"]+)"\}$'
[[ "$CDP_REPLY" =~ $BARRIER_RE ]] || tool_error
[[ "${BASH_REMATCH[1]}" == "$CDP_ID" && "${BASH_REMATCH[2]}" == "$SESSION_ID" ]] || tool_error

# The PNG's base64 goes over as its own statement, not inside DRIVER_SOURCE:
# the driver is itself base64'd for transport, so embedding the artifact there
# would encode a ~600KB PNG twice. Base64's alphabet needs no JSON escaping, and
# the isolated world is unreachable from page scripts, so the global cannot be
# tampered with. Echoing .length proves the whole payload arrived.
PNG_DATA_LENGTH="${#PNG_DATA_B64}"
cdp_call "\"method\":\"Runtime.evaluate\",\"params\":{\"expression\":\"(globalThis.__RPWQA_PNG_B64=\\\"$PNG_DATA_B64\\\").length\",\"contextId\":$CONTEXT_ID,\"returnByValue\":true},\"sessionId\":\"$SESSION_ID\"" || tool_error
[[ "$CDP_REPLY" == "{\"id\":$CDP_ID,"* ]] || tool_error
[[ "$CDP_REPLY" == *"\"value\":$PNG_DATA_LENGTH"* ]] || tool_error
[[ "$CDP_REPLY" == *"\"sessionId\":\"$SESSION_ID\""* ]] || tool_error

DRIVER_SOURCE="$(cat <<EOF
(async () => {
  const qa = (0, eval)(atob("$CHECKER_B64"));
  const receipt = await qa({
    html: atob("$HTML_B64"),
    png: atob("$PNG_B64"),
    pngData: globalThis.__RPWQA_PNG_B64,
    scale: $SCALE,
    pngWidth: $PNG_WIDTH,
    pngHeight: $PNG_HEIGHT,
    externalNetworkCount: $EXTERNAL_NETWORK_COUNT
  });
  const payload = btoa(unescape(encodeURIComponent(JSON.stringify(receipt))));
  return "RPWQA:" + (receipt.ok ? "PASS:" : "FAIL:") + payload;
})()
EOF
)"
DRIVER_B64="$(printf '%s' "$DRIVER_SOURCE" | base64 | tr -d '\n')"
cdp_call "\"method\":\"Runtime.evaluate\",\"params\":{\"expression\":\"eval(atob(\\\"$DRIVER_B64\\\"))\",\"contextId\":$CONTEXT_ID,\"awaitPromise\":true,\"returnByValue\":true},\"sessionId\":\"$SESSION_ID\"" || tool_error

RECEIPT_RE='^\{"id":([0-9]+),"result":\{"result":\{"type":"string","value":"RPWQA:(PASS|FAIL):([ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=]+)"\}\},"sessionId":"([^"]+)"\}$'
[[ "$CDP_REPLY" =~ $RECEIPT_RE ]] || tool_error
[[ "${BASH_REMATCH[1]}" == "$CDP_ID" ]] || tool_error
[[ "${BASH_REMATCH[4]}" == "$SESSION_ID" ]] || tool_error
STATUS="${BASH_REMATCH[2]}"
PAYLOAD="${BASH_REMATCH[3]}"

mkdir -p "$(dirname "$RECEIPT")"
if printf '%s' "$PAYLOAD" | base64 --decode >"$RECEIPT" 2>/dev/null; then
  :
elif printf '%s' "$PAYLOAD" | base64 -D >"$RECEIPT" 2>/dev/null; then
  :
else
  rm -f "$RECEIPT"
  tool_error
fi

if [[ "$STATUS" == "PASS" ]]; then
  echo "$RECEIPT  PASS"
  exit 0
fi

echo "$RECEIPT  FAIL — inspect findings in the receipt" >&2
exit 1
