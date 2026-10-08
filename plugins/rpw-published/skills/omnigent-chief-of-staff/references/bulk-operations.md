# Bulk operations — rename, wake, nudge, close, reconcile, across many sessions

Every operation here mutates a session. Two rules hold for all of them:

1. **Show the list, then act.** Print the exact `(session_id, title, action)` rows
   you are about to touch and get a yes. A bulk close that hit one live session is
   not recoverable. Only `wake` on a `stuck` session is low enough blast radius to
   skip the confirmation — and only because a stuck session is doing nothing.
2. **One mechanism per operation, and it is the one that works on the whole
   fleet.** Where the MCP tool has a limitation the REST route does not, the REST
   route is primary and the tool is noted as the exception. Don't alternate.

Local server base: `BASE=http://127.0.0.1:6767` (the local Omnigent server;
`dispatch-launch/reference.md` verified the surface). Sessions created from a
remote server (a Databricks App) live behind that server's URL instead — the
`sys_session_*` tools address whichever server the current session belongs to,
which is why the tool path is the fallback when the REST base is wrong.

## Rename

**Primary — REST `PATCH`.** Works on any title length and on auto-titled sessions.

```bash
curl -s -X PATCH "$BASE/v1/sessions/$SID" \
  -H 'Content-Type: application/json' \
  -d "{\"title\": \"$NEW_TITLE\"}"
```

**Why not `sys_session_rename`:** measured 2026-08-04, it caps at **60 chars**
server-side (422 `string_too_long`) and **refuses auto-titled sessions**
(`{"renamed": false, "reason": "title_changed"}`). The structured title convention
(`repo::branch::date::state — summary`, `docs/process/agent-session-titles.md`)
routinely exceeds 60. So the tool fails on exactly the titles worth setting.
Reach for it only for the *current* session, where there is no `$SID` to hand.

Bulk shape — build the mapping first, print it, confirm, then loop:

```bash
while IFS=$'\t' read -r sid title; do
  curl -s -o /dev/null -w "$sid %{http_code}\n" -X PATCH "$BASE/v1/sessions/$sid" \
    -H 'Content-Type: application/json' -d "$(jq -cn --arg t "$title" '{title:$t}')"
done < renames.tsv
```

A non-2xx row is a `rename_refused` friction event — log it with the status code.

When retitling, derive the `<work-summary>` from the session's first substantive
user message or the issue it carries; never from `Start working` boilerplate.

## Wake / nudge / reconnect

All three are the same call: post a user message event. On an idle session it
starts a turn; on a busy one it coalesces with pending input; on a **stuck**
(never-woken) session it is the missing second half of the launch.

```bash
cd "<this-skill-dir>"
uv run --no-project --with 'omnigent[databricks]' python scripts/fleet_action.py \
  --server "$BASE" nudge "${SID}=${HOST_ID}"
# Prints the exact rows and sends nothing. After confirmation:
uv run --no-project --with 'omnigent[databricks]' python scripts/fleet_action.py \
  --server "$BASE" --confirm nudge "${SID}=${HOST_ID}"
```

Repeat the target argument for fan-out. Remote targets must be
`SESSION_ID=HOST_ID`; take both values from `sys_session_get_info`. The helper
uses the login recorded by `omnigent login`, mints Databricks OAuth through the
public SDK when that login points at a workspace, and passes `host_id` through
Omnigent's request-header builder. This preserves the host's replica slice; an
unkeyed remote call fails before the POST instead of returning `wrong_replica`.
If auth cannot be resolved, follow its `omnigent login` / `databricks auth login`
error. Pass `--profile NAME` when a workspace has multiple named profiles.

For the one confirmation exception, use `wake-stuck` only after the status
cascade has proved the session is seed-only:

```bash
uv run --no-project --with 'omnigent[databricks]' python scripts/fleet_action.py \
  --server "$BASE" wake-stuck "${SID}=${HOST_ID}"
```

For a local loopback server omit `=${HOST_ID}`; no auth or replica route is
needed.

From inside a turn: `sys_session_send(session_id=…, args="…")` — but note it
**blocks until the child's turn completes**, so it is a poor fit for a fleet-wide
nudge. Use the REST POST for fan-out; use `sys_session_send` when you want the
answer inline.

**Nudge before relaunch, always.** A nudge keeps the session's context; a relaunch
throws it away. Allow 10–30 s after the POST before re-probing history. Only a
session whose history stays frozen through two nudges is a `reconnect_failed`
event and a relaunch candidate.

**Dead runner (`runner_online: false`, `status: failed`).** Do not guess whether a
nudge can still reach it — one read answers that:

```bash
uv run --no-project --with 'omnigent[databricks]' python scripts/fleet_action.py \
  --server "$BASE" probe "${SID}=${HOST_ID}"
```

`last_task_error_code=runner_disconnected` → the process is gone, relaunch. No code
→ nothing killed the task, so nudge it. Then check the host
(`omnigent host status`, and the `omnigent-host` skill if it is installed in the
user's environment); a dead host kills every session on it, and relaunching into a
dead host just makes more corpses. Relaunch = same brief file, same worktree, new
session (`dispatch-launch`).

**When a raw call 4xxs, read [raw-rest-recovery.md](raw-rest-recovery.md) before
retrying.** Three failures there are deterministic and never resolve on a second
attempt: `wrong_replica` (missing or prefixed slice key), `session_not_a_sub_agent`
(sub-agents are keyed by `(agent, title)` under the parent, not by
`parent_session_id`), and a `last_task_error_code` nobody read.

## Close

```bash
curl -s -X DELETE "$BASE/v1/sessions/$SID"
# -> {"deleted": true}
```

or `sys_session_close(conversation_id=…)`. Closing **does not touch the worktree**
and does not kill processes running in it. Sweep before teardown
(`dispatch-launch/session-lifecycle.md`).

Bulk-close candidates are `parked` sessions whose artifact is confirmed (PR merged,
or no workspace and nothing to lose). Print the list. Confirm. Then loop. A `parked`
session with an unmerged PR or a dirty worktree is **not** a close candidate — it is
a `done_candidate` that needs a human decision, and the report should say so.

## Reconcile sessions ↔ worktrees

```bash
MAIN=<main checkout>
git -C "$MAIN" worktree list --porcelain | awk '/^worktree /{print $2}' > /tmp/wts
uv run --no-project python scripts/fleet_report.py --server "$BASE" --json \
  | jq -r '.[] | select(.workspace) | .workspace' | sort -u > /tmp/ws
comm -23 <(sort /tmp/wts) /tmp/ws   # worktrees with no session
comm -13 <(sort /tmp/wts) /tmp/ws   # sessions whose workspace is gone (orphaned)
```

Orphaned sessions → close. Session-less worktrees → `git -C "$WT" status --short`
and `git log @{u}..` first; teardown only when both are empty.

⚠️ **Remote server:** `sys_session_list` carries no `workspace`, so the `jq` above
returns an empty set and the comparison silently "finds" nothing to reconcile. Pass
`--info` with the `sys_session_get_info` reads first (`status-cascade.md` → *Feeding
it from a remote server*). `fleet_report.py --workspace-git` runs those same two
per-worktree checks for you, on the rows where they change the verdict.

## Recording the snag

Whenever any of the above did not go the way this file says — a 4xx where a 2xx
was documented, a field missing, a nudge that did nothing, a loop you had to
hand-roll — spend the ten seconds:

```bash
uv run --no-project python scripts/friction_log.py log <type> \
  --detail "<what happened>" --session "$SID" --surface "<route or tool>" \
  --lesson "<what the skill should do instead>"
```

That line is the only way this file gets better.
