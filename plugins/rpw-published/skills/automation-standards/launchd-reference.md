# launchd reference and job audit checklist

macOS specifics for `SKILL.md`. LaunchAgents live in `~/Library/LaunchAgents/<label>.plist`
and run in the `gui/$(id -u)` domain.

## Required keys for a persistent (always-on) job

| Key | Value | Why |
|---|---|---|
| `Label` | reverse-DNS, matches the filename | how every `launchctl` verb addresses it |
| `ProgramArguments` | **the supervisor**, not the program | Rule 0 — `KeepAlive` cannot see a wedge |
| `ProcessType` | explicit — `Interactive` for latency-sensitive/always-on | absent ⇒ "light resource limits", throttled CPU/I-O |
| `RunAtLoad` | `true` | starts at login without a manual step |
| `KeepAlive` | `true` | restarts on exit — the *floor*, not the health story |
| `ThrottleInterval` | `60` | without it a failing job restarts hot (default 10s) |
| `WorkingDirectory` | absolute | launchd's cwd is `/` |
| `EnvironmentVariables` | at minimum `PATH`, plus `HOME` for daemons | launchd inherits almost nothing from your shell |
| `StandardOutPath` / `StandardErrorPath` | absolute, **outside `/tmp`**, rotated | `/tmp` is purged; unrotated logs reach gigabytes |
| `ExitTimeOut` | explicit if shutdown needs draining | default 20s, then `SIGKILL` |

## Required keys for a scheduled job

Same as above minus `KeepAlive`, plus:

| Key | Value | Why |
|---|---|---|
| `StartCalendarInterval` / `StartInterval` | the schedule | `StartCalendarInterval` fires on wake if the machine was asleep; a machine that was **off** misses the slot entirely |
| `ProcessType` | `Background` for bulk work, stated deliberately | a nightly bulk job should not compete with the UI |
| `AbandonProcessGroup` | leave **false** (default) | true lets children outlive the job — the leak Rule "cleanup" exists to prevent |

Wrap the payload in a script with `set -euo pipefail` and a run-record append. A
`ProgramArguments` of `["/bin/zsh","-c","a; b"]` reports only `b`'s exit status, so launchd's
`last exit code` becomes structurally incapable of reporting a failure of `a`.

## Operating (all read-only except the last two)

```sh
launchctl print gui/$(id -u)/<label>          # state, pid, runs, last exit, spawn type
launchctl print gui/$(id -u)/<label> | grep -E 'state|pid = |last exit|runs = |spawn type'
launchctl list | grep <label>                 # quick triage
launchctl bootout    gui/$(id -u)/<label>     # unload  (mutates)
launchctl bootstrap  gui/$(id -u) <plist>     # load    (mutates)
```

`spawn type` is the *effective* classification. Read it after every reload — it is the only
proof `ProcessType` took.

## Audit checklist

Answer each with evidence from the plist plus `launchctl print`. "Looks fine" is not an
answer; name the key or the observed value.

**Health**

1. What is this job's serving predicate — the one command that proves it is serving? If the
   answer is "it's running", the job has no health definition.
2. Does `ProgramArguments` point at a supervisor that can restart on that predicate, or does
   it exec the program directly under `KeepAlive`?
3. Does anything monitor this job? Does that monitor evaluate the predicate, or only
   `launchctl` signals?

**Resources**

4. Is `ProcessType` present? Does `spawn type` show the class you intended?
5. Is `ThrottleInterval` set for a `KeepAlive` job?

**Serving (if it binds a port)**

6. Is the port allocated and recorded, or hard-coded in the plist/args?
7. Do consumers resolve the recorded port, or repeat a constant?
8. Is there a readiness endpoint that touches real dependencies?

**Scheduling (if scheduled)**

9. Where is the durable record that a run happened, and what does the consumer do when it
   goes stale?
10. Is the exit status meaningful, or flattened by `;` chaining or `2>/dev/null`?
11. Is overlap prevented by a lock?

**Cross-cutting**

12. Where do the logs go, how big are they now (`ls -lh`), and what rotates them?
13. Does the job spawn children? What kills them if the job is `SIGKILL`ed?
