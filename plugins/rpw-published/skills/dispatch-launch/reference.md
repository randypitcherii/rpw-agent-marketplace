# dispatch-launch reference — surface, measured behavior, parity gaps

Deep detail backing [SKILL.md](SKILL.md). Substrate: the local omnigent server at
`http://127.0.0.1:6767`, verified 2026-08-14 against the installed `omnigent`
(`server/schemas.py`, `server/routes/_sessions/orchestration.py`).

## `POST /v1/sessions` — full field surface

`openapi.json` describes this route with **no `requestBody`**, so introspecting the
spec tells you nothing. The authority is `SessionCreateRequest`:

| Field | Notes |
|---|---|
| `agent_id` | **required.** From `GET /v1/agents`. |
| `initial_items` | list of `SessionEventInput`. **History-only when no runner is bound yet** — see [liveness-and-surfacing.md](liveness-and-surfacing.md). |
| `title` | **200-char cap** — 201 chars is a 422 `string_too_long`, a refused create rather than a truncation (measured 2026-09-16). `/` is stored as a space. `PATCH /v1/sessions/{id}` caps at 200 too; the 60 belongs to the `sys_session_rename` tool schema, which is a different route ([session-lifecycle.md](session-lifecycle.md)). |
| `labels` | free-form `dict[str, str]`. |
| `parent_session_id` / `sub_agent_name` | make the new session a child. Omit for a top-level dispatch. |
| `host_type` | `"external"` (default) or `"managed"`. |
| `host_id` | **required whenever `git` or `workspace` is set** — 422 otherwise. |
| `workspace` | absolute path, must exist, must fall inside the agent's `os_env.cwd` boundary. Tilde/relative rejected. |
| `git` | `SessionGitOptions`; requires `host_id`. |
| `terminal_launch_args` | `list[str]` passed to the harness, e.g. `["--permission-mode","acceptEdits"]`. |
| `model_override` / `reasoning_effort` | per-launch. **No Superset CLI equivalent existed.** |
| `cost_control_mode_override`, `subagent_routing_override`, `harness_override`, `smart_routing_override` | advanced; leave unset for dispatch. |

```python
class SessionGitOptions(BaseModel):
    branch_name: str
    base_branch: str | None = None      # create mode only (fork point)
    existing_worktree: bool = False     # True = bind to the worktree at `workspace`
```

`SessionEventInput` is a `type` discriminator plus free-form `data`. For a user turn:

```json
{"type": "message",
 "data": {"role": "user", "content": [{"type": "input_text", "text": "…"}]}}
```

## The routes dispatch actually uses

| Call | Purpose |
|---|---|
| `GET /v1/hosts` | online host ids |
| `GET /v1/agents` | agent ids + harness |
| `GET /v1/projects` | registered projects (may legitimately be empty — dispatch does not need one) |
| `POST /v1/sessions` | create |
| `POST /v1/sessions/{id}/events` | **wake / nudge / interrupt** — the only way to start or continue a turn. Returns `202 {"queued":true,"pending_id":"…"}`. Not present in `openapi.json`; it is real. |
| `GET /v1/sessions/{id}` | snapshot: `status`, `runner_online`, `items`, `pending_inputs`, `pending_elicitations`, `last_task_error`, `workspace`, `git_branch` |
| `GET /v1/sessions/{id}/resources/terminals` | the tmux socket/target behind the session |
| `PATCH /v1/sessions/{id}` | rename — the **manual** one; `sys_session_rename` posts to `POST …/auto-title` instead |
| `DELETE /v1/sessions/{id}` | close |

`POST /v1/sessions/{id}/comments*` is the **review-comment** surface, not a message
channel — do not try to seed work through it.

The `omnigent` CLI is **not** a session-creation surface: `omnigent session` exposes
only `export` and `import` (verified 2026-08-14), and `omni <harness>` launches a
harness in the current cwd rather than taking a workspace argument. Everything above is
plain HTTP, which is what makes non-agent callers (a Raycast script, a Makefile target)
able to dispatch at all.

## Measured session behavior (2026-08-14, #739)

Verified by creating a real bind-mode session against a throwaway worktree and having
it run a six-probe brief. Do not re-derive these.

| Question | Answer |
|---|---|
| Does a bound-workspace session start in its worktree? | **Yes** — `pwd` == the bound `workspace`, no `cd` needed. |
| Does cwd persist across separate Bash calls? | **Yes.** |
| Does a stray `cd` leak into the next call? | **No** — the harness reports `Shell cwd was reset to <workspace>` and the next call is back in the worktree. |
| Do relative file reads resolve to the worktree? | **Yes** — bare `AGENTS.md` read the worktree's own file. |
| Does bare `git` resolve to the worktree's branch? | **Yes** — `git rev-parse --abbrev-ref HEAD` returned the bound branch with no `-C`. |
| Is `$OMNIGENT_RUNNER_WORKSPACE` set? | **Yes**, equal to the bound workspace. runner authentication is also present but is a **credential**, not a session ID. |
| Does `initial_items` alone start work? | **No.** See below. |

**Consequence:** a bind-mode (path A) dispatch needs **no Step 0 relocation block**.
That block is mandatory only on the MCP `sys_session_create` path (path B, the one
`wave-kickoff` uses), which has no `workspace` field and so inherits the parent
session's cwd.

### The `initial_items` trap, in the server's own words

`POST /v1/sessions` dispatches `initial_items` to the bound runner *if one is bound*.
For an external host the runner is provisioned asynchronously, so at create time it
usually is not:

