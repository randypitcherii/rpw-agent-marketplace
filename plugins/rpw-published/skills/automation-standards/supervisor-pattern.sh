#!/bin/bash
# Watchdog supervisor skeleton — the shape a persistent job should point at instead of
# pointing at the program directly. See SKILL.md, Rule 0 and Mode A.
#
# It exists because a restart-on-exit supervisor (launchd KeepAlive, systemd
# Restart=always) cannot see the dominant failure: alive, not serving, never exits.
#
# Copy it, then replace the four ADAPT blocks. Everything else is the pattern.

set -euo pipefail
# Job control: with -m every background job starts in its OWN process group, so the group
# kills below actually reach grandchildren. macOS ships no setsid(1); this is the portable way
# to get a killable group for the child.
set -m

# ---- ADAPT 1: identity -------------------------------------------------------------
TARGET="${TARGET:?the resource this job serves}"     # url, endpoint, queue, ...
# Substring that identifies OUR program in `ps -o command=`. Required: eviction
# refuses to signal a claim-holder it cannot identify, because a stale claim's pid
# may have been recycled by an unrelated process.
# (no apostrophes in a :? message — bash 3.2 mis-parses a quote inside ${...:?...})
EXPECT_HOLDER_CMD="${EXPECT_HOLDER_CMD:?a substring matching the command line of this job}"
CLAIM_DIR="${CLAIM_DIR:-$HOME/.local/state/supervisor}"
CLAIM_FILE="$CLAIM_DIR/$(printf '%s' "$TARGET" | tr -c 'A-Za-z0-9' '_').json"

HEALTH_INTERVAL="${HEALTH_INTERVAL:-60}"   # sparse: a probe competes with the job
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-30}"     # every probe is time-capped
BACKOFF_MIN="${BACKOFF_MIN:-5}"
BACKOFF_MAX="${BACKOFF_MAX:-300}"
FAST_FAIL_SECONDS="${FAST_FAIL_SECONDS:-30}"

CHILD_PID=""

