# Load / stress harness safety (#644)

Companion to [SKILL.md](SKILL.md) section 5. Read this before dispatching — or
being — an agent whose task generates CPU/IO load: reproducing a timing bug,
verifying a flake fix under contention, benchmarking under pressure.

## The failure this exists to prevent

A worker reproducing a test flake under CPU stress used an inline harness:

```sh
for i in $(seq 1 24); do (while :; do :; done) & done
STRESS_PIDS=$(jobs -p)
# … 22 pytest runs …
kill $STRESS_PIDS 2>/dev/null   # did not reap them
```

`jobs -p` listed the subshells, not the loops they had already reparented. The
harness ran twice, so **48 unbounded busy loops were orphaned to PID 1** and spun
for **11h40m** at ~116 CPU-minutes each. Machine load sat at **~275–300** for
almost twelve hours, then fell to 6.3 within five minutes of killing them.

The wave deleted the worker's worktree while the processes survived it, so
nothing on disk pointed back at the cause. The collateral damage was worse than
the wasted CPU: a launchd-managed service classified as a background daemon got
throttled under the load, which starved a 5-second CLI auth probe, which made an
SDK silently serve a **stale token** — a live host that appeared up and served
nothing, for half a day, with no error anywhere.

## The three rules

Apply all three. Each covers a different way cleanup fails to run.

### 1. Bounded tools over unbounded loops

Prefer a harness that terminates by construction, so it dies on its own even if
cleanup never runs at all:

```sh
timeout 120 <load-command>
stress-ng --cpu 8 --timeout 120s          # purpose-built; self-limiting
for i in $(seq 1 5000000); do :; done &   # counted, not `while :`
```

**Never** `while :; do :; done` or `while true` without a bound. An unbounded
loop that escapes cleanup runs until the machine is rebooted.

### 2. `trap` before the first spawn

Install cleanup **before** any background job exists, not after the spawn loop —
a harness interrupted between spawn and `trap` is exactly the gap #644 fell
through. `EXIT` alone is not enough; catch the signals a supervisor or a killed
terminal actually sends:

```sh
trap 'kill -- -$$ 2>/dev/null' EXIT INT TERM
```

### 3. One killable process group

`kill $(jobs -p)` reaps job leaders, not their reparented children. Put the load
in its own process group and kill the group:

```sh
set -m                                  # job control on: each job gets its own group
<load-command> &
PGID=$!                                 # group id == leader pid under `set -m`
# … work …
kill -- -"$PGID" 2>/dev/null            # negative pid = whole group
```

## Verify before the turn ends

Cleanup that was never checked is cleanup that did not happen. Before reporting,
confirm nothing survives:

```sh
make wave-sweep WORKTREE="<worktree-path>"   # 0 clean / 1 survivors / 2 UNPROVABLE
uptime                                      # load average back near idle

# Second signal for a harness whose argv no longer names the worktree. Needs a
# readable process table; `/bin/ps` is DENIED in the sandbox waves run inside
# (#1785), so when it errors say the CPU sweep was NOT run — silence from a
# denied `ps` is not an idle machine.
ps -axww -o pid,etime,%cpu,command | awk '$3 > 50 {print}' | grep -v grep
```

`outcome=clean` is the pass condition — **not** empty output, and **not**
`outcome=unprovable`, which means no reader could read the process table so the
cleanup is unverified (#1785). A survivor is a **blocker to report with its
PID**, not a footnote — and it must be killed, because the worktree that would
explain it is about to be deleted. An unprovable sweep is reported as
unprovable; the one thing it may never be reported as is clean.

## Dispatch-side obligations

- Say it in the prompt. An agent given a load-generation task gets these rules in
  its brief; wave workers get them from
  [`worker-brief-template.md`](../wave-supervisor/worker-brief-template.md).
- Sweep at teardown. Whoever deletes the worktree checks for processes still
  referencing it first — for waves, that is the close-out sweep in
  [`merge-and-closeout.md`](../wave-supervisor/merge-and-closeout.md).
