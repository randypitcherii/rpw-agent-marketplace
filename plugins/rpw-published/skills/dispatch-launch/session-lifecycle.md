# Session lifecycle — where you are, rename, close, teardown, self-terminate

Managing dispatches that already exist, including the one you are running in.

## Where you are

Two env vars are injected into an omnigent session terminal:

| Variable | What it points at |
|---|---|
| `$OMNIGENT_RUNNER_WORKSPACE` | this worktree — verified equal to the session's bound `workspace` |
| Runner authentication values | Credentials. Never echo them into a file, commit, issue, or report. They are not session IDs. |

`$OMNIGENT_RUNNER_WORKSPACE` is only as good as the launch: a **path-A** session binds
it to the worktree you passed, but a **path-B** child has no `workspace` at all, so
its brief's Step 0 block is the only authority on where it should be working. Derive
rather than assume when it matters:

```bash
git rev-parse --show-toplevel && git branch --show-current
```

**There is no env var for the main clone** — the retired Superset path exported
`$SUPERSET_ROOT_PATH` and omnigent has no equivalent:

```bash
dirname "$(git rev-parse --git-common-dir)"   # the main checkout, from any linked worktree
```

**There is no env var for the session id** either. A session that needs its own
`conversation_id` (to rename or close itself) must be told it in its brief.

`.git/info/exclude` does **not** work in a linked worktree (`.git` is a file there).
The one correct form:

```bash
printf '<pattern>\n' >> "$(git rev-parse --git-path info/exclude)"
git check-ignore -v <pattern>      # prove it took
```

## Rename

One step, from the repo root — `SID` is the `conversation_id`:

```bash
make session-list                                   # ids, status, titles
make session-rename SID=<id> TITLE="<repo>::<branch>::<date>::<state> — <summary>"
```

`scripts/session-rename.sh` is the same thing without `make`. It resolves the API base
(`$OMNIGENT_API_BASE` → `$RUNNER_SERVER_URL` → the `server:` line of
`~/.omnigent/config.yaml` → `http://127.0.0.1:6767`) and the auth a Databricks-fronted
server needs (`databricks auth token --profile <the ~/.databrickscfg profile for that workspace>`; a
Databricks App's workspace comes from the pointer `omnigent login` stored, plus the
`X-Databricks-Omnigent-Slice-Key: <host_id>` shard hint from
`$OMNIGENT_RUNNER_SLICE_KEY`), truncates at the real cap with a message naming what was
dropped, and **reads the title back** so a silent no-op cannot pass for a rename. The
route underneath is one call:

```bash
curl -s -X PATCH "$API_BASE/v1/sessions/$SID" \
  -H 'Content-Type: application/json' -d '{"title": "<good name>"}'
```

### `sys_session_rename` is a different route, not this one

It posts to `POST /v1/sessions/{id}/auto-title` — the *automatic* titler
(`runner/tool_dispatch.py`) — so none of its limits describe the manual rename:

| | `PATCH /v1/sessions/{id}` | `sys_session_rename` → `POST …/auto-title` |
|---|---|---|
| Title cap | **200** chars | **60** in the MCP tool schema; the deployed route allows **100** |
| Precondition | none | the current title must still equal the deterministic first-message title |
| Refuses with | 404 only (unknown session) | `title_changed` once the title differs from that seed, `no_seed` with no first message, `not_top_level` for a sub-agent |

`title_changed` is therefore the **inverse** of "refuses auto-titled sessions": the
auto-titler declines to clobber a title someone already set — which is every structured
title in the rail, and every path-A dispatch. Manual renames go through `PATCH`.

### Measured, both routes and create alike (2026-09-16, managed server)

- **200 chars is a hard cap** on create and on `PATCH` — 201 is a 422
  `string_too_long`, a refusal rather than a truncation.
- **`/` is stored as a space.** `worker/1613-x` reads back `worker 1613-x`, so no
  branch segment ever round-trips verbatim; the script substitutes it up front and says
  so. `\`, `|`, `#` and `::` survive.
- **Trailing whitespace is stripped**; a 1-char title is a 422 `string_too_short`.

Title shape is `docs/process/agent-session-titles.md`; when a title will not fit, keep
the longest prefix so `repo::branch` survives, which is what the script does.

Or `sys_session_rename(title=…)` from inside a turn. Local either way, no org
round-trip. Two measured constraints on the MCP path: it **caps at 60 chars**
server-side (422 beyond) and it **refuses auto-titled sessions** (`title_changed`) —
so a path-C session whose title the server derived from the prompt often cannot be
renamed that way; use the `PATCH` above. Titles set at *creation* are not capped (a
76-char title round-tripped intact), which is why path A sets the structured title
there.

Both title shapes and the state-emoji prefix are defined once, in
the session-title convention (`docs/process/agent-session-titles.md`). Two rules from it apply
to every rename you do here:

- **An ad-hoc rename takes the plain-English body**, not the `::`-structured one — a
  human renaming their own session already knows the repo and the branch, and the
  60-char cap is better spent on what the session is doing. `⏳ Building the first
  custom Omnigent agent`, not `⏳ repo::feat/x::2026-09-16::build_worker — …`.
