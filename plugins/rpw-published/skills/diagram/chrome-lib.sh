# shellcheck shell=bash
# Shared headless-Chrome plumbing for render.sh and qa.sh — sourced, never run.
#
# Both scripts once carried their own copy of everything here, so a fix to one
# (a new Chrome install path, a changed sandbox error string) silently missed
# the other (#2288). Each caller sources this file relative to its own
# directory, so it works from any cwd and from an installed plugin:
#
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/chrome-lib.sh"
#
# Exposes:
#   find_chrome                         print the Chrome/Chromium binary; 1 if none
#   chrome_flags_init <prog>            set the CHROME_FLAGS array (sandbox opt-in)
#   classify_chrome_err <file>          print nested-sandbox | sandbox | other
#   exit_if_nested_sandbox <file> <prog> <not-what>
#                                       exit 3 with one message on a nested sandbox
#
# Exit code 3 is the shared contract: Chrome's own sandbox cannot start because
# this process already runs inside one (an agent's macOS Seatbelt, #2057).

CHROME_NESTED_SANDBOX_EXIT=3

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

# ── Sandbox ─────────────────────────────────────────────────────────────────
# The sandbox is Chrome's containment boundary between a renderer bug and this
# machine's filesystem. The HTML rendered here is agent-authored and may embed
# externally-sourced text unescaped, so it stays on by default — both
# `brew install --cask google-chrome` and `apt-get install chromium`, as a
# normal user, are exactly where it works. --no-sandbox exists for root in a
# container, which this skill's setup instructions never describe; opt in
# explicitly if that's your case (#1093).
chrome_flags_init() {
  local prog="$1"
  CHROME_FLAGS=(--headless --disable-gpu --hide-scrollbars)
  if [[ "${RPW_DIAGRAM_UNSAFE_NO_SANDBOX:-0}" == "1" ]]; then
    echo "$prog: WARNING — RPW_DIAGRAM_UNSAFE_NO_SANDBOX=1 set: running Chrome with --no-sandbox. Only for root-in-a-container; this drops renderer containment for agent-authored HTML." >&2
    CHROME_FLAGS+=(--no-sandbox)
  fi
}

# Classify Chrome's captured stderr. `nested-sandbox`: Chrome's sandbox cannot
# start inside another one — it fails identically every run, so never retry it,
# and --no-sandbox is the wrong fix (#2057). `sandbox`: Chrome mentions its
# sandbox some other way (root in a container). `other`: anything else,
# including a missing or unreadable file.
classify_chrome_err() {
  if grep -q 'sandbox initialization failed' "$1" 2>/dev/null; then
    echo nested-sandbox
  elif grep -qi sandbox "$1" 2>/dev/null; then
    echo sandbox
  else
    echo other
  fi
}

exit_if_nested_sandbox() {
  local err="$1" prog="$2" not_what="$3"
  [[ "$(classify_chrome_err "$err")" == nested-sandbox ]] || return 0
  echo "$prog: Chrome's sandbox cannot start in this environment (nested sandbox) — $not_what." >&2
  echo "  Run outside the enclosing sandbox. RPW_DIAGRAM_UNSAFE_NO_SANDBOX is NOT the fix here:" >&2
  echo "  it is for root-in-a-container only. Chrome's first error lines:" >&2
  head -n 3 "$err" | sed 's/^/    /' >&2
  exit "$CHROME_NESTED_SANDBOX_EXIT"
}