> No runner bound — persist initial items as history-only seed via the conversation
> store. No execution fires; the caller is responsible for binding a runner and
> posting a follow-up event if they want the agent to react.

Live signature: `status: idle`, `runner_online: true`, `pending_inputs: []`,
`last_task_error: null`, terminal resource `running: true`, and exactly two items —
the seed `message` (tagged `response_id: "seed"`) and one `session.resource.created`
event. Indistinguishable from healthy at a glance. One `POST /v1/sessions/{id}/events`
moved it to `running` within 10s and it completed its brief in ~50s with nine
`function_call` items.

This is the omnigent-era analogue of the Superset `ok:true` trap, and it is why
[liveness-and-surfacing.md](liveness-and-surfacing.md)'s history gate is mandatory.

## Superset → omnigent primitive mapping

Everything the retired `superset-launch` skill needed, and where it lives now.

| Superset | Omnigent |
|---|---|
| `superset auth login` / `whoami` | none — local server, no auth, no org |
| `workspaces create --project <id>` | `workspace` (absolute path) + `GET /v1/projects` |
| `--branch` | `git.branch_name` |
| `--base-branch` | `git.base_branch` (create mode) |
| `--local` / `--host` | `host_id` from `GET /v1/hosts` |
| `--agent <HostAgentConfig UUID>` | `agent_id` from `GET /v1/agents` |
| `--prompt` | `POST /v1/sessions/{id}/events` (the wake) |
| HostAgentConfig args (`--permission-mode …`) | `terminal_launch_args` |
| **no `--model` / `--effort` on the CLI** | `model_override` + `reasoning_effort` — **new capability** |
| `workspaces get -f worktreePath` | the session snapshot's `workspace` |
| host branch prefixing (`fix/x` → `superset/fix/x`) | none — the branch you name is the branch you get |
| `agents create` respawn-in-place | re-POST the wake event (keeps context) |
| `lsof +D` / prompt-grep liveness probes | the session's `items` history |
| focus deep link + upstream pane-registration bug | the session rail; no pane, so no bug to work around |
| `workspaces update --name` | `PATCH /v1/sessions/{id}` |
| `workspaces delete --local` (removed the worktree) | `DELETE /v1/sessions/{id}` **plus** `git worktree remove` — separate lifetimes |
| `$SUPERSET_WORKSPACE_PATH` | `$OMNIGENT_RUNNER_WORKSPACE` |
| Legacy process id | Runner authentication value (a credential — never echo it or treat it as a session id) |
| `$SUPERSET_WORKSPACE_ID` | none — the session id must be passed in the brief |
| `$SUPERSET_ROOT_PATH` | none — `dirname "$(git rev-parse --git-common-dir)"` |
| `$SUPERSET_TERMINAL_ID` | `GET /v1/sessions/{id}/resources/terminals` |

## Parity gaps carried forward, explicitly

Full analysis and the blocker-vs-acceptable verdicts:
ADR-2026-08-14 (Omnigent dispatch).
Summary of what a dispatcher must live with:

- **No `$SUPERSET_ROOT_PATH` equivalent.** Derive the main clone from git; any doc that
  used the env var needs the `git rev-parse --git-common-dir` form.
- **No session-id env var.** Self-referential work (self-rename, self-close) needs the
  id supplied in the brief.
- **No cwd binding on the MCP path (#795).** Path B keeps the Step 0 relocation block.
- **No structured title on the CLI path.** `omni <harness>` has no `--title`; the
  server auto-derives one from the first ~60 characters, so put the short
  work-summary first to make that title useful. `sys_session_rename` is the *auto*
  titler and refuses any title a human already set (`title_changed`), so
  `make session-rename` / `PATCH /v1/sessions/{id}` is the manual path — the only
  one that takes a structured title ([session-lifecycle.md](session-lifecycle.md)).
- **Create ≠ running (#974).** Compensating control: the mandatory history gate.
- **Permission elicitations can stall an unattended session (#972).** `acceptEdits`
  is not the mitigation: it covers edit tools only, and a supervisor launched with it
  stalled on its first `mcp__omnigent__sys_*` call. Unattended, supervisor-grade launches
  take `terminal_launch_args: ["--permission-mode","bypassPermissions"]`; the resolve
  route for an already-wedged session is in
  [liveness-and-surfacing.md](liveness-and-surfacing.md).
- **Completion signals can lie (#971).** Verify with history and artifacts (commits, PR
  state), never with a self-reported "done".
- **Terminal death mid-run (#824).** Briefs must commit early and often, and anything
  that can outlive a session stays launcher-owned (#495).

## Delivery mode — why the brief is the only gate

A dispatched headless `/build` runs to completion with no human in the loop. It
**self-certifies** the Phase 3d human-validation receipt, and with no branch protection
on the repo it **auto-merges** at Phase 5d.5 — observed live: #188 → the agent merged
its own PR #192. So the brief's closing delivery line ("open a PR, then STOP" vs "open
a PR and merge") is the only thing standing between a dispatch and an unattended merge.
Default to Gate; state the mode in the Step 7 report.

## Long launch messages

Keep the launch message to one line pointing at the brief file. The Superset-era
evidence was a ~2,000-char `--prompt` spawn-dying 2/2 while a ~100-char one spawned
alive 1/1 — argv-through-PTY fragility at length, which still applies verbatim to
path C's `omni … -p`. Path A's event POST is JSON over HTTP rather than argv, so the
mechanism does not obviously transfer there, but the brief-file pattern costs nothing,
keeps the work reviewable on disk, survives a relaunch, and is what every proven
dispatch in this repo uses. Not worth re-testing the failure to find out.
