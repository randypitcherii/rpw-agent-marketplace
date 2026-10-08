---
name: automation-standards
description: House standard for automation that runs with no human watching — background processes, long-lived localhost servers, and scheduled jobs. Anchored on liveness-is-not-health — an alive-but-serving-nothing process defeats KeepAlive and every process-level check. Use when writing, reviewing, or debugging a LaunchAgent, launchd plist, systemd unit, cron or scheduled job, watchdog, health check, health endpoint, port binding, or localhost serving.
---

# Automation Standards

Three modes — **background processes**, **localhost serving**, **scheduled jobs** — and one
rule that outranks everything else in all three.

Companion files: [launchd-reference.md](launchd-reference.md) for the macOS key-by-key
contract and the audit checklist; [supervisor-pattern.sh](supervisor-pattern.sh) for a
runnable watchdog skeleton.

## Rule 0 — liveness is not health

**A process that is alive is not a process that is serving.** The dominant failure of
long-running automation is not a crash. It is a wedge: a connection retry loop that never
gives up, a worker thread that died inside a live process, a server holding its socket while
every request 500s. It never exits, so:

- `KeepAlive` / `Restart=always` **never fire** — they restart on *exit*, and this never exits.
- The job reports `state = running`, `runs = 1`, `last exit code = (never exited)` forever.
- Every process-level check — pid present, restart count low, exit status clean — says healthy.

A twelve-hour outage produced exactly this shape: process online, service offline, all
supervisors green the entire time.

### The detection pattern

For every persistent job, define a **serving predicate** — one out-of-band command whose
output proves the job is doing its job — and make it the *only* definition of health.

1. Name the predicate in the job's own docs (`curl -fsS localhost:$PORT/readyz`,
   `<cli> status | grep -q 'state=online'`, "row count for today > 0").
2. A supervisor polls it and restarts the child **when the predicate fails**, not when the
   child exits ([supervisor-pattern.sh](supervisor-pattern.sh)).
3. Anything that *monitors* the job evaluates the same predicate. A monitor that reads only
   `launchctl`/`systemctl` inherits the supervisor's blind spot and will report a wedged job
   as `ok`.

Probes are expensive and can hang. Rules for any probe: **time-cap it with your runtime's
native mechanism** (a `subprocess` timeout in Python, `--max-time` on curl; only pure shell
needs the background-and-poll-`kill -0` dance, since macOS has no `timeout(1)` —
[supervisor-pattern.sh](supervisor-pattern.sh) shows it), **rate-limit/cache it**, degrade to `unknown`
rather than raising, and never let it block the monitor's fetch. Keep the cadence sparse —
a probe competes with the job it measures inside the same scheduler coalition, so an
aggressive poll worsens the starvation it exists to detect.

Absent health evidence is a state of its own: *"restart-managed, pid present, no successful
probe for N minutes"* is **stale**, not `ok`.

## Rule 1 — resource classification is a required decision

Schedulers classify jobs, and the default is rarely what you want. On macOS a plist with **no
`ProcessType`** is treated as a background daemon and given "light resource limits"
(`launchd.plist(5)`) that throttle CPU and I/O.

That throttling caused the outage above, through a chain nobody would guess:

1. Under machine load, the throttled job starved.
2. A dependency's **5-second version probe timed out** (0.025s when idle).
3. On timeout the SDK **silently omitted `--force-refresh`** and served a **stale token**.
4. Auth then failed at the network layer — while the process stayed alive. See Rule 0.

So: **every persistent job states its resource class explicitly, with a one-line reason.**

| Platform | Key | Note |
|---|---|---|
| launchd | `ProcessType` — `Interactive` \| `Adaptive` \| `Standard` \| `Background` | Absent ⇒ throttled. Latency-sensitive/always-on ⇒ `Interactive`. |
| systemd | `CPUWeight`, `IOWeight`, `Nice` | Also `CPUQuota` for bulk jobs. |

**Verify it took**, don't assume the file is the truth:
`launchctl print gui/$(id -u)/<label> | grep 'spawn type'` must show `interactive`, not
`daemon`.

## Mode A — background processes

- **Supervise a child; never `exec`.** A supervisor that `exec`s becomes the job and can no
  longer act on a wedge. Point the job at the supervisor, not at the program.
- **Restart on unhealthy, not on exit** (Rule 0).
- **Back off on fast failure.** Exponential backoff with a cap, so an expired credential
  costs one log line every few minutes instead of a hot restart loop. Set a restart throttle
  (`ThrottleInterval`, `RestartSec`) explicitly — the platform default is seconds.
