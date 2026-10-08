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
#                                  "Sandbox" comment below before setting this.
set -euo pipefail

IN="${1:?usage: render.sh <in.html> [out.png]}"
OUT="${2:-${IN%.html}.png}"
SCALE="${RPW_SCALE:-2}"

[[ -f "$IN" ]] || { echo "render.sh: no such file: $IN" >&2; exit 1; }
# Absolute path: `file://relative.html` resolves to nothing and Chrome
# screenshots its own "site can't be reached" page instead of the diagram.
IN_ABS="$(cd "$(dirname "$IN")" && pwd)/$(basename "$IN")"

find_chrome() {
  if [[ -n "${CHROME_PATH:-}" ]]; then
    [[ -x "$CHROME_PATH" ]] && { printf '%s' "$CHROME_PATH"; return 0; }
    command -v "$CHROME_PATH" 2>/dev/null && return 0
    return 1
  fi
  local c
  for c in google-chrome google-chrome-stable chromium chromium-browser chrome; do
    command -v "$c" 2>/dev/null && return 0
  done
  for c in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "/opt/google/chrome/chrome"; do
    [[ -x "$c" ]] && { printf '%s' "$c"; return 0; }
  done
  return 1
}

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

# ── Sandbox ─────────────────────────────────────────────────────────────────
# The sandbox is Chrome's containment boundary between a renderer bug and this
# machine's filesystem. The HTML rendered here is agent-authored and may embed
# externally-sourced text unescaped, so it stays on by default — both
# `brew install --cask google-chrome` and `apt-get install chromium`, as a
# normal user, are exactly where it works. --no-sandbox exists for root in a
# container, which this skill's setup instructions never describe; opt in
# explicitly if that's your case.
CHROME_FLAGS=(--headless --disable-gpu --hide-scrollbars)
if [[ "${RPW_DIAGRAM_UNSAFE_NO_SANDBOX:-0}" == "1" ]]; then
  echo "render.sh: WARNING — RPW_DIAGRAM_UNSAFE_NO_SANDBOX=1 set: running Chrome with --no-sandbox. Only for root-in-a-container; this drops renderer containment for agent-authored HTML." >&2
  CHROME_FLAGS+=(--no-sandbox)
fi

# ── Pass 1: measure ────────────────────────────────────────────────────────
# The script is appended to a throwaway copy, so diagram sources stay clean and
# free of render plumbing. Measure off <body>'s box, never documentElement's:
# documentElement.scrollHeight floors at the viewport, so a tall window reports
# the window's height and the PNG comes out padded with dead white space.
TMPDIR_M="$(mktemp -d)"
MEASURE_HTML="$TMPDIR_M/measure.html"
trap 'rm -rf "$TMPDIR_M"' EXIT
{
  cat "$IN_ABS"
  printf '%s' '<script>(function(){var b=document.body,s=getComputedStyle(b),r=b.getBoundingClientRect(),mr=parseFloat(s.marginRight)||0,mb=parseFloat(s.marginBottom)||0;var w=Math.max(r.right+mr,b.scrollWidth+r.left+mr),h=Math.max(r.bottom+mb,b.scrollHeight+r.top+mb);document.title="RPWSIZE:"+Math.ceil(w)+"x"+Math.ceil(h);})();</script>'
} > "$MEASURE_HTML"

MEASURE_ERR="$TMPDIR_M/measure.err"
SIZE="$("$CHROME" "${CHROME_FLAGS[@]}" \
  --window-size=600,600 --virtual-time-budget=1500 --dump-dom \
  "file://$MEASURE_HTML" 2>"$MEASURE_ERR" | grep -o 'RPWSIZE:[0-9]*x[0-9]*' | head -1 || true)"

if [[ -z "$SIZE" ]]; then
  echo "render.sh: could not measure $IN (did Chrome fail to load it?)" >&2
  if grep -qi 'sandbox' "$MEASURE_ERR" 2>/dev/null; then
    echo "render.sh: Chrome's own stderr mentions the sandbox — if this is root in a" >&2
    echo "  container, Chrome refuses to start without --no-sandbox. That flag is opt-in" >&2
    echo "  via RPW_DIAGRAM_UNSAFE_NO_SANDBOX=1 (UNSAFE: drops renderer containment for" >&2
    echo "  this agent-authored HTML — see render.sh's Sandbox comment). Chrome's error:" >&2
    sed 's/^/    /' "$MEASURE_ERR" >&2
  fi
  exit 1
fi
SIZE="${SIZE#RPWSIZE:}"
W="${SIZE%x*}"
H="${SIZE#*x}"

# ── Pass 2: screenshot at the measured size, 2x ────────────────────────────
"$CHROME" "${CHROME_FLAGS[@]}" \
  --window-size="$W,$H" --force-device-scale-factor="$SCALE" \
  --virtual-time-budget=1500 --screenshot="$OUT" "file://$IN_ABS" >/dev/null 2>&1

[[ -s "$OUT" ]] || { echo "render.sh: Chrome wrote no PNG to $OUT" >&2; exit 1; }
echo "$OUT  ${W}x${H} css px  ->  $((W * SCALE))x$((H * SCALE)) px @${SCALE}x"
