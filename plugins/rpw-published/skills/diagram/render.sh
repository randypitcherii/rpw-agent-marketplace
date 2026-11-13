#!/usr/bin/env bash
# Render a self-contained diagram HTML to a 2x PNG with headless Chrome.
#
#   render.sh <in.html> [out.png]
#
# Two passes, because `--screenshot` captures the window, not the page: pass 1
# measures the laid-out page and pass 2 shoots a window of exactly that size.
# A hand-guessed --window-size is the #1 cause of a clipped or half-empty PNG.
#
# Env overrides:
#   CHROME_PATH                    explicit Chrome/Chromium binary
#   RPW_SCALE                      device scale factor (default 2 — the crispness contract)
#   RPW_DIAGRAM_UNSAFE_NO_SANDBOX  UNSAFE: set to 1 to run Chrome with --no-sandbox. Only
#                                  for root-in-a-container, where Chrome refuses to start
#                                  without it. Drops renderer containment for the
#                                  agent-authored HTML this script renders. See the
#                                  "Sandbox" comment in chrome-lib.sh before setting this.
#
# Exit codes:
#   0  PNG written
#   1  render failure: bad input, or Chrome still failing after RENDER_ATTEMPTS tries
#      (Chrome's exit code and stderr are printed)
#   3  Chrome's own sandbox cannot start here because this process already runs in
#      one (a nested sandbox, e.g. an agent's macOS Seatbelt) — not a render defect
set -euo pipefail

IN="${1:?usage: render.sh <in.html> [out.png]}"
OUT="${2:-${IN%.html}.png}"
SCALE="${RPW_SCALE:-2}"

[[ -f "$IN" ]] || { echo "render.sh: no such file: $IN" >&2; exit 1; }
# Absolute path: `file://relative.html` resolves to nothing and Chrome
# screenshots its own "site can't be reached" page instead of the diagram.
IN_ABS="$(cd "$(dirname "$IN")" && pwd)/$(basename "$IN")"

# Chrome discovery, the sandbox flag setup and the nested-sandbox detector are
# shared with qa.sh (#2288); resolved from this script's own dir, never the cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=chrome-lib.sh
source "$SCRIPT_DIR/chrome-lib.sh"

CHROME="$(find_chrome)" || {
  cat >&2 <<'EOF'
render.sh: no Chrome/Chromium found.
  macOS:  brew install --cask google-chrome
  Debian: apt-get install chromium
  Or set CHROME_PATH to the binary.
Headless Chrome is this skill's only dependency — do not hand-write the PNG.
EOF
  exit 1
}

# Sandbox stays on unless RPW_DIAGRAM_UNSAFE_NO_SANDBOX=1 — see chrome-lib.sh.
chrome_flags_init render.sh

# ── Nested sandbox and transient failures ──────────────────────────────────
# Inside another sandbox, Chrome's sandbox fails the same way every run, so
# retrying is pointless and --no-sandbox would be the wrong fix (#2057): exit 3.
# Anything else — Chrome exiting non-zero under load, an empty measure — retries
# a bounded number of times, keeping stderr so a persistent failure names its
# cause instead of leaking Chrome's own exit status (#2228).
RENDER_ATTEMPTS=3

# ── Pass 1: measure ────────────────────────────────────────────────────────
# The script is appended to a throwaway copy, so diagram sources stay clean and
# free of render plumbing. Measure off <body>'s box, never documentElement's:
# documentElement.scrollHeight floors at the viewport, so a tall window reports
# the window's height and the PNG comes out padded with dead white space.
TMPDIR_M="$(mktemp -d)"
MEASURE_HTML="$TMPDIR_M/measure.html"
trap 'rm -rf "$TMPDIR_M"' EXIT