- **Single-instance ownership needs an explicit protocol** when interactive sessions can
  claim the same resource. Write a claim record (`target`, `pid`) to a known path; decide
  ownership by reading it and `kill -0` on the pid — instant, unlike a status round-trip.
  The persistent job **yields** while a live owner holds the claim, **claims** the moment it
  frees, and **evicts** an owner whose serving predicate fails. Stale records for dead pids
  are normal; always liveness-check before trusting one.

## Mode B — reliable localhost serving

- **Allocate, don't assert.** Ask for a preferred port, take a nearby free one when it is
  busy, record what you actually bound, and make consumers resolve from the record. Full
  standard: `docs/process/local-ports.md` in `rpw-agent-marketplace`. A hard-coded port under
  a restart-always supervisor is worse than a crash: it is a restart loop fighting the
  incumbent.
- **Never print, log, link to, or open the *preferred* port.** Report the bound one.
- **Split readiness from liveness.** `/healthz` = the process can answer. `/readyz` = the
  dependencies this service needs are usable and a real request would succeed. Only `/readyz`
  is the serving predicate.
- **A health endpoint must exercise the serving path.** An endpoint that returns `{"ok":true}`
  from the web framework proves the framework is up and nothing else. Touch the database, the
  queue, the upstream token — cheaply, with a cap. Include version + git hash so drift is
  visible (see the `versioning-standards` skill).
- **Reclaim, don't fight.** On start, if the preferred port is held, probe nearby free ports,
  bind one, and record the bind — never loop retrying the incumbent's port. The allocation and
  stale-record semantics are `local-ports.md`'s to define; follow it rather than this summary.

## Mode C — scheduled jobs

- **Prove the run happened.** A schedule is not evidence. Append a run record — start,
  finish, exit status — to a durable path. "No output" and "never ran" must not look alike. Notifications out of a scheduled job use the five-state status line ([`../communication/references/status-updates.md`](../communication/references/status-updates.md)) — `STOPPED` is not `FAILED`.
- **Keep the exit status meaningful.** `a; b` reports only `b`'s status, and blanket
  `2>/dev/null` destroys the only diagnosis you will get at 3am. Use `set -euo pipefail`,
  and let stderr reach the log.
- **Detect missed runs from the consumer side.** Whoever depends on the output checks the
  freshness of the run record and alarms on staleness. Nothing else notices a job that
  silently stopped firing.
- **Prevent overlap explicitly** with a lock (`flock`, or an atomic lockfile carrying the pid)
  when a run can outlast its interval. Do not rely on the scheduler's claim that it won't
  double-start.
- **Log somewhere durable.** Not `/tmp` — it is periodically purged, so the only evidence a
  scheduled job produces is the evidence most likely to vanish.

## Cross-cutting

**Cleanup — nothing outlives its parent.** Anything that spawns children installs a trap and
kills the child's process *group*, because `kill $(jobs -p)` misses reparented subshells and
never runs at all if the shell is killed. The canonical shape is
[supervisor-pattern.sh](supervisor-pattern.sh)'s `cleanup()`: run the child in its own process
group, then TERM that group, wait briefly, and KILL what remains. (macOS ships no `setsid(1)`
— give the child its own group with `set -m` job control or a small POSIX `setsid` shim; a
plain `&` child shares your group and a group-kill will miss its subprocesses.)

Belt and braces: prefer **self-limiting** children (`timeout 60 …`, `stress-ng --timeout`)
over unbounded loops, so orphans die on their own even when cleanup never runs. A leaked set
of unbounded busy loops once held a machine at load ~300 for twelve hours after its worktree
was deleted — and that load is what triggered Rule 1's throttle chain.

**What a job prints is agent context.** Hold every command it runs to the house CLI output
contract: `docs/process/cli-output-contract.md` in `rpw-agent-marketplace`.

**Log rotation is not optional.** `StandardOutPath` / `StandardErrorPath` and their
equivalents grow forever, and a crash-looping job produces gigabytes. Cap every long-lived
job's logs by size (`newsyslog.d`, `logrotate`, or rotation inside the app) at install time,
not after the disk fills.

## Reviewing an existing job

Run the checklist in [launchd-reference.md](launchd-reference.md). It is written to produce
specific findings — the failure mode of a review here is generic advice.
