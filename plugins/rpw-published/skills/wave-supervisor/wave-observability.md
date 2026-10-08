# Wave observability page — bring-up, port resolution, honest scope

Companion to [SKILL.md](SKILL.md) step 2 (#531/#1136). The wave's live artifacts —
`WAVE-STATE.md`, `.wave/worker-<issue>.meta.json`, `.wave/worker-<issue>.log` —
already have a purpose-built reader: the **waves** panel in
`projects/build-observability` (#705). Step 2 is where it becomes meaningful,
because step 2 is what creates the files it reads.

**Why this is REQUIRED and not a nicety:** without it the only view of a wave is
the supervisor's own poll narration, so every "how is it going" round-trips
through agent context, and a supervisor that dies mid-wave takes the only view
with it — while the artifacts on disk stay perfectly readable.

## Bring-up (idempotent — check before you start)

Already-running is the common case; a wave-per-day machine starts it once.

```bash
cd projects/build-observability
make ports                 # a live record for both services? then it is up — skip ahead
make install               # first run on this machine only: uv sync + npm install
make dev                   # backend + vite; both print the URL they bound
```

- **`make install` is not optional on a fresh checkout.** A missing
  `frontend/node_modules` surfaces as `sh: vite: command not found`, which reads
  like a broken Makefile and is really just an un-run `npm install`.
- `make dev` is a foreground pair of dev servers. Start it in its own shell (or
  background it deliberately) — do not park the wave behind it.
- `make clean` in that project stops both.

## Resolve the URL from the registry, never a literal

Local app ports are **allocated and recorded**, not fixed (#535/#654): each
service takes its preferred port or the next free one and writes what it actually
bound to `~/.rpw/ports.json`. Read it; never paste a port number into the wave
plan from memory.

```bash
cd projects/build-observability && make ports
# build-observability.backend.dev  -> http://127.0.0.1:<port>
# build-observability.frontend.dev -> http://127.0.0.1:<port>
```

The **frontend** record is the URL you hand the user. The backend record is what
the vite `/api` proxy resolves for itself — the user never needs it. The waves
view is a tab inside the app, not a separate route, so the instruction is "open
`<frontend URL>`, choose the **waves** tab".

Then record that URL in `WAVE-STATE.md` (`- **Observability:**` in
[`wave-state-template.md`](wave-state-template.md)) so a takeover supervisor
inherits it instead of re-deriving it (#886).

## No registration step

Discovery is one non-recursive scan of the sibling `<repo>-worktrees/` directory
plus the checkout itself, matching any directory that holds `.wave/` or
`WAVE-STATE.md`. **A supervisor worktree is picked up automatically** the moment
step 2 writes those artifacts — nothing to register, nothing to configure.
`RPW_WAVE_ROOTS` pins the roots explicitly if the scan ever misses one (and an
off-value switches the panel off entirely).

## Scope, stated honestly

`projects/build-observability/backend/app/waves.py` reads **local supervisor-side
artifacts only, deliberately not GitHub** — its docstring gives the reason: the
API binds loopback with no auth layer, so a GitHub-authenticated read path would
turn the page into a proxy for the operator's GitHub identity.

| The panel shows | The panel does NOT show |
|---|---|
| worker rows: issue, branch, worktree, model, dispatch mode, status | PR review state, mergeability, CI results |
| dispatch/relaunch counts and the `WAVE-STATE.md` event log | anything from GitHub — labels, comments, claims |
| worker logs, sizes, report counts, the #636 usage line | a wave supervised on another machine |
| open questions and close-out checklist progress | history of a deleted supervisor worktree |

Do not tell the user it shows PR or CI state — merge readiness still comes from
`gh`. And say the per-machine part out loud when it matters: these artifacts are
gitignored and supervisor-local.

## Failure to start is a DISCLOSURE, not a wave blocker

If the page will not come up — install fails, a port is wedged, the panel reports
no supervisor root — **say so in one line and keep supervising.** The wave's state
of record is `WAVE-STATE.md` plus the wave issue; the page is a view over them,
never a dependency of them. A supervisor that stalls a wave on a dev-server
hiccup has made a reader outage into a delivery outage.

Suggested disclosure shape, then move on:

> Observability page didn't start (`vite: command not found` — needs `make
> install` in `projects/build-observability`). Wave proceeding; state is in
> `WAVE-STATE.md` and wave issue #<n>.