- **Keep the emoji prefix current.** Flip it to ‼️ the moment the session parks on a
  human decision, and to a terminal glyph at close-out (next section). Renaming the
  body while leaving a stale ⏳ on a finished session is the failure this convention
  exists to prevent — it claims to be working.

### Flip the prefix at close-out

Closing out is two steps, not one: set the terminal state, *then* close. The prefix is
the only close-out signal that survives in the rail after the session goes idle.

| Outcome | Prefix | Example |
|---|---|---|
| PR merged, or the gate-mode PR is open and ready | ✅ | `✅ Emoji session-title convention shipped` |
| failed and cannot self-recover | ❌ | `❌ rpw-agent-marketplace::fix/1712-ci::2026-09-16::build_worker — CI green (blocked on creds)` |
| halted deliberately or superseded | 🛑 | `🛑 Snowflake PAT probe — superseded by #1804` |

```bash
source <this-skill-dir>/scripts/omni-api.sh
curl -s -X PATCH "$API_BASE/v1/sessions/$SID" ${AUTH_HEADERS[@]+"${AUTH_HEADERS[@]}"} \
  -H 'Content-Type: application/json' -d '{"title": "✅ <same body, unchanged>"}'
```

Change only the prefix — a body that changes at close-out breaks the rail's continuity
with the report that named it.

## Close a session

```bash
make session-close SID=<id>      # = scripts/session-close.sh <id>
```

`session-close` sends the PATCH `sys_session_close` sends — the `omnigent.closed`
label plus `archived: true`, which triggers the server's reaper for the session's
harness, tmux and bridge processes — then reads `archived` back. It resolves the base
and auth like `session-rename` (`scripts/omni-api.sh`), so it works on the managed
server, where nothing listens on localhost.

Use it for any session you own. `sys_session_close(conversation_id=<id>)` works only
inside your own spawn tree: a session created over REST — every path-A dispatch and
the wave-kickoff write probe — answers `session_out_of_tree`, and the omni CLI (0.16)
has no close command (#2030). A raw `curl -X DELETE "$API_BASE/v1/sessions/$SID"`
(omni-api.sh base) hard-deletes instead; archive is reversible.
Closing a session **does not touch the worktree**.

## Tear down the worktree

```bash
MAIN=$(dirname "$(git -C "$WT" rev-parse --git-common-dir)")
git -C "$MAIN" worktree remove "$WT"
git -C "$MAIN" branch -D <branch>       # squash-merge --delete-branch removes only the remote
```

Use the branch name you created — nothing prefixed it. `worktree remove` refuses while
the tree is dirty; `--force` only after you have read what is uncommitted. If the
directory is already gone, `git worktree prune` clears the stale record.

The separated lifetimes are a **strict improvement** on the Superset path, where
`workspaces delete --local` removed the worktree synchronously and destroyed the
current terminal's CWD the moment it returned. Here killing the session never eats the
work, and removing the worktree never orphans a session record.

**But a worktree removal does not kill what runs in it** (#644). Sweep first:

```bash
tmux kill-session -t worker-<issue> 2>/dev/null || true     # path C
lsof +D "$WT" | awk 'NR>1 {print $2}' | sort -u | xargs -r ps -o pid,command= -p
```

A surviving process after teardown is a loud failure, not a cosmetic one.

## Agent self-termination (an agent closing out its own finished dispatch)

For an agent whose PR has landed. The old ordering hazard (a self-delete that killed
the terminal mid-command) is gone, but the sequencing still matters:

1. **Confirm the PR merged** — `gh pr view <n> --json state -q .state` ⇒ `MERGED`.
   Anything else ⇒ STOP and leave the session alive.
2. **Send your final report FIRST.** The report is the deliverable; once the worktree
   is removed nothing in it is recoverable.
3. **Flip your title to ✅** (the `PATCH` above, prefix only). Do it before teardown —
   after step 5 there is no session left to rename, and a session that reaped itself
   still showing ⏳ reads as a hung worker.
4. **Prune the branch** — a squash-merge `--delete-branch` removes only the remote:
   ```bash
   git -C "$(dirname "$(git rev-parse --git-common-dir)")" branch -D <branch> 2>/dev/null || true
   ```
5. **Remove the worktree from outside it** — removing the directory you are standing in
   leaves the shell in a dead cwd:
   ```bash
   MAIN=$(dirname "$(git rev-parse --git-common-dir)")
   cd "$MAIN" && git worktree remove "$OMNIGENT_RUNNER_WORKSPACE"
   ```
6. **Close the session last**, or prefer letting the orchestrator reap you. Reaping a
   whole cohort is **wave-supervisor**'s job, not each worker's.

## Listing what is out there

```bash
make session-list                      # id, status, title — resolves base URL + auth
git -C <main-checkout> worktree list
```

A bare `curl "$API_BASE/v1/sessions"` works only against the local host service; the
managed server needs the bearer token and shard header `session-rename.sh` builds.

Both lists matter and they can disagree: a deleted session can leave a worktree, and a
removed worktree can leave a session record. Reconcile them at close-out rather than
trusting either alone.

## Scheduled dispatch

A recurring dispatch is `sys_scheduled_task_create` (or `POST /v1/scheduled-tasks`) —
an agent id, a prompt, an RFC 5545 `rrule`, and optionally a pinned host and
workspace. Same brief-file discipline applies: point the prompt at a file, don't
inline a wall of text into a schedule.
