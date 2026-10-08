# Liveness and surfacing — the wake call, Step 5, and Step 6

A successful launch call only means the session was *created*. Three hidden failures
follow, and they need different responses:

| Failure | What it looks like | Fix |
|---|---|---|
| **Never woken** (path A) | `status: idle`, `runner_online: true`, history = seed message only | the wake call below |
| **Dead spawn** | `status: failed`, or history frozen with `runner_online: false` | relaunch in place |
| **Invisible progress** | it works fine, nobody can find it | surface the `conversation_id` (Step 6) |

Telling them apart is the whole point of the Step 5 gate. **Never skip it** —
"dispatched" is not "running".

## The wake call (path A — REQUIRED, not optional)

```bash
LAUNCH=<this-skill-dir>/scripts
source "$LAUNCH/omni-api.sh"; BASE=$API_BASE   # the configured server, with auth
SID=<conversation_id>
curl -s -X POST "$BASE/v1/sessions/$SID/events" ${AUTH_HEADERS[@]+"${AUTH_HEADERS[@]}"} -H 'Content-Type: application/json' -d '{
  "type": "message",
  "data": {"role": "user", "content": [{"type": "input_text",
    "text": "#<issue> <work-summary>. Read WORKER-BRIEF.md in your worktree root and execute it exactly."}]}
}'
# -> HTTP 202  {"queued":true,"pending_id":"pending_…"}
```

**Why this call exists.** `POST /v1/sessions` dispatches `initial_items` to the bound
runner *if one is bound* — but an externally-hosted runner is provisioned
**asynchronously**, so at create time there usually is none. The server then persists
the items as a **history-only seed** (tagged `response_id: "seed"`) and, in its own
words, *"the caller is responsible for binding a runner and posting a follow-up event
if they want the agent to react."* Nothing executes.

Measured live 2026-08-14: a bind-mode session sat `idle` with `runner_online: true`
for 120s, history holding exactly the seed message and one `session.resource.created`
event — indistinguishable from healthy at a glance. It began work within 10s of the
event POST above and finished its brief in ~50s with nine `function_call` items.

So on path A the launch is **always two calls**: create, then wake. Treat
`initial_items` as optional decoration.

