# One watcher per watched resource

Companion to [SKILL.md](SKILL.md) Rule 0.

**One background watcher owns one watched resource** — a CI run, a deploy, a job id, a
pid, a log file. A second watcher on the same resource adds no health signal: both fire
at the same moment with the same news, and a human has to establish twice that nothing
new happened. Two watchers is redundant liveness reporting, not more health.

## Before registering a watcher

1. **Key it by the resource.** Put the resource's id in the watcher's own name or argv —
   a run id, a pid, a session id — so a later check can find it by that id. A watcher
   named `wait` or `monitor` cannot be found again.
2. **List what is already watching it, by that id**, from the source that owns the
   watchers: the harness's background-task list for in-session watchers, `pgrep -fl
   <resource-id>` for processes, the scheduler's job list for scheduled ones.
3. **An existing watcher on that id → reuse it.** Read its output, or extend its
   timeout. Do not add a second. Replace it only by stopping the first and confirming
   it is gone (re-read the list; an exit code is not proof of death).
4. **The list could not be read → say so.** An unreadable list is not an empty one
   ([unasked-is-not-no.md](unasked-is-not-no.md)); register only after stating that
   the check was blind.

A watcher is also a child: bound it (a timeout or a counter, never an unbounded poll)
and stop it when its resource reaches a terminal state.
