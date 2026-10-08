---
name: omnigent-chief-of-staff
description: One surface to manage a fleet of Omnigent sessions — what is stuck, finished, or waiting on you, then bulk rename / wake / nudge / close / reconcile behind a confirm gate, plus a friction log that harvests its own headaches into retro-finding issues. Trigger on "what's stuck", "any updates on my sessions", "chief of staff", "rename these sessions", "close the dead ones". NOT for dispatching new work (dispatch-launch, wave-kickoff) or the host daemon (omnigent-host).
---

# Omnigent chief of staff

One surface for the question "how is my fleet, and what do I need to do about it."
It reads every session, sorts them by how urgently a human is needed, and offers
the bulk actions that answer the report — then writes down every place it tripped
so the next pass is smoother.

Three things it composes onto and does not restate: `dispatch-launch` owns
liveness rules and the single-session lifecycle; `wave-supervisor` owns a wave's
cohort; `omnigent-host` (when installed in the user's environment) owns the host
daemon. This skill is the layer above — many sessions, many origins, one answer.

## The loop

Every invocation runs the same four steps. Skip none; the friction log has shown
the skipped step is where the next headache comes from.

### 1. Inventory and classify

```bash
uv run --no-project python "<this-skill-dir>/scripts/fleet_report.py" --server http://127.0.0.1:6767
```

No local server, or the sessions live behind a remote one (`omnigent config list`
shows `server=`)? **A tool harness cannot pipe a prior tool response into stdin**,
so stage files instead of reaching for `--input -` (#1688) — and never transcribe
rows by hand:

```bash
D="<this-skill-dir>"; T="${TMPDIR:-/tmp}/cos-fleet"; mkdir -p "$T"
cat > "$T/fleet.json" <<'JSON'
{ …the sys_session_list response, verbatim… }
JSON
cat > "$T/info.json" <<'JSON'
[ …one sys_session_get_info object per enriched session (step 2)… ]
JSON
uv run --no-project python "$D/scripts/fleet_report.py" \
  --input "$T/fleet.json" --info "$T/info.json" --workspace-git
```

The `sessions` key is unwrapped for you. `--info` merges the enrichment over the
coarse rows, `get_info` winning any conflict. The coarse list omits
`last_activity_at` and `workspace`, so **without `--info` every idle live-runner
row is an unenriched guess** — the reason field says so rather than pretending.
`--workspace-git` only helps when those workspace paths are on *this* machine.

The script applies the cascade in [references/status-cascade.md](references/status-cascade.md)
and prints urgent-first:

| Verdict | Means | Priority |
|---|---|---|
| `dead` | `status: failed` | urgent |
| `needs_input` | pending elicitation — waiting on a human | urgent |
| `stuck` | idle, live runner, seed-only history — never woken | urgent |
| `stale` | idle > 30 m with a live runner and no question | warning |
| `done_candidate` | just went idle; verify the artifact | action |
| `working` | running | info |
| `parked` | idle, runner offline — hidden unless `--all` | info |

**It never says `done`.** Completion is a PR URL, a commit, or a green gate. The
report hands you candidates; you confirm.

### 2. Enrich only what the coarse pass cannot settle

Every `idle` + `runner_online: true` session needs two more reads —
`sys_session_get_info` (pending questions, `last_activity_at`, `workspace`) and
`sys_session_get_history(tail_items=5, content_max_chars=200)`. Nothing that is
`failed`, `running`, or offline needs enrichment. On a 40-session fleet that is
3–6 calls.

Collect those reads into the `info.json` above (a list, or a map of session id →
info, both are accepted) and let `--info` merge them — that is what recovers
`last_activity_at` before stale classification and `workspace` before reconcile.
Put each session's history `items` in its info object too: the last assistant
message is the only evidence of a pending question when nothing was elicited.

### 3. Report, then offer actions

Lead with the counts, then the urgent rows, then a one-line proposal per row.
Group parked sessions into a single line. Shape it for a reader who will skim:
the `communication` skill applies.

Then offer, as a numbered list the user can pick from:

- **wake** the `stuck` ones (safe; no confirmation needed)
- **nudge** the `stale` ones for a status
- **answer / attach** the `needs_input` ones
- **rename** anything whose title is boilerplate, to `repo::branch::date::state — summary`
- **close** confirmed-finished `parked` ones; **relaunch** `dead` ones
- **reconcile** sessions against worktrees

Mechanics for each — and why REST `PATCH` is the rename path, not the MCP tool —
are in [references/bulk-operations.md](references/bulk-operations.md).

**Confirm before mutating.** Print the exact rows a bulk action will touch and get
a yes. The only exception is waking a `stuck` session, which is doing nothing.
For remote/bulk wakes and nudges, use `scripts/fleet_action.py`; it obtains
Omnigent login authentication and passes each session's `host_id` through
Omnigent's replica-routing interface. It previews nudges until `--confirm` and
refuses an unkeyed remote target instead of risking `wrong_replica`.

**Probe before recovering.** `fleet_action.py … probe SID=HOST_ID` GETs one session
and reads `labels.omnigent.last_task_error_code`: `runner_disconnected` means the
runner is gone (relaunch), no code means nothing killed the task (nudge). It
mutates nothing, so the gate above does not apply. The raw-REST failures that are
deterministic and never survive a retry — the slice-key law, the
`session_not_a_sub_agent` discriminator — are in
[references/raw-rest-recovery.md](references/raw-rest-recovery.md).

### 4. Log the friction

Anything that did not go the way the references say — a field missing, a 4xx, a
verdict the user corrected, a loop you hand-rolled — is one line:

```bash
uv run --no-project python "<this-skill-dir>/scripts/friction_log.py" log <type> \
  --detail "…" --session "$SID" --surface "…" --lesson "…"
```

Types: `probe_lied`, `bulk_op_manual_loop`, `api_shape_drift`, `rename_refused`,
`reconnect_failed`, `user_correction`, `missing_context`, `safety_intentional`.
The last one is for a gate that correctly stopped you — reinforcement, so the
harvest never proposes relaxing it.

End the pass with
`uv run --no-project python "<this-skill-dir>/scripts/friction_log.py" report`.
A class at **HARVEST** becomes a
`retro-finding` issue per [references/self-improvement.md](references/self-improvement.md):
dedupe, file with the lessons as the proposal, archive the class. The skill is
never edited in place; the fix lands through that issue and a PR with a test.

## Probes that lie

Read before trusting any single field. Full table: `status-cascade.md`.

- `status: idle` ≠ done. Also "never started" (#974). History decides.
- `runner_online: true` ≠ healthy. It is a tunnel, not an agent.
- A "finished" message in history ≠ finished (#971). Only the artifact counts.
- A finished *turn* ≠ finished *work* (#1800). One measured `done_candidate` had 4
  uncommitted files and no PR: `--workspace-git` reclassifies those `stale`.
- No `pending_elicitation_count` ≠ nobody is waiting (#1800). A last message that
  asks you something — an SSO login, a decision — is `needs_input`, prose only.
- A coarse list `status` ≠ the session's status. When `sys_session_list` and
  `sys_session_get_info` disagree, `get_info` wins **and the row says so**.
- `git_branch` on a session = the branch at *creation*, not now.
- `sys_session_rename` ≠ rename. Caps at 60 chars and refuses auto-titled sessions.

## Where you are

Running *as* an Omnigent session, you are one row in your own report. Your
`conversation_id` is not in any env var; `sys_session_get_info()` with no
argument describes you. Do not close or relaunch yourself from the bulk list.

## Related skills

- `dispatch-launch` — one session's launch, wake, rename, close, teardown. This
  skill fans those out.
- `wave-supervisor` / `wave-kickoff` — a wave's own monitor and retro miner.
  The chief-of-staff sees the wave supervisor as one `working` row.
- `issue-creation` — the harvest issues take its shape and its labels.
- `communication` — the report is for a human who will skim it.
