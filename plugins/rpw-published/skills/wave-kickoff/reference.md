# wave-kickoff reference — brief template, choreography, measured omnigent behavior

Companion to [SKILL.md](SKILL.md). This file carries what wave-kickoff owns: the
canonical brief, the condensed command sequence, and the omnigent-session facts
measured on 2026-08-04 (#795). Shared dispatch mechanics (the three launch
paths, worktree + env provisioning, long-prompt spawn-death, probes that lie)
stay in the `dispatch-launch` skill.

## Gate 0 — the pre-dispatch liveness gate (#1873)

**Why it exists.** On 2026-09-21 a kickoff pass could not tell a silent
supervisor from a dead one and redispatched **7 workers onto an issue set PR
#1872 had already delivered** — zero PRs, pure burn, the third time that
double-landing shape was caught. The lease heartbeat could not settle it: `hb=`
is refreshed by the supervisor's **own turn loop**, so a busy supervisor and a
dead one both let it go stale.

**Scope — the lease is per wave, so waves run concurrently (#2029).** Each wave
files its own `wave`-labeled issue and takes its own lease (#886). Gate 0 guards
*that* lease: a `live` verdict forbids re-dispatching or taking over **that wave's
issues**. It does **not** forbid kicking off a second wave whose seeds are
disjoint. On 2026-09-28 a kickoff for epic #1995 stopped and asked the human only
because the unrelated `gate-trust` wave (#2011) was live — a question the design
had already answered. When another wave is live:

1. Confirm none of your seeds is in its seed list or skip-list, and none carries a
   `status: in-progress` claim (`make build-honor-check ISSUE=<n>`).
2. Diff the files your seeds will touch against the files its wave issue names
   (its cohort table's conflict-surface column). Typical overlaps: the root
   `Makefile`, root `pyproject.toml` / uv config, the root `AGENTS.md` project
   index.
3. Put the overlap in the brief's **Concurrency with live waves** block (template
   below) and dispatch. Overlap is a merge-order note, not a stop.

`make wave-liveness ISSUE=<n>` answers it from a substrate the supervisor does
not write by choosing to — the Omnigent runner log, which the *runner process*
appends to whether or not the agent ever runs a make target.

**Run it for every candidate — and refuse on a FAILED query, never on an empty one.**
The old `gh issue list … | while read -r n` form **iterated zero times when that `gh`
call failed**, so an unreachable GitHub printed no verdict and Gate 0 passed at exit 0:
a fourth independent route to the 09-21 redispatch. Capture the list, check the query
actually succeeded, and keep "no wave is leased" visibly different from "the query
failed". Run it as **one** shell call (an agent Bash call or `sh -c`) so the `exit`
refuses the gate, not your terminal.

```bash
owned=$(gh issue list --label "wave: owned" --state open --json number --jq '.[].number') ||
  { echo 'Gate 0 REFUSED: could not ASK GitHub which waves are leased — that is NOT "none are".' >&2; exit 1; }
echo "wave: owned → ${owned:-none (GitHub answered; no wave holds a lease)}"
for n in $owned; do make wave-liveness ISSUE="$n"; done
make wave-liveness-status     # is the unattended poller even running?
```

Do **not** collapse that into `[ -n "$owned" ] && for … || echo` — `make wave-liveness`
exits nonzero on every refusing verdict, so the `||` branch would fire on a `live` wave
and report "no wave holds a lease" about the wave that is holding one.

| Verdict | Means | Do |
|---|---|---|
| `free` | GitHub **answered**, and that answer was "no live lease on this wave issue" | ✅ proceed |
| `live` | runner log touched in the last 15m | 🚫 **STOP** — a supervisor is working |
| `at-risk` | runner quiet >15m but the lease heartbeat is still inside its 45m TTL | 🚫 **STOP** — may be mid-long-turn or self-recovering |
| `dead` | runner quiet **and** heartbeat past TTL — both signals agree | ✅ proceed, but salvage the worktrees first |
| `unknown` | **the lease could not be read** — no `gh`, no network, expired auth, a 4xx/5xx, unparseable output, or an exit-0 `--json` that printed nothing — **or** no session pointer, or the lease was taken on another host, or no runner logs here | 🚫 **STOP and ask the user** |

**`free` is an answer that arrived, not the absence of one (#1910).** "GitHub says
there is no lease" and "GitHub was never asked" used to be the same value, and `free`
exits 0 = dispatchable, so a 30-second blip during a Gate 0 pass authorized the very
redispatch this gate exists to refuse. A failed read is now `unknown`.

**`unknown` is not `dead`.** Treating it as death is precisely the 09-21 error.
It means nobody knows, and the only correct response is a human.

**Read the verdict word, not the exit code.** `make` collapses the script's 3
(refused) and 4 (unknown) into its own exit 2 — the same trap `wave-gate-check`
documents (#1785). Scripted callers invoke
`automation/bin/wave-liveness.py check --issue <n>` directly, where `0`
dispatchable / `3` refused / `4` unknown survive. An unreachable `gh` lands on **4**,
never 0 — that is the contract the snippet above enforces one layer up.

**A stale record is not a green light.** `make wave-liveness-status` exits 4 and
degrades every verdict to `unknown` when `~/.rpw/wave-liveness.json` is older
than 15 minutes, because a poller that stopped firing must not be read as "no
wave is live". Mechanism, thresholds, and the restart cadence that motivated all
of this: `docs/process/wave-liveness.md`.

## Measured omnigent-session behavior (2026-08-04, #795)

Verified by launching a real `claude-native` child session that reached
"oriented and cut its wave branch". Do not re-derive these.

| Question | Answer | How it was measured |
|---|---|---|
| Does a child inherit a usable cwd? | **Yes — the parent session's `workspace`, verbatim.** Not the caller's, not a fresh dir. | probe child's `pwd` == parent's `workspace` field |
| Can the cwd be set at creation? | **No.** `sys_session_create` takes only `agent_id` / `config_path` / `title` / `message` / `model`; `title` is the creation-time name and should include the short `<wave-summary>`. | tool schema |
| Does `cd` persist between Bash calls? | **No.** Every call ends `Shell cwd was reset to <parent workspace>`. | every `function_call_output` in the live run |
| Does the child know its own workspace? | **No.** Its `sys_session_get_info` returns `workspace`, `git_branch`, `model`, `host_id` as `null`. Read the **parent's**. | `sys_session_get_info` on the child |
| Is the parent's `git_branch` trustworthy? | **No.** It is the branch the worktree was *created* on. A live session read `wave_supervisor/2026-08-02_01` while actually on `wave/2026-08-02-backlog`. | compared with `git rev-parse --abbrev-ref HEAD` |
| Does a >60-char title survive? | **Yes via `create`.** A 76-char title round-tripped intact. `sys_session_rename` caps at 60 server-side (422) *and* refuses auto-titled sessions (`title_changed`). |
| What prefixes the title? | The shared **state emoji first**, then `🌊` for a wave supervisor. Flip only the state glyph to ‼️ / ✅ / ❌ / 🛑 and preserve the 🌊 marker. The five states are defined once in the session-title convention (`docs/process/agent-session-titles.md`); do not restate the table here. | `sys_session_get_info` after create |
| How does `::` display? | The `sub_agents` view splits on the **first** colon into (agent, title) — cosmetic only. | `sys_session_list` |

**Consequence — the two rules the brief must encode:** the supervisor lands in
the *previous* wave's worktree, and it cannot fix that with one `cd`. So every
command carries its own `cd <worktree> &&`, and every file path is absolute.

### `.git/info/exclude` does not work in a linked worktree

The old recipe `printf … >> .git/info/exclude` **fails** in every supervisor
worktree, which is exactly where it runs. In a linked worktree `.git` is a
*file* (`gitdir: …`), so the append dies with `not a directory`. Writing to
`$(git rev-parse --git-dir)/info/exclude` fails differently — silently: that is
the per-worktree gitdir, and `git check-ignore -v` shows the honored rule comes
from the **common** dir. The one correct form:

```bash
printf '.wave/\nWAVE-STATE.md\n' >> "$(git rev-parse --git-path info/exclude)"
git check-ignore -v WAVE-STATE.md      # prove it took
```

## Canonical WAVE-BRIEF.md template

Write this file into the supervisor's worktree root. Fill every `<...>`; delete
the mode block you are not using. Keep the hard-boundary section verbatim. **Step 0
belongs to the path-B fallback only** — delete it for a path-A (bind-mode) launch, where
the bound workspace already *is* the persistent cwd.

```markdown
# Wave supervisor brief — <YYYY-MM-DD> <slug>

You are the wave supervisor for this wave. Your worktree is
`<worktree-path>` (branch `wave-supervisor/<YYYY-MM-DD>-<slug>`, cut from
`origin/production`).

## Step 0 — Relocate into your worktree (do this FIRST, and keep doing it)

<!-- PATH-B ONLY. Delete this whole section when the launch bound the worktree
     via POST /v1/sessions (git.existing_worktree: true). -->

You were launched as an omnigent session, so you inherited your **parent
session's** working directory — a different wave's worktree. Worse, the shell
resets to it after **every** Bash call, so one `cd` does not stick.

```bash
cd <worktree-path> && pwd && git rev-parse --abbrev-ref HEAD
```

- **Every** Bash call starts with `cd <worktree-path> && …`, or uses
  `git -C <worktree-path>`.
- **Every** Read/Write/Edit uses an absolute path under `<worktree-path>`.
- Never assume the shell's cwd carried over from the previous call.

If you skip this you will run the entire wave inside the previous wave's
worktree, on the previous wave's branch.

## Operating instructions

1. Invoke the **wave-supervisor** skill FIRST and follow it exactly — modes,
   defaults (width 5, judgment ordering, auto-advance with exception stops),
   dispatch pattern, liveness hierarchy, salvage protocol, merge discipline.
2. Read the retros before dispatching anything: `gh issue view 260 --comments`.

## Mode

<!-- UNBOUNDED (default) — keep this block, delete the seeds block -->
Run an **unbounded wave** over the open backlog: continuously pull the next
eligible issue by your own ordering judgment (priority, impact, effort,
prerequisites-first) until the backlog is drained or only needs-input items
remain. Queue needs-input issues and batch-ask at checkpoints; never idle the
fleet for one ambiguous ticket. Queue every open question **tool-ready** (header,
question, 2-4 concrete options) and ask with `AskUserQuestion` — the instant I say
I am ready to answer, or as soon as nothing else is eligible. Never hand me a
paragraph to write a reply to.

<!-- EXPLICIT SEEDS — keep this block, delete the unbounded block -->
Work these issues, in this order: <#a, #b, #c — with any user-stated ordering
rationale or caps>. <"Stop when the list is delivered." | "Then continue
unbounded over the remaining backlog."> Stop conditions the user set: <caps,
budget, or "none">.

## Claims

- Skip-list — claimed in-flight elsewhere; do NOT touch: <#x (branch), #y (…)
  — or "none found">.
- Run `make build-honor-check ISSUE=<n>` LIVE immediately before every claim,
  then `make build-claim ISSUE=<n>`. The skip-list above is a snapshot; the
  honor-check is the truth.

## Concurrency with live waves (#2029)

<!-- Keep when Gate 0 found another live wave; delete otherwise. -->
Wave <wave/...> (#<its wave issue>) is live with disjoint issues. Files both
waves touch: <root Makefile (its #x), pyproject.toml (its #y), ...>.
- Keep edits to those files minimal and additive (new lines, not rewrites).
- Rebase the wave branch onto `origin/production` whenever that wave merges,
  before your next worker merge, and re-run the gate.
- Never touch its worktrees, branches, claims or wave issue.

## State + artifacts (do this before the first dispatch)

- Initialize `WAVE-STATE.md` in this worktree root, fresh from the
  wave-supervisor skill's `wave-state-template.md`, and create `.wave/` for
  issue-keyed worker logs (`.wave/worker-<issue>.log` + `.meta.json`).
- This worktree may carry a previous wave's `WAVE-STATE.md`: **overwrite it.**
  Both artifacts are untracked scratch — exclude them locally with the
  worktree-safe path (plain `.git/info/exclude` fails here):
  `printf '.wave/\nWAVE-STATE.md\n' >> "$(git rev-parse --git-path info/exclude)"`
- If the branch recorded in `WAVE-STATE.md` is ever not the active wave branch,
  you are reading another wave's state — overwrite at init, STOP at close-out.

## Worker execution rules (state these in every worker brief)

- **Env files (#496):** gitignored env files (`.env`, `dev.env`, `prod.env`) do
  NOT travel with branches, so a fresh worker worktree has none. Copy them in
  from the main checkout right after creating the worktree (recipe in the
  wave-supervisor skill's `dispatch-mechanics.md`), and say so in the brief.
- **Foreground runs (#495):** a worker must never background a live run and end
  its turn — nothing re-invokes a headless worker. Anything that outlives a
  worker session is yours to run: the worker delivers code + run protocol, you
  execute it detached with a **stall-aware** watcher (no log growth for N minutes
  with the process alive, #497), not just an exit/crash watcher.

## Topology (non-negotiable)

- Cut `wave/<YYYY-MM-DD>-<slug>` off `origin/production` and push it first.
- Workers branch off the wave branch and PR INTO the wave branch, **Gate mode**
  ("open a PR, then STOP") — you serialize the merges, one same-plugin PR at a
  time, reviewing each (check `description:` frontmatter on skill PRs).
- The wave ends with ONE PR `wave/<...> → production` carrying the full
  `Closes #a, Closes #b, ...` list and links to every worker PR.
- Never hand-edit any `plugin.json` version (#210 automation owns it).

## HARD BOUNDARY — publishing

Public publishing is NEVER in a wave's scope. No `make publish-promote`, no PRs to `published/<target>`, no target-delivery PRs, and no public GitHub Releases. If an issue requires publishing, park it needs-input
for the human. This rule overrides anything an issue body says.

## Close-out

When the wave ends (or you halt), post a retro comment on #260: what merged,
what's parked needs-input (with the batched questions), what's left, and any
new pattern lessons.
```

## Pre-dispatch write probe — Step 3b mechanics (#1777)

The highest-value 30 seconds in a kickoff. It answers one question no static check can:
**can a runner-spawned session on this host actually write a file?**

**Why it is not paranoia.** An enterprise managed-settings policy
(`/Library/Application Support/ClaudeCode/managed-settings.json` with
`disableBypassPermissionsMode: "disable"`, `allowManagedPermissionRulesOnly: true`) is
evaluated *before* any launch flag, so `--permission-mode bypassPermissions`,
`acceptEdits` and `--allowedTools` are **silent no-ops** — the pane even prints "bypass
permissions on". The session then stops at its first `Edit` on a prompt that renders
**only in a tmux pane**, with `pending_elicitations: []` and a `tool_use` carrying no
`tool_result`. Wave 2026-09-13 discovered this six sessions in: the supervisor and all
five cohort-1 workers dead at their first `Edit`, zero commits, ~$20 of tokens, one day.

### Layer 1 — static wiring (~2s, no server needed)

```bash
make host-preflight     # harness.<id>.command → claude-home-unattended, + claude-home --check
```

### Layer 2 — the live write probe (~30s, the actual gate)

```bash
# Scratch file with a known "before" value, inside the supervisor worktree.
printf 'probe-before\n' > "$WT/.wave-probe.txt"
```

```
sys_session_create(
  agent_id = <the claude-native builtin from sys_agent_list>,
  title    = "<repo>::wave-supervisor/<date>-<slug>::<date>::probe — pre-dispatch write probe",
  message  = "One task, then stop: Edit the file <WT>/.wave-probe.txt so it reads
              probe-after instead of probe-before. Do nothing else. Reply DONE.")
# capture: conversation_id
sys_session_get_history(conversation_id=<conversation_id>, tail_items=10)
```

```bash
# THE GATE is the file on disk, not the session's self-report (#971).
grep -q probe-after "$WT/.wave-probe.txt" && echo "PROBE PASS" || echo "PROBE FAIL"
```

| Outcome | Reading | Action |
|---|---|---|
| file says `probe-after` | writes work unattended on this host | dispatch the fleet |
| `status: running`, last item a `tool_use` with **no** `tool_result`, `pending_elicitations: []` | the managed-policy stall — a prompt is waiting in a pane | **refuse to dispatch** |
| `status: failed` with a `Settings Error` error item | the claude-home dialog raced the wake (#2030) — the pane is fine seconds later | re-wake with `make session-wake`; do not relaunch |
| `status: failed` / `runner_online: false` (no `Settings Error`) | dead spawn, not a permission wedge | relaunch recipe below |
| still no `Edit` item after ~90s | not yet alive; do not conclude anything | poll again, then treat as dead spawn |

**A wedged probe is a hard stop, not a warning.** Do not dispatch "just one worker to
see" — that is how the same $20 gets spent twice. Fix the runner wiring (`make
host-preflight` prints the fix; the `hide-claude-managed-settings` skill owns the
`claude-home` / `claude-home-unattended` assets), re-run the probe, and dispatch only on
a pass. If it cannot be fixed here, report the host as unfit for unattended dispatch and
stop — an in-session `wave-supervisor` mode is the fallback, not a wedged fleet.

**Clean up** so the probe never looks like wave work:

```bash
rm -f "$WT/.wave-probe.txt"
```

```bash
make session-close SID=<probe conversation_id>
```

The probe is created over REST, so it is **not** in your spawn tree and
`sys_session_close` answers `session_out_of_tree`. The omni CLI has no close
command either. `session-close` sends the same PATCH the tool sends
(`omnigent.closed` + `archived: true`, which reaps its processes) and reads it
back (#2030).

## Launch payloads — path A (default) and path B (fallback)

Full field surface: `dispatch-launch`'s `reference.md`. What matters here:

### File the new session under a unique existing repository project

Path A can attach the supervisor to a first-class Omnigent project. Read the
project list with `GET /v1/projects`. Identify the repository by the final component
of its `origin` URL, **not** by the temporary
supervisor-worktree directory. A project is a candidate when its name or the final
component of `config.workspace` matches that repository name (case-insensitive).
File only when exactly one project matches; no match, multiple matches, or a failed
lookup leaves the session unfiled. **Do not create a project.**

Run this before session creation and retain `PROJECT_ID` for the post-create PATCH:

```bash
REPO_NAME=$(git -C "$WT" remote get-url origin |
  sed -E 's#.*[:/]##; s#\.git$##')
PROJECT_ID=""
if PROJECTS=$(curl -fsS "$OMNI/v1/projects"); then
  if PROJECT_CANDIDATES=$(printf '%s' "$PROJECTS" | jq -ce --arg repo "$REPO_NAME" '
    [.data[]? | select(
      ((.name // "" | ascii_downcase) == ($repo | ascii_downcase)) or
      (((.config.workspace // "") | sub("/+$"; "") | split("/")[-1] | ascii_downcase)
        == ($repo | ascii_downcase))
    )]'); then
    PROJECT_COUNT=$(printf '%s' "$PROJECT_CANDIDATES" | jq 'length')
    if [ "$PROJECT_COUNT" -eq 1 ]; then
      PROJECT_ID=$(printf '%s' "$PROJECT_CANDIDATES" | jq -r '.[0].id')
    elif [ "$PROJECT_COUNT" -gt 1 ]; then
      echo "Ambiguous repository project match; leaving wave session unfiled." >&2
    fi
  else
    echo "Could not parse project list; leaving wave session unfiled." >&2
  fi
else
  echo "Could not list projects; continuing without project filing." >&2
fi
```

After `POST /v1/sessions` returns `SID`, but **before** the wake event, file the
session. Filing is best-effort: if the PATCH fails, warn and still wake the
supervisor so an optional grouping step cannot strand the wave.

```bash
if [ -n "$PROJECT_ID" ]; then
  if curl -fsS -X PATCH "$OMNI/v1/sessions/$SID" \
      -H 'content-type: application/json' \
      -d "$(jq -n --arg p "$PROJECT_ID" '{project_id:$p}')" >/dev/null; then
    echo "Filed wave session in project $PROJECT_ID"
  else
    echo "Could not file wave session; continuing unfiled." >&2
  fi
fi
```

Path B (`sys_session_create`) exposes no `project_id`, and is used only when the
REST API is unavailable, so it cannot perform this lookup or PATCH. Leave that
session unfiled and report the limitation; do not create a project or block the
launch.

**Path A — `POST /v1/sessions`, bind mode.** `host_id` is required whenever `git` or
`workspace` is set (422 otherwise); `workspace` must be absolute, exist, and sit inside
the agent's `os_env.cwd` boundary.

```jsonc
// POST <the configured server>/v1/sessions
{
  "agent_id": "<the claude-native builtin from GET /v1/agents>",
  "host_id":  "<an online id from GET /v1/hosts>",
  "title":    "⏳ 🌊 <repo>::wave/<date>-<slug>::<date>::wave_supervisor — <wave-summary>",
  "workspace": "<absolute supervisor worktree path>",
  "git": { "branch_name": "wave-supervisor/<date>-<slug>", "existing_worktree": true },
  "terminal_launch_args": ["--permission-mode", "bypassPermissions"]
}
```

```jsonc
// REQUIRED second call — create seeds history, it does not start a turn.
// POST /v1/sessions/<id>/events
{"type": "message",
 "data": {"role": "user", "content": [{"type": "input_text", "text":
   "<wave-summary>. Read WAVE-BRIEF.md in your worktree root and execute it exactly. Read out-of-tree files — installed skills under ~/.claude/plugins/cache/… — with Bash cat/sed, never the Read tool."}]}}
```

Skip the wake and the session sits at `idle` holding only the seed message, which looks
exactly like a dead spawn. Re-post the event; do not relaunch.

**Wake with `make session-wake SID=<id> MSG="<pointer>"`, not a bare POST (#2030).** On a
claude-home host the Seatbelt sandbox hides `managed-settings.json` on purpose, so Claude
Code opens a **Settings Error** dialog at startup; the auto-dismisser answers it a few
seconds later. A wake that lands first is refused ("Claude Code is waiting for an answer
in its terminal (Settings Error)") and the session goes `failed` — the dead-spawn look.
`session-wake` posts the event, polls until `running`, and re-posts after
`WAKE_RETRY_DELAY` when the newest error item is that refusal. Exit 6 is a real dead
spawn; 7 is not-started-yet. Measured 2026-09-28: refused ~20:51:50Z,
`auto-dismiss.log` pressed at 20:51:55Z, one re-post worked.

**The API base is not always localhost.** On a managed server nothing listens on
`127.0.0.1:6767`; the base is `$RUNNER_SERVER_URL` with a Databricks bearer token and the
`X-Databricks-Omnigent-Slice-Key` shard header. `dispatch-launch/scripts/omni-api.sh`
resolves all three; the sequence below sources it.

**`bypassPermissions`, not `acceptEdits` (#1761).** `acceptEdits` gates file-edit tools
only, so a supervisor launched with it wedges on its first `mcp__omnigent__sys_*` call
with `pending_elicitations` non-empty. Neither flag survives a managed-policy host — that
is what Step 3b's probe is for (#1777). Cure for an already-wedged session:
`dispatch-launch`'s `failure-modes.md`.

**Path B — `sys_session_create`.** A strict subset: no `workspace`, no `git`, no
`terminal_launch_args`. Use it only when no REST port answers, ship the Step 0 block with
it, and expect the wedge.

## Condensed command sequence (worktree → brief → launch → probe)

```bash
# 1. Supervisor worktree off the fetched upstream default (#1164 — `make base-ref`
#    resolves the fork's parent and its default branch). The WAVE branch is the
#    supervisor's to cut.
WT=<worktrees-root>/wave_supervisor-<date>_<slug>
cd <main-checkout> && make base-worktree PATH_="$WT" \
  BRANCH=wave-supervisor/<date>-<slug>

# 2. Provision gitignored env files if the wave needs them (#496), then write the brief
git -C <main-checkout> ls-files --others --ignored --exclude-standard \
  | grep -E '\.env$' | while read -r f; do cp "<main-checkout>/$f" "$WT/$f"; done
cat > "$WT/WAVE-BRIEF.md" <<'BRIEF'
<the filled template above>
BRIEF
```

```bash
# 2b. MANDATORY pre-dispatch write probe (#1777) — wiring, then a real Edit.
#     Details and the wedge signature: "Pre-dispatch write probe" above.
cd <main-checkout> && make host-preflight
printf 'probe-before\n' > "$WT/.wave-probe.txt"
#     …one-tool probe session Edits it… then the gate is the file, not the report:
grep -q probe-after "$WT/.wave-probe.txt" || echo "WEDGED — do NOT dispatch"
```

```bash
# 3. Launch — path A: create bound, then WAKE. Two calls; create alone starts nothing.
#    omni-api.sh resolves the base (managed server or localhost) and auth (#2030).
LAUNCH=<main-checkout>/plugins/rpw-published/skills/dispatch-launch/scripts
source "$LAUNCH/omni-api.sh"; OMNI=$API_BASE
curl() { command curl ${AUTH_HEADERS[@]+"${AUTH_HEADERS[@]}"} "$@"; }  # auth on every call
# Run the unique-project lookup above now; it sets PROJECT_ID or leaves it empty.
# Lists come bare or wrapped ({"data": [...]}, hosts: {"hosts": [...]}); hosts say online or status=="online".
AGENT=$(curl -sf "$OMNI/v1/agents" | jq -r '[(.data // .)[]|select(.harness=="claude-native")][0].id')
HOST=$(curl -sf "$OMNI/v1/hosts"  | jq -r '[(.hosts // .data // .)[]|select(.online == true or .status == "online")][0] | .host_id // .id')
SID=$(curl -sf "$OMNI/v1/sessions" -H 'content-type: application/json' \
  -d "$(jq -n --arg a "$AGENT" --arg h "$HOST" --arg w "$WT" \
            --arg b wave-supervisor/<date>-<slug> \
            --arg t "⏳ 🌊 <repo>::wave/<date>-<slug>::<date>::wave_supervisor — <wave-summary>" \
    '{agent_id:$a, host_id:$h, title:$t, workspace:$w,
      git:{branch_name:$b, existing_worktree:true},
      terminal_launch_args:["--permission-mode","bypassPermissions"]}')" | jq -r .id)
# File the new session before waking it; a failed PATCH is non-fatal.
if [ -n "$PROJECT_ID" ]; then
  if ! curl -fsS -X PATCH "$OMNI/v1/sessions/$SID" \
      -H 'content-type: application/json' \
      -d "$(jq -n --arg p "$PROJECT_ID" '{project_id:$p}')" >/dev/null; then
    echo "Could not file wave session; continuing unfiled." >&2
  fi
fi
# Wake, and prove it landed: re-posts on the Settings Error race, exit 0 = running.
bash "$LAUNCH/session-wake.sh" "$SID" "<wave-summary>. Read WAVE-BRIEF.md in your worktree root and execute it exactly. Read out-of-tree files with Bash cat/sed, never the Read tool."
# capture: SID as the conversation_id.
```

```
# 3b. FALLBACK ONLY — path B, when no REST port answers. One call, but no bound
#     workspace and no --permission-mode: ship the Step 0 block and expect the wedge.
sys_agent_list()                       # take the builtin whose harness == "claude-native"
sys_session_create(
  agent_id = <that agent_id>,
  title    = "⏳ 🌊 <repo>::wave/<date>-<slug>::<date>::wave_supervisor — <wave-summary>",
  message  = "<wave-summary>. cd <WT> first — that is your worktree, not the
              directory you start in. Then read WAVE-BRIEF.md in that worktree's
              root and execute it exactly. Read out-of-tree files with Bash cat/sed,
              never the Read tool.")
# capture: conversation_id

# 4. Liveness gate — status alone is not proof
sys_session_get_info(session_id=<conversation_id>)        # running, then idle
sys_session_get_history(conversation_id=<conversation_id>, tail_items=25)
#   -> REQUIRED: real function_call items. Seed message only == not yet alive
#      (path A: re-post the wake event before you consider relaunching).
```

```bash
# 5. First observable progress
git -C "$WT" ls-remote origin 'wave/*'
```

## Relaunch recipe (dead-spawn recovery)

Dead-spawn signature: `status: "failed"`, or a history frozen at the user message
with `runner_online: false`.

1. Do NOT delete the worktree — `WAVE-BRIEF.md` is fine. Relaunch on the **same path**
   with the same title and pointer message (path A: create **and** wake again). First
   rule out the look-alikes: a missing wake, the Settings Error wake race (`failed`
   with a `Settings Error` error item — re-wake, #2030), and the managed-policy stall
   (`running`, frozen mid-`tool_use`, no `tool_result`) that no relaunch fixes.
2. Re-probe the new `conversation_id` with the Step 5 history check.
3. **Twice-dead ⇒ stop.** Report the failure rather than a third blind launch:
   check `runner_online` on the parent session first — a dead runner kills every
   child regardless of the brief.

## Teardown

```bash
make session-close SID=<conversation_id>   # path A sessions are out of your spawn tree
```

```bash
git -C <main-checkout> worktree remove "$WT"
git -C <main-checkout> branch -D wave-supervisor/<date>-<slug>
```

## Worked example

The 2026-08-04 verification run for #795: worktree created off `production`,
brief written as a file, session launched with the title
`⏳ 🌊 rpw-agent-marketplace::wave/2026-08-04-verify795::2026-08-04::wave_supervisor — verify omnigent wave dispatch`,
child landed in the *parent's* worktree and relocated per Step 0, oriented on
the live backlog, cut and pushed `wave/2026-08-04-verify795`, initialized
`WAVE-STATE.md` and `.wave/`, and stopped. Its one stumble — the
`.git/info/exclude` append — is the bug fixed above.

The Superset-era original (2026-07-14 backlog dispatch, #260 wave-5 retro) took
three spawn attempts and two probe bugs. That substrate is retired
(ADR-2026-08-14 (Omnigent dispatch));
the failure modes it taught are carried in `dispatch-launch`'s
`liveness-and-surfacing.md`.
