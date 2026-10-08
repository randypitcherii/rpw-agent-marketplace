# Status cascade — how a session record becomes a triage verdict

`scripts/fleet_report.py` implements this; the prose is here so a human can audit
the rules and so the skill can apply them by hand when the script is unavailable.

## Why not just read `status`

Every single field on a session record lies in at least one common case:

| Field | What it looks like it means | What it actually means |
|---|---|---|
| `status: idle` | finished | *either* finished the turn *or* never started (#974). Indistinguishable without history. |
| `runner_online: true` | healthy | the runner has a tunnel. Says nothing about the agent inside it. |
| `status: running` | working | the turn is open. A turn blocked on an invisible permission prompt is also "running" until it times out. |
| a completion claim in history | done | a session can report finished work it never did (#971). Completion is a PR URL, a commit SHA, or a green gate. |
| `runner_online: false` | dead | the runner disconnected. The work may be committed and fine, or the process may have died mid-task (#824). |
| `git_branch` | current branch | the branch the worktree was *created* on. Never the one checked out now. |

The cascade reads two or three fields per verdict for exactly this reason.

## The cascade (first match wins)

Modelled on Agent Orchestrator's `determineStatus`: liveness → activity → thresholds → default.

| # | Condition | Verdict | Priority | Meaning / next move |
|---|---|---|---|---|
| 1 | `status == failed` | **dead** | urgent | Relaunch in place. Do **not** delete the worktree — the brief and any uncommitted work are in it. |
| 2 | `pending_elicitations` non-empty | **needs_input** | urgent | It is waiting on a human, not thinking (#972). Answer it or `omnigent attach`. |
| 3 | `status == running` | **working** | info | Leave it alone. Note the idle time anyway; a "running" turn older than an hour deserves a history peek. |
| 4 | `idle` and runner **offline** | **parked** | info | Finished, or died quietly. Hidden by default; confirm against the artifact (PR / commit) before closing. |
| 5 | `idle`, runner online, history is **seed-only** | **stuck** | urgent | Created, never woken. Post the wake event (`bulk-operations.md`). |
| 6 | `idle`, runner online, idle > threshold (30m) | **stale** | warning | Probably finished and nobody harvested it, or wedged without a prompt. Read the last few history items. |
| 7 | `idle`, runner online, **last message asks you something** | **needs_input** | urgent | It ended its turn on a question, not a report. Answer it (#1800). |
| 8 | `idle`, runner online, **workspace dirty or unpushed with no PR** | **stale** | warning | Mid-implementation, not finished. Nudge for a commit; do not close (#1800). |
| 9 | `idle`, runner online, recently active | **done_candidate** | action | A turn just finished. Verify the artifact, then rename/close/harvest. |
| — | anything else | **stale** | warning | Unrecognised `status`. Log `api_shape_drift`. |

Rules 7 and 8 exist because `done_candidate` was measurably too optimistic, three
times over (#1800):

- **Rule 7 — prose is the only evidence of a question.**
  `pending_elicitation_count` catches a *structured* elicitation. A session that
  ended its turn with "can you run `aws sso login` and tell me when it's done?"
  has none, and reads as a finished turn. `awaiting_human()` matches an explicit
  wait phrase, or a last assistant message that simply ends in `?`. It is tuned
  loose on purpose: a false positive costs one human glance, a false negative
  closes a session that was blocked on you. Those costs are not symmetric.
- **Rule 8 — a finished turn is not finished work.** One measured session looked
  like a clean candidate with **4 uncommitted files, no pushed branch and no PR**.
  `--workspace-git` attaches `git status --short`, the upstream ref and the ahead
  count for `idle` + live-runner rows that have a `workspace`; dirty, or never
  pushed, or ahead-with-no-PR all read as WIP. A branch with no upstream cannot
  have a PR, so this needs no `gh` call. **No probe data means unknown, never
  clean** — the classifier will not infer a clean tree from missing fields.

## When the coarse list and `get_info` disagree

Measured: a REST `/v1/sessions` listing said `status: failed` while an immediate
`sys_session_get_info` on the same session returned `idle`, with history showing
completed work. Silently picking either one is how a live session gets relaunched
or a dead one gets ignored.

**`get_info` wins** — it is the fresher and more specific read — **and the
disagreement is reported as a fact in the row**, not resolved behind your back:

```
- 3465311996250265  [omnigent] idle=1m  worker/…
    idle recently with a live runner … — NOTE: the coarse list and get_info
    disagree (list=failed get_info=idle); get_info is the fresher read and wins
```

`merge_info()` does the merge and sets `status_mismatch`. A mismatch is also an
`api_shape_drift` friction event — log it, because a list view that lies about
status is a server-side problem worth a pattern.

"Seed-only history" = no `function_call` / tool items and no assistant message —
just the user's first message and resource events. Detail and the wake call:
`dispatch-launch/liveness-and-surfacing.md`.

The classifier **never emits `done`.** It hands you a `done_candidate` and you
confirm with `gh pr view` / `git log` in the workspace. That asymmetry is the whole
point: an optimistic status field is how finished-looking sessions with no PR get
reaped (#1023).

## Enriching a verdict

`GET /v1/sessions` (and `sys_session_list`) carry `status`, `runner_online`,
`title`, `agent_name`, `parent_session_id`. Rules 2, 5, 6 need more:

```
sys_session_get_info(session_id=…)          # pending_elicitations, last_activity_at, workspace
sys_session_get_history(conversation_id=…, tail_items=5, content_max_chars=200)
```

Enrich **only the sessions the coarse pass cannot settle** — every `idle` +
`runner_online: true` session, and nothing that is `failed`, `running`, or offline.
On a fleet of 40 that is usually 3–6 calls, not 40. The workspace probe is bounded
the same way: `--workspace-git` touches only an `idle` + live-runner row that has a
`workspace`, because that is the only shape whose verdict can turn on git state.

### Feeding it from a remote server (#1688)

`--input -` assumes an interactive stdin a **tool harness cannot provide** — it has
no way to pipe a prior tool response into a process. Stage files instead; it is
deterministic and copy-safe, and a heredoc never mangles the JSON:

```bash
T="${TMPDIR:-/tmp}/cos-fleet"; mkdir -p "$T"
cat > "$T/fleet.json" <<'JSON'
{ …sys_session_list response, verbatim… }
JSON
cat > "$T/info.json" <<'JSON'
[ {"session_id": "…", "last_activity_at": 1758000000, "workspace": "/…",
   "items": [ …history tail… ]} ]
JSON
uv run --no-project python scripts/fleet_report.py \
  --input "$T/fleet.json" --info "$T/info.json" --json
```

`--info` accepts a list of info objects, a `{"data": […]}` / `{"sessions": […]}`
wrapper, a single object, or a map of session id → info — whichever shape your
harness happened to save. Rows with no matching read pass through untouched.

**Without it, a remote pass cannot classify.** `sys_session_list` omits
`last_activity_at`, so nothing can be stale, and every idle live-runner row lands
in `done_candidate`; it omits `workspace`, so the reconcile recipe below yields
nothing. Those rows now carry `UNENRICHED` in their reason — a report that says "I
do not know" beats one that says `done_candidate`.

`--workspace-git` runs local `git` in each workspace, so it applies when the
workspaces live on the machine running the script. For workspaces on a remote host,
read them there (or over `probe`/ssh) and supply `workspace_git` in the info
object; the classifier only ever reads that field.

## Two ledgers, not one

Sessions and worktrees have separate lifetimes. A closed session can leave a
worktree; a removed worktree can leave a session. At the end of any triage pass
that closed or relaunched anything, reconcile:

```bash
git -C <main-checkout> worktree list
```

against the `workspace` field of the surviving sessions. A worktree with no
session and no unpushed commits is teardown fodder; a session pointing at a
missing workspace is **orphaned** and should be closed. Mechanics:
`dispatch-launch/session-lifecycle.md`.

## Thresholds are tuned from evidence

The 30-minute stale threshold is a starting guess. When the friction log shows
`probe_lied` events clustering around a specific boundary ("classified stale, was
still working on a 40-minute test run"), change the default in `fleet_report.py`
and say so in the harvest issue. Do not hand-tune it from a single incident.
