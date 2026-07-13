#!/usr/bin/env bash
# Stop hook — gates build completion on receipt artifact existence.
# Plugin-owned version. Sources the canonical build-state library.
# Only activates when build state exists (active /build session).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$SCRIPT_DIR/../scripts/build-state.sh"

source "$LIB" 2>/dev/null || exit 0

STATE_FILE=$(_build_state_file 2>/dev/null) || exit 0
if [ ! -f "$STATE_FILE" ]; then
  exit 0
fi

# Phase 2 (implementation): don't gate the full receipt checklist until
# implement_complete is set — avoids noisy Stop feedback during normal turns.
if ! build_phase_get implement_complete >/dev/null 2>&1; then
  exit 0
fi

RECEIPTS_DIR=$(_build_receipts_dir 2>/dev/null) || exit 0

MISSING=()
INVALID=()
# Canonical 6 receipts: check, security-review, simplification,
# human-validation, docs-review, retro.
for phase in check security-review simplification human-validation docs-review retro; do
  RECEIPT="$RECEIPTS_DIR/$phase.json"
  if [ ! -s "$RECEIPT" ]; then
    MISSING+=("$phase")
  elif ! python3 -c "import json, sys; json.load(open(sys.argv[1]))" "$RECEIPT" 2>/dev/null; then
    INVALID+=("$phase")
  fi
done

if [ ${#INVALID[@]} -gt 0 ]; then
  echo "BUILD INCOMPLETE: Invalid JSON in receipts: ${INVALID[*]}" >&2
  echo "Re-save with valid JSON via 'make build-receipt PHASE=<phase>' (reads stdin)." >&2
  exit 2
fi

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "BUILD INCOMPLETE: Missing receipts for: ${MISSING[*]}" >&2
  echo "" >&2
  echo "Each phase must produce a receipt at \$RECEIPTS_DIR/<phase>.json:" >&2
  for m in "${MISSING[@]}"; do
    case "$m" in
      check)
        echo "  - check: Run the project's check gate and save the receipt" >&2 ;;
      security-review)
        echo "  - security-review: Review changed files for security issues" >&2 ;;
      simplification)
        echo "  - simplification: Run simplifier pass or document 'no changes needed'" >&2 ;;
      human-validation)
        echo "  - human-validation: Run Phase 3d human validation with user confirmation" >&2 ;;
      docs-review)
        echo "  - docs-review: Check docs for needed updates or document 'none needed'" >&2 ;;
      retro)
        echo "  - retro: Run Phase 5a retrospective with categorized feedback" >&2 ;;
    esac
  done
  echo "" >&2
  echo "Use: make build-receipt PHASE=<phase> <<<'<json>' (or via heredoc)" >&2
  exit 2
fi

# All receipts present — also require the check gate has passed.
if ! build_phase_get check_passed >/dev/null 2>&1; then
  echo "BUILD INCOMPLETE: check_passed phase not set. Run 'make check' first." >&2
  exit 2
fi

exit 0