# ---- Cleanup: nothing outlives this supervisor -------------------------------------
# kill the whole process group, not $CHILD_PID: the child may have spawned its own.
cleanup() {
  if [[ -n "$CHILD_PID" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
    kill -TERM "-$CHILD_PID" 2>/dev/null || kill -TERM "$CHILD_PID" 2>/dev/null || true
    for _ in $(seq 1 10); do kill -0 "$CHILD_PID" 2>/dev/null || break; sleep 1; done
    kill -KILL "-$CHILD_PID" 2>/dev/null || true
  fi
}
# Signal handlers must EXIT after cleaning up. A trapped signal does not end the
# shell on its own — a handler that returns resumes the while-true loop below and
# respawns the child, making the supervisor unkillable by TERM/INT (it then burns
# launchd's ExitTimeOut and gets SIGKILLed, orphaning the fresh child).
trap cleanup EXIT
trap 'cleanup; trap - EXIT; exit 130' INT
trap 'cleanup; trap - EXIT; exit 143' TERM

log() { printf '%s supervisor: %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }

# ---- ADAPT 2: the serving predicate ------------------------------------------------
# The ONLY definition of health. Must prove the job is SERVING, not that it is running.
# Never inspect pid / state / restart count / last exit code here.
# REDACT: a failing probe's output is logged (see bounded_is_serving), and curl/CLI
# failures echo the request URL and auth diagnostics. If your probe carries a token,
# strip it here — e.g. pipe through:
#   sed -E 's/(token|api[-_]?key|authorization|password)=[^ &]*/\1=REDACTED/gi'
is_serving() {
  # e.g. curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/readyz" >/dev/null
  # e.g. mycli status --target "$TARGET" | grep -q 'state=online'
  return 1
}

# macOS has no timeout(1): background the probe and poll kill -0.
bounded_is_serving() {
  local out; out="$(mktemp)"
  ( is_serving >"$out" 2>&1 ) & local probe=$!
  local waited=0
  while kill -0 "$probe" 2>/dev/null; do
    if (( waited >= HEALTH_TIMEOUT )); then
      # Group-kill: the probe subshell has its own group (set -m), and killing
      # only the subshell would leak whatever it spawned (curl, a CLI, ...).
      kill -KILL -"$probe" 2>/dev/null || kill -KILL "$probe" 2>/dev/null || true
      rm -f "$out"
      log "probe timed out after ${HEALTH_TIMEOUT}s -> treating as unhealthy"
      return 1
    fi
    sleep 1; waited=$((waited + 1))
  done
  wait "$probe"; local rc=$?
  # An unhealthy probe's output is the 3am diagnosis — log it, don't discard it.
  (( rc != 0 )) && [[ -s "$out" ]] && log "probe output: $(head -c 500 "$out")"
  rm -f "$out"
  return $rc
}

# ---- ADAPT 3: ownership ------------------------------------------------------------
# Only needed when interactive sessions can claim the same resource. Decide ownership by
# reading the claim record and kill -0 on its pid — instant, unlike a status round-trip.
# Stale records for dead pids are normal; always liveness-check before trusting one.
claim_holder_pid() {
  [[ -f "$CLAIM_FILE" ]] || return 1
  local pid; pid="$(sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' "$CLAIM_FILE" | head -1)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && printf '%s' "$pid"
}

# ---- ADAPT 4: start the child ------------------------------------------------------
# Run it as a CHILD. Never exec: an exec'ing supervisor becomes the job and can no longer
# act on a wedge. `set -m` above gives each background job its own process group, so
# $CHILD_PID is also the group id cleanup() kills.
start_child() {
  # e.g. myprogram --target "$TARGET" &
  true & CHILD_PID=$!
  log "started child pid=$CHILD_PID"
}

# ---- The loop ----------------------------------------------------------------------
mkdir -p "$CLAIM_DIR"
backoff="$BACKOFF_MIN"

while true; do
  # Yield while a live owner holds the claim; reclaim the moment it frees.
  if holder="$(claim_holder_pid)"; then
    if bounded_is_serving; then
      log "target served by pid=$holder — yielding"
      sleep "$HEALTH_INTERVAL"; continue
    fi
    # Identity check BEFORE signalling. The claim record can be stale and its pid
    # recycled by an unrelated process of the same user; a KILL escalation against
    # a mis-identified pid kills a bystander. ADAPT: match your own program.
    holder_cmd="$(ps -o command= -p "$holder" 2>/dev/null || true)"
    case "$holder_cmd" in
      *"$EXPECT_HOLDER_CMD"*) ;;
      *) log "pid=$holder does not look like our program ($holder_cmd) — leaving it alone"
         sleep "$HEALTH_INTERVAL"; continue ;;
    esac
    # Only use the group form when the holder actually LEADS a group. The
    # identity check above validated a PID; `kill -- -$holder` targets whatever
    # group has that PGID, which for a non-leader (an interactive session, per
    # ADAPT 3) is somebody else's group — the incumbent survives, a bystander
    # group dies, and the loop starts a second instance anyway.
    if [ "$(ps -o pgid= -p "$holder" 2>/dev/null | tr -d ' ')" = "$holder" ]; then
      holder_target="-$holder"
    else
      holder_target="$holder"
    fi
    log "pid=$holder holds the claim but is not serving — evicting"
    # Group-kill, matching cleanup() and the probe timeout: a TERM'd incumbent can
    # reap its own children, but a KILL'd one cannot, so its grandchildren would
    # survive still holding the resource we are about to bind.
    kill -TERM "$holder_target" 2>/dev/null || true
    # Confirm it actually died before starting our own child — TERM can be ignored
    # or slow to drain, and two live instances is the exact state a single-instance
    # supervisor exists to prevent.
    for _ in $(seq 1 10); do kill -0 "$holder" 2>/dev/null || break; sleep 1; done
    if kill -0 "$holder" 2>/dev/null; then
      kill -KILL "$holder_target" 2>/dev/null || true
      sleep 1
    fi
  fi

  started_at=$SECONDS
  start_child

  # Watch the CHILD's health, not its liveness.
  while kill -0 "$CHILD_PID" 2>/dev/null; do
    sleep "$HEALTH_INTERVAL"
    if ! bounded_is_serving; then
      log "child pid=$CHILD_PID alive but not serving — restarting on health, not on exit"
      cleanup; CHILD_PID=""
      break
    fi
    backoff="$BACKOFF_MIN"   # a healthy interval resets the backoff
  done

  wait "$CHILD_PID" 2>/dev/null || true
  ran_for=$((SECONDS - started_at))
  CHILD_PID=""

  # Back off on FAST failure only: an expired credential costs one log line every few
  # minutes instead of a hot restart loop.
  if (( ran_for < FAST_FAIL_SECONDS )); then
    log "child died after ${ran_for}s — backing off ${backoff}s"
    sleep "$backoff"
    backoff=$(( backoff * 2 )); (( backoff > BACKOFF_MAX )) && backoff=$BACKOFF_MAX
  else
    log "child exited after ${ran_for}s — restarting"
    sleep "$BACKOFF_MIN"
  fi
done
