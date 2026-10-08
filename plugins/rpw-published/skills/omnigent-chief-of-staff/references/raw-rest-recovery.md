# Raw-REST recovery — the three things that cost a pass every time (#1825)

Three failures kept being re-derived by hand across chief-of-staff passes, each
one wearing a message that pointed the wrong way. `scripts/fleet_action.py`
implements all three; this file is the audit trail and the by-hand fallback.

## 1. The slice key, or every session on the host 400s

Any **session-scoped** call — `GET /v1/sessions/{id}`,
`POST /v1/sessions/{id}/events`, `PATCH /v1/sessions/{id}` — against a
host-sharded server needs:

```
X-Databricks-Omnigent-Slice-Key: <host_id with the "host_" prefix stripped>
```

`host_id: host_9` → header value `9`. Without it, or with the prefix left on, the
server answers **400 `wrong_replica`** — for *every* session on that host, not
just one.

> ⚠️ **It is deterministic, not transient. Retrying never helps.** That is the
> trap: the response reads like a transient routing blip, so the reflex is a
> retry loop, and the loop always fails. Root-caused 2026-09-17.

`fleet_action.py` builds this value itself (`slice_key()` / `with_slice_key()`):
it adds the header when the upstream builder omits it, and normalises a value
that still carries the `host_` prefix. A remote target with no `=HOST_ID` is
refused **before** the request, on purpose. Take `host_id` from
`sys_session_get_info`.

By hand:

```bash
curl -s "$BASE/v1/sessions/$SID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Databricks-Omnigent-Slice-Key: ${HOST_ID#host_}"
```

## 2. `last_task_error_code` answers "dead or just blocked" in one call

Before assuming a dead-looking session needs a routing fix or a relaunch, read
the label:

```bash
uv run --no-project --with 'omnigent[databricks]' python scripts/fleet_action.py \
  --server "$BASE" probe "${SID}=${HOST_ID}"
```

It GETs `/v1/sessions/{id}` (slice key included), reads
`labels.omnigent.last_task_error_code`, and prints one of three verdicts:

| `last_task_error_code` | Verdict | Next move |
|---|---|---|
| `runner_disconnected` | **relaunch** | The runner process is gone; no nudge can reach it. Relaunch in place — same brief, same worktree. |
| any other code | **inspect** | Neither a clean finish nor a routing problem. Read the code first. |
| absent | **re-send** | Nothing killed the last task. Idle or routing-blocked — nudge before relaunching. |

`probe` mutates nothing, so it is outside the confirm-before-mutate gate rather
than an exception to it. Do it **first**: it is the cheapest read on the fleet and
it is the difference between throwing away a session's context and just re-sending.

The label has been seen in two shapes — flattened to the dotted key
`labels["omnigent.last_task_error_code"]` and nested under `labels.omnigent`. The
script reads both; if you hit a third, that is an `api_shape_drift` event.

## 3. `session_not_a_sub_agent` is not lying to you

`sys_session_close` (and `sys_session_continue`) can refuse a child whose
`get_info.parent_session_id` visibly matches the parent you called from:

```
session_not_a_sub_agent
```

**The discriminator:** sub-agent tracking is keyed by **`(agent, title)` under the
parent**, not by the `parent_session_id` field. The field is descriptive; the
registry is what those tools read. So the call works only for names actually
registered in the parent's `sub_agents` view.

- Check `sys_session_get_info()` on the **parent** and look at `sub_agents` — if
  the `(agent, title)` pair is not there, the tool will keep refusing however
  right `parent_session_id` looks.
- Route round it with the session-scoped REST call (`DELETE /v1/sessions/{id}`,
  with the slice key) which addresses the session directly.
- A rename that changed the child's title un-registers it by that key. Retitling
  a live child and then trying to close it through the parent is the common way
  into this error.

## The habit all three teach

**Do not cite a tool, script, or field until it is confirmed present.** Item 4 of
#1825 was a recovery script named across several passes as "the preferred wake
mechanism" before anyone checked it existed — it did not, until `fleet_action.py`
was actually written. `ls` the path, `grep` the field, or say plainly that you
have not verified it. Reporting a shape you assumed is exactly the `probe_lied`
class this skill logs against itself.
