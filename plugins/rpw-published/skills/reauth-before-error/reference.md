# Reference: one-click Salesforce reauth

Worked reference for the `reauth-before-error` skill. The example is a single-user local web app
(FastAPI backend + web UI) wrapping the `sf` CLI; the Salesforce session token expires
roughly every two days. Before #93, the banner told the user to copy-paste
`sf org login web` into a terminal. After, the banner has a primary button and the backend
runs the flow itself.

Use this as the template shape when implementing the skill in a new app. The pieces
generalize to any wrapped login CLI (`databricks auth login`, `gcloud auth login`,
`gh auth login`, `az login`, `aws sso login`).

## The three moving parts

### 1. Launch endpoint — `POST /api/auth/login`

- Spawns `sf org login web --instance-url <My Domain> --json` **in the background** and
  returns immediately with `{"started": true, "login_in_progress": true}`. The HTTP request
  does not block on the human's browser click-through.
- **Single-flight**: if a flow is already pending, the endpoint returns an
  already-running response instead of spawning a second browser window. Implement as an
  in-process flag/lock checked-and-set atomically before spawning.
- **Time-bounded at 300s** — generous enough for SSO + MFA, finite enough that an
  abandoned window releases the in-progress flag.
- **Guarded like every other process-spawning route**: same CSRF/origin checks; no request
  data flows into the spawned command's arguments.
- **Login target from env, not from the request**: `SF_INSTANCE_URL` overrides the
  instance URL (default: the org's My Domain, which lands directly on SSO instead of the
  generic vendor login page). The equivalent knob exists for most CLIs (profile, tenant,
  project flags).

### 2. Status endpoint — `login_in_progress` + `login_error`

`/api/status` (already polled by the UI) gained two fields:

- `login_in_progress: bool` — true from spawn until the subprocess exits. Drives the
  banner's waiting state and doubles as the client-visible single-flight signal.
- `login_error: str | null` — on failure, the **real** reason (subprocess stderr / parsed
  CLI JSON error), cleared when a new flow starts.

On success, the completion handler calls the internal `_mark_auth(ok=True)` — flipping the
**TTL-cached auth verdict immediately**. This detail matters: the application caches the
sf-session check with a 60s TTL, and without the explicit flip the banner survived a
successful login for up to a minute, making the feature look broken.

### 3. The banner (AuthBanner)

- Persistent (not a toast) while `auth_ok` is false.
- Primary button **"Log in to Salesforce"** → `POST /api/auth/login`.
- While `login_in_progress`: waiting copy — *"Complete the SSO login in the browser window
  that just opened."* — button disabled.
- On success (status poll shows auth ok): clear the banner, toast, and **re-sync the data
  the expired session had blocked** (auto-resume).
- On `login_error`: show the actual message; keep the terminal command visible as the
  fallback, plus a **Retry** button for sessions fixed outside the app (e.g. the user ran
  the CLI themselves).

## Test coverage that locked it in

The PR's backend tests are a good checklist for any implementation of this pattern:

1. **Successful login marks auth ok** — completion flips the cached verdict, status shows
   `auth_ok: true` without waiting out the TTL.
2. **Single-flight under concurrent clicks** — two simultaneous `POST /api/auth/login`
   calls spawn exactly one subprocess; the second gets already-running.
3. **Failure records `login_error` and keeps auth expired** — no false-positive session
   restore.
4. **Timeout surfaces an error** — the 300s bound expiring produces a visible
   `login_error`, and the in-progress flag is released.
5. **Endpoint guards** — happy path, already-running, and forbidden-origin (CSRF)
   responses.

## Verifying without real SSO: the stub-binary trick

You cannot unit-test a live SSO click-through, and you should not need to. The PR
validated the real wiring by running the backend with a **stub `sf` binary on PATH**:

- The stub logs its argv and sleeps, then exits 0.
- `POST /api/auth/login` returned `{"started": true, "login_in_progress": true}`.
- Status showed `login_in_progress: true` while the stub slept, `false` after it exited.
- The stub's log confirmed the exact invocation
  (`org login web --instance-url https://example.my.salesforce.com --json`).

This verifies spawn, argument construction, state transitions, and completion handling —
everything except the browser itself. Do the same with a stub `databricks`/`gcloud`/etc.
when porting the pattern.

## Scheduler interaction

An application's background sync can also hit the expired session. Under this
pattern, the scheduler marks auth expired and **stops** — it never calls the launch
endpoint. Browser windows opening with nobody at the keyboard is the failure mode this
guardrail exists to prevent. The one-click launch is exclusively user-initiated.