# ── Profile isolation ──────────────────────────────────────────────────────
# Every launch gets its own throwaway --user-data-dir. Without one, headless
# Chrome uses the user's real profile and its Crashpad database, so concurrent
# renders (parallel agents, `pytest -n auto`) contend on that shared state at
# shutdown: Chrome writes the PNG, then its teardown watchdog expires and it
# exits 2 — measured 6 of 36 launches at 12-way concurrency, 0 of 36 with a
# per-launch profile (#2392). Retrying cannot fix that while the others run.
fresh_profile() { mktemp -d "$TMPDIR_M/profile.XXXXXX"; }
{
  cat "$IN_ABS"
  printf '%s' '<script>(function(){var b=document.body,s=getComputedStyle(b),r=b.getBoundingClientRect(),mr=parseFloat(s.marginRight)||0,mb=parseFloat(s.marginBottom)||0;var w=Math.max(r.right+mr,b.scrollWidth+r.left+mr),h=Math.max(r.bottom+mb,b.scrollHeight+r.top+mb);document.title="RPWSIZE:"+Math.ceil(w)+"x"+Math.ceil(h);})();</script>'
} > "$MEASURE_HTML"

MEASURE_ERR="$TMPDIR_M/measure.err"
SIZE=""
for ((attempt = 1; attempt <= RENDER_ATTEMPTS; attempt++)); do
  SIZE="$("$CHROME" "${CHROME_FLAGS[@]}" --user-data-dir="$(fresh_profile)" \
    --window-size=600,600 --virtual-time-budget=1500 --dump-dom \
    "file://$MEASURE_HTML" 2>"$MEASURE_ERR" | grep -o 'RPWSIZE:[0-9]*x[0-9]*' | head -1 || true)"
  [[ -n "$SIZE" ]] && break
  exit_if_nested_sandbox "$MEASURE_ERR" render.sh "not a render defect"
  if ((attempt < RENDER_ATTEMPTS)); then
    echo "render.sh: measure attempt $attempt/$RENDER_ATTEMPTS got no size from Chrome; retrying" >&2
    sleep 1
  fi
done

if [[ -z "$SIZE" ]]; then
  echo "render.sh: could not measure $IN (did Chrome fail to load it?)" >&2
  if [[ "$(classify_chrome_err "$MEASURE_ERR")" == sandbox ]]; then
    echo "render.sh: Chrome's own stderr mentions the sandbox — if this is root in a" >&2
    echo "  container, Chrome refuses to start without --no-sandbox. That flag is opt-in" >&2
    echo "  via RPW_DIAGRAM_UNSAFE_NO_SANDBOX=1 (UNSAFE: drops renderer containment for" >&2
    echo "  this agent-authored HTML — see chrome-lib.sh's Sandbox comment). Chrome's error:" >&2
    sed 's/^/    /' "$MEASURE_ERR" >&2
  fi
  exit 1
fi
SIZE="${SIZE#RPWSIZE:}"
W="${SIZE%x*}"
H="${SIZE#*x}"

# ── Pass 2: screenshot at the measured size, 2x ────────────────────────────
# Stderr is kept, not discarded: a bare `>/dev/null 2>&1` here once let Chrome's
# own exit status (2) escape through `set -e` with no message at all (#2228).
SHOT_ERR="$TMPDIR_M/screenshot.err"
for ((attempt = 1; attempt <= RENDER_ATTEMPTS; attempt++)); do
  rm -f "$OUT"
  CHROME_RC=0
  "$CHROME" "${CHROME_FLAGS[@]}" --user-data-dir="$(fresh_profile)" \
    --window-size="$W,$H" --force-device-scale-factor="$SCALE" \
    --virtual-time-budget=1500 --screenshot="$OUT" "file://$IN_ABS" >/dev/null 2>"$SHOT_ERR" ||
    CHROME_RC=$?
  [[ "$CHROME_RC" -eq 0 && -s "$OUT" ]] && break
  exit_if_nested_sandbox "$SHOT_ERR" render.sh "not a render defect"
  if ((attempt < RENDER_ATTEMPTS)); then
    echo "render.sh: screenshot attempt $attempt/$RENDER_ATTEMPTS failed (Chrome exit $CHROME_RC); retrying" >&2
    sleep 1
  fi
done

if [[ "$CHROME_RC" -ne 0 || ! -s "$OUT" ]]; then
  echo "render.sh: Chrome wrote no PNG to $OUT after $RENDER_ATTEMPTS attempts (last Chrome exit $CHROME_RC). Chrome's stderr:" >&2
  tail -n 20 "$SHOT_ERR" | sed 's/^/    /' >&2
  exit 1
fi
echo "$OUT  ${W}x${H} css px  ->  $((W * SCALE))x$((H * SCALE)) px @${SCALE}x"