**Prefer `make session-wake SID=<id> MSG="<pointer>"` over the bare POST (#2030).** It
posts the same event, resolving base and auth the same way as the `BASE` above (it
sources the same `scripts/omni-api.sh`), polls until `running`, and re-posts once the
claude-home **Settings Error** race is the reason for a `failed` status (below). Exit
0 = running, 6 = a real dead spawn, 7 = not started yet.

## Step 5 — the probe

`status: "idle"` on a fresh session means **created, not working** (#974). The gate is
the history.

**From a shell (paths A and C):**

```bash
curl -s "$BASE/v1/sessions/$SID" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("status", d.get("status"), "runner_online", d.get("runner_online"))
for it in d.get("items", []):
    print(" -", it.get("type"), it.get("name",""))
'
tmux capture-pane -pt worker-<issue> | tail -20     # path C only: what it is doing now
```

**Inside an omnigent turn (path B):**

```
sys_session_get_info(session_id=<conversation_id>)      # running, then idle when done
sys_session_get_history(conversation_id=<conversation_id>, tail_items=25)
#   -> REQUIRED: real function_call items doing the brief's work.
```

**Healthy** = real `function_call` items (`Read`, `Bash`, `Write`, …) AND the work
*advancing*: new commits, a moving `.rpw/build/state.json`, growing brief-relevant
output. A history holding only the seed message and a `resource_event` is **not**
liveness — poll again (allow ~10–30s after the wake) before concluding anything.

```bash
git -C "$WT" log --oneline -3      # the second signal: the first real artifact
```

### Probes that lie

- **`status` alone.** `idle` is both "not started yet" and "finished the turn". It
  distinguishes nothing (#974) — it is the exact `ok:true` trap the Superset path had.
- **A completion claim.** A session can report finished work it never did (#971).
  Completion means a **PR URL, a commit SHA, or a green gate** — nothing else counts.
- **`lsof +D <worktree>` and `ps | grep "<prompt fragment>"`.** Both were the
  Superset-era liveness probes and both produced false "STILL DEAD" verdicts on
  thriving agents: `lsof`'s `COMMAND` column truncates to ~9 chars, and
  server-launched agents don't carry the prompt in argv. Neither is needed now — the
  session's item history is a first-class, non-lying signal. If you are ever reduced
  to a process check, resolve PIDs with full `ps -o command=` (#259).
- **A path-B child's own `sys_session_get_info`.** It reports `workspace`,
  `git_branch`, `model`, `host_id` as `null`. Read the **parent** session's
  `workspace` — and treat `git_branch` as the branch the worktree was *created* on,
  never the branch checked out now. (Path A sessions carry a real bound `workspace`.)

### Dead-spawn signature and recovery

`status: failed`, or a history frozen at the user message with `runner_online: false`.

**Rule out the Settings Error wake race first (#2030).** On a claude-home host the
Seatbelt sandbox hides `managed-settings.json` on purpose, so Claude Code opens a
*Settings Error* dialog at startup and the auto-dismisser answers it ("Continue without
these settings") a few seconds later. A wake that arrives first is refused and the
session goes `failed`, with an `error` item reading *"Claude Code is waiting for an
answer in its terminal (Settings Error), so the message was not delivered"*. The pane is
healthy seconds later. Confirm with the dismisser's log, then **re-wake — never
relaunch**:

```bash
tail -3 ~/.claude-home/auto-dismiss.log   # a `shape=settings-error key=3` press just after the refusal
make session-wake SID=<id> MSG="<same pointer>"
```

Measured 2026-09-28: one session refused at ~20:51:50Z, dismissed at
20:51:55Z, one re-post later it was working. A probe launched a minute earlier missed
the race, so a passing write probe does not rule it out.

1. **Do NOT delete the worktree** — `WORKER-BRIEF.md` is intact, which is the whole
   point of the brief-file pattern.
2. **Re-post the wake event first.** If the runner has since come online, that alone
   revives it — with full context, unlike a relaunch.
3. Still dead ⇒ relaunch: the same create payload (same title, same worktree) and wake
   again, or the same tmux command on path C. Re-probe the new `conversation_id`.
4. **Twice-dead ⇒ stop looping** and check the host, not the brief:

```bash
curl -s "$BASE/v1/hosts" | python3 -m json.tool | grep -E '"(id|status)"'
tail -40 ~/.omnigent/logs/host/host-*.log
```

A dead or wedged runner kills every session regardless of the brief. **Liveness is not health** — judge the host only by `status: online`, then use Omnigent's public host diagnostics when it is not healthy.

### Wedged on an invisible question (#972)

An unattended session that stops to ask a permission question has nowhere to render it.

**Signature — both halves, together:** `pending_elicitations` **non-empty** on the
session record, and a **stalled history** whose last item is a `tool_use` with no
`tool_result`. Non-empty means it is waiting on a human, not thinking. (Non-empty is
what separates this from the managed-policy stall below, where the list stays `[]` and
there is nothing to resolve.)

**`acceptEdits` does not cover MCP tools.** It gates file-edit tools only, so every
`mcp__omnigent__sys_*` call still raises a prompt. Measured 2026-09-12: a supervisor
session launched with
`terminal_launch_args: ["--permission-mode","acceptEdits"]`, stalled on its first
`mcp__omnigent__sys_agent_list` — the exact call a wave brief *requires* it to make.

**Prevention (do this instead):** supervisor-grade unattended launches take
`terminal_launch_args: ["--permission-mode","bypassPermissions"]` (path A) or
`--dangerously-skip-permissions` (path C), and briefs are written to need no answer
mid-run. Pre-granting only edits just moves the wedge one layer down.

#### Cure — resolve the elicitation over REST

When you could not pre-grant, the server exposes a resolve route (verified in the
installed omnigent `server/routes/sessions/routes_elicitations.py`):

```bash
# 1. The id comes off the session snapshot — there is no list-elicitations route.
EID=$(curl -sf "$BASE/v1/sessions/$SID" | jq -r '.pending_elicitations[0].elicitation_id')

# 2. Accept it, and remember the decision for the rest of the session.
curl -sf -X POST "$BASE/v1/sessions/$SID/elicitations/$EID/resolve" \
  -H 'content-type: application/json' \
  -d '{"action": "accept", "content": {"remember": true}}'
```

- `action: accept` + `content.remember: true` adds a **session-scoped allow rule** for
  that tool (`PermissionUpdate addRules`, `destination: "session"`). The measured
  supervisor unblocked within seconds and continued.
- **`remember` is honored only for remember-eligible tools** (`_allow_remember_eligible`
  server-side); edit tools take the `setMode` path instead, so do not read a
  still-prompting edit tool as a failed call.
- **One prompt per distinct tool name**, and with `remember: true` it does not fire
  again for that tool in that session. A wave supervisor should expect one each for
  `sys_agent_list`, `sys_session_create`, `sys_session_get_info`,
  `sys_session_get_history`, and `sys_session_send` — five resolves, not one.
- **Auth:** the managed server accepts the Databricks CLI token
  (`databricks auth token --host <workspace host>`). `~/.omnigent/auth_tokens.json`
  does **not** carry a bearer token — do not go looking for one there.

Resolving is recovery, not a launch strategy: five hand-resolves per supervisor is why
the prevention line above exists.

### The managed-policy stall — an EMPTY `pending_elicitations` (#1777)

The nastier sibling of #972, and the one that has cost the most: the prompt exists, but
**no API surface shows it**. `pending_elicitations` stays `[]`, so #1761's
`/elicitations/{id}/resolve` route never fires and there is nothing to resolve even if you
find it. The pane cheerfully prints "bypass permissions on" while the policy has already
overruled the flag.

**Signature — all four together, and nothing less is this bug:**

| Signal | Value |
|---|---|
| where the prompt renders | the **tmux pane only** — invisible to every probe in this file |
| `pending_elicitations` | **`[]`** (empty, not populated — that is the whole trap) |
| `status` | **`running`**, with a **frozen** history |
| last history item | a **`tool_use` with no matching `tool_result`** — usually `Edit` |
| ~3600s later | `runner_disconnected` (the idle timeout, not a crash) |

**One line to check it by:** `status: running` **and** `pending_elicitations: []` **and** a
last item that is a `tool_use` with no `tool_result` ⇒ this bug. Any other combination is
one of the failures above, not this one.

**Cause.** An enterprise managed-settings policy — on macOS
`/Library/Application Support/ClaudeCode/managed-settings.json` with
`disableBypassPermissionsMode: "disable"` and `allowManagedPermissionRulesOnly: true`. Org
policy is evaluated **before** any launch flag, so on such a host:

- `--permission-mode bypassPermissions` is a **silent no-op**;
- `acceptEdits` cannot add rules, and neither can `--allowedTools` — only the managed
  allow-list applies, and it contains no `Edit`, `Write`, `git commit`, `make …`,
  `Monitor`, or `mcp__omnigent__sys_*`;
- so the flags in this skill's launch payloads are necessary but **not sufficient**, and
  their presence is not evidence of anything.

**`-p` mode is unaffected** — a one-shot `claude -p …` never reaches an interactive
permission prompt, which is why path C's `-p` dispatches kept working while every
interactive session on the same machine wedged. That divergence is a diagnosis clue, not a
recommendation to switch paths.

**The fix is at the runner, not the dispatch.** The runner **must** launch through
`claude-home-unattended` (the `hide-claude-managed-settings` skill's Seatbelt wrapper plus
the watcher that answers Claude Code's blocking "Settings Error" dialog), wired at
Omnigent's config layer:

```yaml
# ~/.omnigent/config.yaml
harness:
  claude-native:
    command: /Users/<you>/.local/bin/claude-home-unattended
```

**Check it before you dispatch, not after you lose a day.**

```bash
make host-preflight     # asserts the override + `claude-home --check`; ~2s, read-only
```

`make host-preflight` proves the *wiring*. Only a live one-tool session that actually
`Edit`s a scratch file proves the wiring *works* — that probe is **mandatory before the
first dispatch of a wave** (`wave-kickoff` Step 3b, "Pre-dispatch write probe"). Run it
for a lone dispatch too whenever the host's configuration is not known-good: wave
2026-09-13 spent ~$20 of tokens and a day discovering, six sessions in, what the probe
answers in 30 seconds.

## Step 6 — surfacing

There is no pane to focus and no deep link to send — the upstream pane-registration
bug the Superset path fought is simply absent, because there is no pane.

- The session appears in the **omnigent session rail**, addressed by
  `conversation_id`. Report the id and the structured title together: the title is how
  a human finds it in a list, the id is how every tool addresses it.
- `omnigent attach <conversation_id>` puts a TTY on a live session without spawning
  anything.
- The **same event POST** is the nudge/interrupt channel: a follow-up user message
  either starts a continuation turn (idle session) or coalesces with pending input
  (busy session). `sys_session_send` does the same from inside a turn. A nudge keeps
  the session's context — it is the cheap salvage path, not a relaunch.
- Path-C sessions are also visible locally: `tmux attach -t worker-<issue>`.
