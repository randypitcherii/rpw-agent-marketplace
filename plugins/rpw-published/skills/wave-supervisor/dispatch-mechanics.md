# Dispatch mechanics — worker launch, claim handoff, durable logs

Companion to [SKILL.md](SKILL.md) step 3 (#531). Dispatch is one
supervisor-owned worker per issue, in that issue's worktree; the human-visibility
layer is the Omnigent session rail, addressed by `conversation_id` (there is no
pane — ADR-2026-08-14 (Omnigent dispatch)).

## Compose over the substrate — what each existing layer owns

Executable cross-workspace orchestration is a runtime/`rpw` concern
(ADR-2026-05-27), so a supervisor invents no parallel mechanism for it. Session
launch, Gate-vs-Autonomous prompts and liveness belong to `wave-kickoff` (#795)
and `dispatch-launch`; claim coordination to the claim protocol below
(#245/#246 — the ONLY claim system); branch topology to the
wave branch (inside `/build`, #183); version bumps to the #480 post-merge
auto-bump, never a hand-bumped `plugin.json`.

**Omnigent children by default** (#1081): create each worker as this
supervisor's child; record its `conversation_id`, title and worktree in
`.wave/worker-<issue>.meta.json`. Use `sys_session_send` to resume and
`sys_session_get_info` plus history to check liveness. Bind the child to its
exclusive worktree and verify workspace/branch before sending the brief. Children
may die with the parent runner (#1085): commit early and reconcile before
resuming. Detached `claude -p` is the explicit durability fallback.

For an Omnigent child, verify the selected agent is available and correctly
bound to its exclusive worktree before dispatch. External-CLI fallbacks are
gated by the **Bootability preflight** below, before planning the roster.

## The machinery ships with the plugin — resolve it, then preflight it (#842/#840)

**This skill travels to every repo. For a long time its mechanics did not.**
`wave_worker.py` and the claim protocol were reachable only through
`rpw-agent-marketplace`'s own Makefile, so a supervisor following this file in
another repo found nothing to call and improvised a bare `status: in-progress`
label — a **read-then-write with no compare-and-swap**. On 2026-08-05, on a repo
with no `Makefile` at all, two supervisors each read "unclaimed", each dispatched
a worker at issue #6, and the repo got duplicate implementations on two branches.
Nothing warned anyone: the degradation removed the **safety mechanism**, not the
convenience.

### One entry point, callable from any directory

`plugins/rpw-published/scripts/wave-mechanics.sh` ships inside this plugin, so it
is wherever the plugin is. Every verb acts on **the git repo of the current
directory**, never on the repo the script lives in:

```bash
wave-mechanics.sh preflight              # REQUIRED before the first dispatch
wave-mechanics.sh honor-check <issue>    # is it taken? 0 / 3 / 4
( cd <worker-worktree> && wave-mechanics.sh claim <issue> [<supervisor>] )
wave-mechanics.sh spawn --issue 556 --slug triage-lane --wave-branch wave/<...>
wave-mechanics.sh land  --issue 556 --pr <url> [--report-file <path>]
wave-mechanics.sh lease guard --issue <wave-issue>
wave-mechanics.sh which tools            # where it resolved the machinery from
```

Resolution ladder: `$RPW_WAVE_TOOLS`, then `$CLAUDE_PLUGIN_ROOT` (set for hooks
and MCP servers, **not** in a skill's Bash environment, which is why it cannot be
the only rung), then the script's own checkout (which is also how an installed
marketplace clone resolves), then the target repo, then
`~/.claude/plugins/marketplaces/*/scripts`. Needs `bash`, `git`, `gh` and the
system `python3`; needs **no** `make`, no `uv`, no venv, no repo layout.

**In this repo the `make` targets remain and behave identically** — `make
build-claim`, `make build-honor-check`, `make build-claim-audit`, `make
wave-spawn`, `make wave-land` are now thin wrappers over that script. Prefer the
`make` form inside this repo (it is what this file's snippets use); use the
script anywhere else.

### The preflight is a gate, not a warning

Run it **once per wave, before you size the roster and before the first
dispatch** — earlier than the bootability preflight below, which asks a different
question (*can a worker boot?* rather than *does the machinery exist?*):

```bash
make wave-preflight          # in this repo
wave-mechanics.sh preflight  # anywhere else
```

| Component | Job | Missing means |
|---|---|---|
| `claim` | **attribution** — which branch and which supervisor holds an issue, and whether a rival claim is a sibling worker or a foreign supervisor | no claim protocol at all |
| `lease` | the **only genuine mutex**: `refs/wave-owner/<wave>` via create-only `POST /git/refs`, which GitHub answers **422 on contention**, server-side (#886) | no atomicity — two supervisors both "win" |
| `worker` | spawn/land and the `.wave/worker-<n>.meta.json` ledger | dispatch is unrecorded (#827's false "worker dead") |

`git`, `gh` and `python3` are checked with the claim layer, not below it: without
them a claim can be neither written nor read, so every claim silently succeeds at
nothing.

Exit codes are the contract: **0** dispatchable · **exit 3** the atomic layer is
missing · **4** atomicity is fine but the ledger is not.

**A wave that cannot claim atomically MUST NOT RUN** (#840). On exit 3 the remedy
is one of: install the marketplace so the plugin carries its own tooling; set
`RPW_WAVE_TOOLS=<dir with wave_worker.py + wave_owner.py>`; or run **one worker at
a time, by hand**, and say so in the wave plan. Never substitute a label — that is
the exact non-atomic improvisation that caused the incident. On exit 4, dispatch
is hand-run and unrecorded: treat it as a stop unless you write the acceptance
into the wave plan.

**Labels, comments and assignees are all unconditional writes.** GitHub's
`POST /issues/{n}/assignees` adds up to 10 assignees and does not replace existing
ones, with no conditional-write parameter — so a second claimant is *added*, not
rejected, exactly like a label. An assignee is **not** a compare-and-swap
primitive; the create-only ref is the only one here that can fail on contention,
which is why the lease is acquired first and why its absence is a stop.

### Where this is going (do not re-decide it here)

**#907** is the open P0 epic that owns the carrier question — whether invariant
mechanics should ship as `rpw` CLI verbs (its recommended Option D) rather than as
`make` targets — with an ADR as its Phase 1. The entry point above is the interim
that gets this skill off a repo-only `make` dependency **without** pre-empting
that choice. Two consequences today: the verbs and exit codes are stable, and a
**mirror-only plugin install** carries the claim script but not the root
`scripts/*.py`, so `preflight` reports `lease`/`worker` absent there. That is
honest, not broken — the remedy is `RPW_WAVE_TOOLS` or a full marketplace install.

## Cutting the wave branch (SKILL.md step 2)

The wave branch is cut off the helper's ref — never a hand-written base:

```bash
BASE=$(make base-ref)   # fork-aware, fetched; #1164
git checkout -b wave/<YYYY-MM-DD>-<slug> "$BASE" && git push -u origin HEAD
```

Name the branch `<YYYY-MM-DD>-<slug>` to match the wave issue, then initialize
`WAVE-STATE.md` before the first dispatch (below). Workers branch off this
branch and PR into it; see
[`merge-and-closeout.md`](merge-and-closeout.md) for the topology and why.

## Wave artifacts (set up once, at wave init)

Both live in the supervisor worktree and are scratch — never committed:

```bash
mkdir -p .wave                                   # per-worker logs + launch metadata
printf '.wave/\nWAVE-STATE.md\n' >> .git/info/exclude   # local-only; no repo file changes
```

`WAVE-STATE.md` is the wave's state of record ([`wave-state-template.md`](wave-state-template.md), #569);
`.wave/` is what the retro miner reads (#570).

## Claim handoff — pre-claim as the worker, not as yourself (#568)

`build_honor_check` compares the claim comment's `branch=` against the branch of
the worktree it runs in. A supervisor that claims from its OWN worktree stamps
the supervisor's branch into the sentinel, so the worker's own honor-check
returns `claimed-by-other` and a correctly-behaving worker refuses to start
(observed live on #556, wave 2026-07-29: the worker exited in 27s and needed a
manual override to resume). Order the steps so the claim is stamped with the
worker's branch:

1. **Honor-check from the supervisor worktree** — `make build-honor-check ISSUE=<n>`
   (`wave-mechanics.sh honor-check <n>` outside this repo).
   A `claimed-by-other` here is a genuinely competing workspace: do not dispatch.
   **A clean claim is not evidence the work is undone** — the same step asks two
   more questions, about an open PR racing you and a merged PR that already
   delivered the issue (#1846): [`delivered-but-open.md`](delivered-but-open.md).
2. **Create the worker worktree and branch** (`dispatch-launch` mechanics).
3. **Claim from INSIDE the worker worktree** — `( cd <worker-worktree> && make build-claim ISSUE=<n> )`,
   or `( cd <worker-worktree> && wave-mechanics.sh claim <n> )` where there is no
   Makefile. Either way the sentinel records `branch=<worker-branch>`, so the
   worker's own honor-check prints `own-claim` and it proceeds.
4. **Name the owner in the brief.** The brief's claim section states the exact
   branch the pre-claim carries — that is the worker's machine-checkable token
   for "this claim is mine" ([`worker-brief-template.md`](worker-brief-template.md)).

If a claim was already posted under the supervisor's branch, don't try to delete
it: state in the brief that the pre-claim is **inherited**, name the supervisor
branch verbatim, and tell the worker that a `claimed-by-other` naming exactly
that branch means proceed — any other branch means stop and report.

## Fence on the files a brief will CREATE, not only the ones that exist (#689)

Conflict-surface analysis reads the tree, so it can only see files that already
exist — and a **predictable new file** is invisible to it. An observed wave had
two workers independently create the same `tests/conftest.py`, causing an add/add
conflict and an avoidable serialization cycle. When two briefs touch the same package, ask what each will
plausibly **create**: `conftest.py`, `CHANGELOG.md`, `AGENTS.md`, `__init__.py`,
`README.md`, `index.ts`, a new `docs/process/<topic>.md`. For each such file
either **name the owner in exactly one brief** (and tell the other worker to
leave it alone, or to note the deferred edit in its PR body) or **plan the
union-merge** and say so up front. Same-wave `CHANGELOG.md` collisions stay in
the cheap-to-merge bucket the 2026-07-31 retro said to keep tolerating; a
`conftest.py` collision is not — it wedges a gate, not a text file.

## Name the destination when a brief can produce an outward-facing artifact (#797)

The stamped brief carries the worker's half of this rule — the surface list, the
preflight, and "a different destination is a blocker you report" — under
[`worker-brief-template.md`](worker-brief-template.md)'s `## Destination fencing`,
which is where the rule lives and the only place it is written. **Your half is the
one thing the stamper cannot supply: the destination itself.** If the task can
open a PR or issue, cut a release or tag, push to the mirror, publish a package,
comment on a third-party thread, or post to Slack, then the `## Task` body you
write must name the exact `owner/repo` **and** base branch. A brief that names no
destination is what turned a correct rebase into a public PR on a third-party
repo in the user's name: the worker had no rule to break.

## Script the mechanical half of the lifecycle (#687)

`scripts/wave_worker.py` (stdlib-only; `make wave-spawn` / `make wave-land` in
this repo, `wave-mechanics.sh spawn` / `land` anywhere else — **resolve and
preflight it first**, above) does the six mechanical steps this file describes,
so the supervisor spends its attention on judgment instead of on ~120 identical
hand-run commands per wave:

```bash
make wave-spawn ISSUE=556 SLUG=triage-lane WAVE=wave/2026-08-01-backlog \
  MODEL=opus [EXTRA_ISSUES="557 558"]   # fetch → worktree add off the wave
                                        # branch → claim(s) from INSIDE the
                                        # worktree → stamp WAVE-BRIEF.md →
                                        # append .wave/worker-556.meta.json
make wave-land ISSUE=556 PR=<url> REPORT_FILE=/tmp/report.md   # append report +
                                        # usage line to .wave/worker-556.log,
                                        # backfill meta `pr`, print teardown
```

`spawn` stamps every **invariant** brief section from
[`worker-brief-template.md`](worker-brief-template.md) — turn-end contract, load
harness rules, environment, claim ownership, delivery — and leaves the `## Task`
and `## Fencing` sections as explicit `SUPERVISOR:` placeholders. That split is
deliberate: the ledger and the boilerplate are mechanical and must be right
100% of the time, while the task statement and the file fence (including the
predictable-new-file call above) are judgment the supervisor still owns. A brief
that still contains a `SUPERVISOR:` placeholder is not ready to dispatch.

Script flags reach the targets through `WAVE_SPAWN_ARGS` / `WAVE_LAND_ARGS` — a
bare `--dry-run` on the `make` line is consumed by `make` itself, which silently
prints the recipe instead of running it:

```bash
make wave-spawn ISSUE=556 SLUG=triage-lane WAVE=wave/<...> \
  WAVE_SPAWN_ARGS=--dry-run              # commands + rendered brief, tree untouched
                                         # — worth doing once per wave, before
                                         # the first cohort
make wave-spawn ... WAVE_SPAWN_ARGS="--relaunch 1"   # salvage relaunch: writes
make wave-land  ... WAVE_LAND_ARGS="--relaunch 1"    # .wave/worker-<n>.r1.log
```

### Four gates run before the worktree exists, and they answer different questions

1. **The wave lease** (#886) — *am I still the supervisor of this wave?*
   `spawn` re-runs `wave-owner-check` on every dispatch and **refuses** when a
   different live supervisor holds the wave. Claiming once at wave start does
   not cover a deliberate takeover mid-wave, and every dispatch after being
   superseded is the #823 P0 all over again. It reads the issue number from
   `WAVE-STATE.md`'s `Wave issue:` field (`WAVE_ISSUE=<n>` overrides), and
   **fails closed** when no owner can be determined — a wave with an unknown
   owner may already have a second supervisor. `WAVE_SPAWN_ARGS=--skip-lease-check`
   dispatches unguarded, deliberately.
2. **The per-issue claim** (#568) — *is this issue taken?* A clean claim on
   every issue tells you nothing about gate 1: on 2026-08-05 both supervisors
   held clean claims.
3. **The brief's citations** (#1087) —
   `make wave-brief-check BRIEF=WAVE-BRIEF.md REF=<fork-commit>` checks existence
   and line range only; whether a premise is still true stays a manual read
   (#1014/#1062).
4. **Already delivered?** (#1846) — *is an open PR racing this issue, or did a
   merged PR already deliver it?* Gates 1–3 all pass on an issue whose work
   landed five weeks ago; wave `2026-09-18-backlog` paid a full dispatch to learn
   that. Hand-run, and a merged-PR hit is a read, never an auto-skip:
   [`delivered-but-open.md`](delivered-but-open.md).

**You do not maintain the `## Workers` table.** Both `spawn` and `land` regenerate
it from `.wave/worker-*.meta.json` after their own guard passes (#1344), so a
dispatched worker cannot be missing from the state of record — the
`2026-08-24-raycast-supercmd` failure, six workers on disk and one row in the
table. Reconcile by hand only when a verb *warns* that the refresh failed:
`make wave-state-workers` (idempotent, lease-guarded, atomic). Statuses no
artifact implies go on the ledger, not into the table:
`make wave-record-status ISSUE=<n> STATUS=merged|abandoned|parked|stalled`.
Details: [`wave-state-template.md`](wave-state-template.md).

`spawn` honor-checks every issue **before** creating the worktree and aborts on a
claim held by another branch (`--claim-branch <supervisor-branch>` for the
inherited case above; `--allow-claimed` to override deliberately), copies the
gitignored env files below into the new worktree, and derives the brief's
Environment sentence from what it actually copied. `land` is mode-A only — a
`claude-p` log is raw stream-json and a markdown append would corrupt it.

## Bootability preflight — REQUIRED before you plan the roster (#819, #825, #498)

**Binary presence is not readiness.** `command -v <harness>` proves a file exists
on `PATH`. It does not prove that harness can reach a task-ready session under the
current CLI version, provider/model config, credentials, MCP/permission policy,
and terminal environment. On the 2026-08-05 visual-quality wave a `command -v`
roster reported six available workers and **three could not boot** — `codex`
(native terminal failed to start), `opencode` (CLI refused as outdated, wants
`opencode-ai@~1.17.7`), `pi` (provider config could not be resolved) — and every
one of those failures was paid for with a real dispatch on a real task: issue #6
burned three dispatches before landing on a worker that could start. A roster
that reports capacity which does not exist is worse than no roster, because
cohort sizing and review pairing get planned against fiction.

**Probe once per wave, per dispatch target, before the plan is written.** Never
treat `command -v` output as a roster.

- **External-CLI fallback (explicit mode B):** run the exact invocation shape you will fan out and require exit 0 with no `Error:` line:

  ```bash
  ( cd <any-worktree> && claude -p "reply ok" --model <pinned> \
      --permission-mode acceptEdits --allowedTools Bash \
      --output-format stream-json --verbose ) </dev/null | tail -2
  ```

  **Bound the probe** — a wedged CLI hangs instead of failing, and macOS has no
  `timeout` by default: `cmd & p=$!; ( sleep 60; kill $p 2>/dev/null ) & wait $p`.
  The probe also catches flag drift, because the CLI's flag contract moves under
  you and a snippet that worked last wave can be rejected this wave. Five workers
  spawned against a bad command is five dead workers, and #498 was only caught in
  seconds because spawn-failure notifications happened to fire.


**Record a typed result per target and cache it for the wave** in
`.wave/roster.json`, one line per target, so the probe cost is paid once and
every later relaunch reads the same verdict instead of re-deriving it:

```json
{"target": "claude-p", "state": "ready", "probed": "2026-08-11T18:04:11Z"}
{"target": "opencode", "state": "outdated", "detail": "wants opencode-ai@~1.17.7",
 "remediation": "npm i -g opencode-ai@~1.17.7"}
```

`state` is exactly one of:

| `state` | Means | Do |
|---|---|---|
| `ready` | exited 0, task-ready | dispatchable |
| `absent` | not on `PATH` | drop from the roster |
| `outdated` | booted, refused on version | drop; record the exact upgrade command as `remediation` |
| `provider-unresolved` | binary fine, model/provider config will not resolve | drop; record the resolution error verbatim |
| `prompt-never-ready` | process started, never reached a prompt inside the bound | drop; record the last output line — an enterprise-policy warning is not readiness and must not be read as one |
| `classifier-blocked` | the probe was refused by the permission classifier, not on its own merits | not a target failure: use an available Omnigent child agent |

Any `state` other than `ready` is a **roster removal, not a retry**: drop the
target and dispatch without it. Do not re-probe a dropped target mid-wave unless
you have run its `remediation` first.

**Disclose an under-strength roster in the wave plan, before the first dispatch.**
If the probe leaves fewer dispatchable targets than the plan assumes — and
specifically **fewer than two vendors when the plan calls for cross-vendor
review** — write that into the wave plan and `WAVE-STATE.md` and either re-scope
the wave or state plainly that cross-vendor review is unavailable. A roster gap
found at review time means the wave already ran without the guarantee it was
planned around.

## Launch A — Agent tool, background (legacy attended-session fallback)

This legacy path remains available only when the current Omnigent harness cannot create child sessions and an attended worker is suitable.

Mode A is **asynchronous whether or not `run_in_background` is passed** — the tool
result is launch metadata, never the agent's work. Budget 3–5 minutes before a
worker's first visible artifact and do not probe before then (#773).

**Brief file per worktree + one-line pointer prompt** (same long-prompt hazard
the `dispatch-launch` skill documents — put the brief on disk, keep the prompt
short):

```bash
cat > <worker-worktree>/WAVE-BRIEF.md <<'BRIEF'
<the filled-in worker-brief-template.md>
BRIEF
```

```
Agent(
  subagent_type: "general-purpose",
  description: "wave-worker-<issue>",
  model: "opus",                 // pin it; wave work is multi-file
  run_in_background: true,
  prompt: "Read <worker-worktree>/WAVE-BRIEF.md and execute it exactly.
           Work only in that worktree."
)
```

Properties that matter to the supervisor: task-completion notifications arrive
for free **while the supervisor session is alive** (the primary liveness signal,
[`supervision.md`](supervision.md)); `SendMessage` resumes a stalled worker **with
its context intact**, which is the cheap salvage path mode B lacks; and no env
scrubbing, flag pinning, or `--allowedTools` wrangling is needed, so the
flag-drift class of spawn-death (#498) cannot happen. Mode A removes that class
of death. It does **not** remove the turn-boundary class immediately below.

The cost is observability: there is **no stream-json**, so cache/token
breakdowns are coarser — see the log contract below for what you capture instead.

### Mode-A children die at the supervisor's turn boundary (#881)

"Mode A survives being left alone" is **conditional on the supervisor session
staying alive**, and that condition is false in a durable, headless, or omnigent
supervisor session: such a session goes idle when the turn ends, and its
background children die with it. On wave #862 the phase-1 worker (#732+#809) was
dispatched with `run_in_background: true` and the supervisor then ended its turn —
no `.wave/worker-732.log` was ever written, the worktree stayed at the fork
commit, and no process referenced it. It happened **twice** (dispatch, then a
naive re-dispatch) before a `SendMessage` nudge revived the original agent from
its transcript. This is the #495 failure shape at the supervisor's own level.
Under interactive Claude Code the parent session persists and the free-notification
guarantee holds; **do not carry that guarantee into a durable session.** This
section describes only the legacy Agent-tool path. For the current default,
Omnigent child sessions, follow their `sys_session_get_info` liveness polling
contract and read their history before relaunch; the parent-runner durability
caveat is #1085 above.

After every mode-A dispatch, do **one of these two** before your turn may end —
never neither:

1. **Stay in-turn until you have observed a first artifact for each worker in the
   cohort:** growth of `.wave/worker-<n>.log`, or a first commit or dirty file in
   its worktree. Poll in the foreground. Budget 3–5 minutes before the first
   artifact and conclude nothing before then (#773).
2. **Arm an explicit liveness mechanism that cannot go idle** — a `Monitor` over
   the cohort's logs, or a scheduled wake — so the session is re-entered while
   un-observed children are outstanding. Arm it **before** the dispatch, not after.

**Death detector — a three-part conjunction; all three parts are required:**

1. The dispatch layer reports no live task for that worker (`ListAgents` does not
   list it, or a terminal `task-notification` arrived; mode B: `kill -0 <pid>`
   fails; an omnigent child: `sys_session_get_info` reports `status: failed` or
   `runner_online: false` — its notification may never come, #853/#1037), **and**
2. `.wave/worker-<n>.log` was never created, **and**
3. the worktree is still at the fork commit with no untracked work.

Parts 2 and 3 on their own are the **#827 false-death inference** — a healthy
worker matches both for its first minutes. Part 1 is the evidence; 2 and 3 only
corroborate it. With all three present, that is death rather than progress — and
the worktree stays occupied until you have confirmed termination (**One worktree,
one worker**, below).

### The supervisor's own runner dies too — mid-turn (#974, wave `2026-08-11-backlog`)

Everything above is a **child** dying; the supervisor's runner died twice on this
wave, mid-turn. That breaks mitigation 1 above — "stay in-turn until you have
observed a first artifact" only survives a death at a turn *boundary*, so it is a
**promptness** strategy, not a durability one. Only mitigation 2, a liveness
mechanism that re-enters the session, is durable.

**Blast radius, measured twice each:**

| Worker mechanism | When the supervisor's runner dies |
|---|---|
| Detached `claude -p` (mode B) | **survives** — reparented to init (`ppid=1`) |
| Mode-A Agent-tool child | dies with the session (#881, above) |
| Omnigent child session | **dies with the runner** (#1085) |

Omnigent child work can be lost on runner death (#1085): commit early and reconcile before resuming. Detached `claude -p` is the explicit escape hatch when parent-independent durability is required.

On resume, reconcile actual state (`git log`, `gh pr list`, worker worktrees and child histories) before proceeding.

## Launch B — headless `claude -p` (FALLBACK)

```bash
( cd <worker-worktree> && claude -p "<prompt>" --model <pinned> \
    --permission-mode acceptEdits --allowedTools Bash \
    --output-format stream-json --verbose ) \
  &> <supervisor-worktree>/.wave/worker-<issue>.log &
```

Headless gotchas (all hit live): **let the child inherit your Anthropic env — do
NOT scrub `ANTHROPIC_BASE_URL` / `ANTHROPIC_CUSTOM_HEADERS`** (#1012). On a
proxy-backed machine `ANTHROPIC_BASE_URL` *is* the auth path: it points at the
machine-local LLM proxy that owns the pooled Databricks OAuth (#953), and
`ANTHROPIC_AUTH_TOKEN=<proxy-placeholder>` is a deliberate non-secret placeholder. Scrubbing
it sends the child to the public API with a fake credential — the exact failure
the old `env -u …` prefix claimed to prevent. Follow the machine-local proxy's own configuration documentation. Evidence:
one wave dispatched 13 detached `claude -p` children with fully inherited env and
every one booted and produced work. Also pin `--model`; unattended workers
need `--allowedTools` / `acceptEdits` or they permission-wedge;
**`--output-format stream-json` requires `--verbose` under `--print`/`-p`** — without
it the CLI exits immediately with
`Error: When using --print, --output-format=stream-json requires --verbose`, which
is how all three of one cohort's workers died at spawn (#498).

The redirect target is **absolute and in the supervisor worktree** on purpose: a
relative path lands the log inside the worker's own worktree, where it is
invisible to the miner and at risk of being committed.

Mode B's readiness is the `state: ready` verdict from the **Bootability
preflight** above — probe before the first cohort, never at dispatch time. A
non-zero exit or an `Error:` line means **fix the command, do not dispatch.**

### Mode-B liveness is parsed, never grepped (#974/#971)

`kill -0 <pid>` proves a process exists, not that it is *working*, and byte growth
is the weak form of the signal. Parse the log: **tool-use count, error count, and
the final `result` line's `subtype`** — that line is this substrate's only terminal
signal, since a detached child notifies nobody and a bridge event claiming
otherwise is #971's false completion. Both guards below were hit for real on
`2026-08-11-backlog`:

```python
import json
tools = errors = 0; subtype = None
for line in open(log):
    try: d = json.loads(line)
    except ValueError: continue
    if not isinstance(d, dict): continue           # a line can decode to a bare string
    if d.get("type") == "result": subtype = d.get("subtype")
    content = (d.get("message") or {}).get("content")
    if not isinstance(content, list): continue     # content is not always a list
    for b in content:
        if not isinstance(b, dict): continue
        tools += b.get("type") == "tool_use"
        errors += bool(b.get("is_error"))
```

## One worktree, one worker (#827)

A worktree is one directory, not a branch pair: two live agents inside it
overwrite each other's files with **no conflict detection**, so anything either
produces is suspect. On the 2026-08-05 wave a supervisor read "still at base
commit" as death and re-dispatched onto the same issues and the same worktrees. A
process audit then found two `claude` workers inside `w-issue-4` and two
`cursor-agent` workers on `w-issue-6`; the worker that session had written off as
gone opened its PR at 22:05, having been live the whole time.

- **A worktree admits exactly one worker.** Before dispatching into a worktree
  that already exists, read its launch record and its processes:

  ```bash
  cat .wave/worker-<n>.meta.json                       # launch lines; `pr` still null?
  make wave-sweep WORKTREE="<worktree-path>"           # anything live inside it (#644/#1785)
  ```

  A launch line whose worker you have **not** confirmed terminated means the
  worktree is **occupied**, and the second dispatch must **fail loudly** — refuse
  it and report the occupant, do not proceed quietly. A `wave-spawn` at an
  existing worker worktree path is an abort, never a silent reuse.
- **Terminate before you replace.** Reusing a worktree requires an explicit cancel
  of the prior worker (`TaskStop` in mode A, `kill <pid>` in mode B) **and**
  confirmed termination. The cancel returning is not confirmation; the sweep
  above printing `outcome=clean` is. `outcome=unprovable` is **not** that
  confirmation — it means no reader could read the process table (#1785), so as
  far as this decision goes the worktree is still occupied. Only on a clean
  sweep relaunch into it (salvage protocol, [`supervision.md`](supervision.md)).
- **When in doubt, take a fresh worktree.** A second worktree costs disk. Two
  agents in one costs the work.

## Long runs are supervisor-owned (#495)

Decide at plan time who executes anything that can outlive a worker session —
live eval runs, multi-hour builds, warehouse-backed jobs:

- **Worker-sized** (fits in-session, e.g. `make check`): the worker runs it in the
  **foreground** and polls it to completion. Backgrounding it and ending the turn
  is the failure the brief template forbids — nothing re-invokes a headless
  worker, so the run dies or completes unattended and unread.
- **Longer than a worker session:** the **supervisor** owns the run from the
  start. The worker's scope shrinks to code + the run protocol (the exact command,
  its inputs, how to read its output); the supervisor executes it detached, with a
  stall-aware watcher over the log ([`supervision.md`](supervision.md)).

Evidence: on issue #459 the same worker twice backgrounded a live eval run and
ended its session with "I'll continue when it finishes" — two dead runs and $6.87
burned, even after a salvage prompt explicitly forbade it. Splitting it into
worker-delivers-code / supervisor-runs-it is what finally landed the run.

## Provision gitignored env files into the new worktree (#496)

**Gitignored env files do not travel with branches.** A fresh worktree or clone
starts with none, so the first command that needs one dies at the door —
`FileNotFoundError: missing dev.env; copy template.env first` killed a baseline
run whose `libs/rpw_evals/dev.env` existed only in some other worker's worktree.
Copy them from a checkout that has them, right after creating the worktree and
**before** spawning the agent:

```bash
SRC=<checkout-that-has-them>   # the main clone: dirname "$(git rev-parse --git-common-dir)"
DST=<new-worktree>
git -C "$SRC" ls-files --others --ignored --exclude-standard \
  | grep -E '(^|/)[^/]*\.env$' \
  | while read -r f; do
      mkdir -p "$DST/$(dirname "$f")" && cp "$SRC/$f" "$DST/$f" && echo "env: $f"
    done
```

(Tracked `template.env` files are unaffected — `--others` lists only untracked
files, so this copies exactly the local-only ones.) Then tell the worker in its
brief where env files came from, so a missing one reads as "re-run the copy",
not "the repo is broken".

## Durable, issue-keyed logs (REQUIRED — #570)

Wave 2026-07-29 produced zero `worker-*.log` files; its retro had to reconstruct
duration and cost by hand-joining Cursor terminal artifacts (`849019.txt`, …) to
issues through each terminal's `cwd`. Every launch must leave a durable artifact
keyed by ISSUE, not by terminal id:

- **`.wave/worker-<issue>.log`** — contents depend on the dispatch mode:
  - **Mode B (`claude -p`)** — raw stream-json, unfiltered. Never pipe it
    through `jq`/`grep`/`tee -a` on the way to disk: the miner needs the untouched
    `result` and usage events to compute duration and token/cache totals.
  - **Omnigent child (default)** — the child's **final report verbatim**, followed
    by an available usage line from its history or runner metadata. **The
    supervisor writes this file.** Read the child's history before recording its
    completion; notifications and `sys_read_inbox` are not authoritative for
    child-session liveness.
- **Mode A (legacy Agent tool, #636)** — the agent's **final report verbatim**,
    followed by one usage line transcribed from the task-completion notification.
    The supervisor writes this file, not the worker (#1152).

    ```
    usage: tokens=<in>/<out> tool_uses=<n> duration=<Xm Ys> dispatch=agent-tool
    ```

    **Stream-json-derived cache metrics are unavailable in this mode** — there is
    no per-turn event stream to read, so cache-read/cache-write and per-turn
    timing are simply absent. Say so in the retro rather than reporting zeros.
    The miner's `MISSING` preflight is satisfied by the report + usage line;
    inventing a fake stream-json wrapper is worse than the coarser numbers.
- **`.wave/worker-<issue>.meta.json`** — written at spawn, one line per launch:

  ```json
  {"issue": 556, "issues": [556], "branch": "worker/556-slug",
   "worktree": "/abs/path", "wave_branch": "wave/<YYYY-MM-DD>-<slug>",
   "model": "<pinned>", "session": "<Omnigent conversation_id>",
   "started": "2026-07-30T18:04:11Z", "log": ".wave/worker-556.log", "pr": null,
   "dispatch": "agent-tool"}
  ```

  `"issues"` lists every issue a multi-issue worker carries (primary first) and
  `"wave_branch"` records which wave the launch belongs to, so the miner never
  has to infer either from the branch name.

  `"dispatch"` is `"omnigent-child"`, `"agent-tool"` or `"claude-p"` — it tells the
  miner which log shape to expect and which metrics it may legitimately not find.

  Backfill `pr` when the worker reports its PR URL — that link is what lets the
  miner score cost against delivered diff.
- **Resumes append to the same issue key.** A salvage relaunch writes
  `.wave/worker-<issue>.r1.log` (`.r2`, …) — for Omnigent children, the *same supervisor write*
  against the relaunched child's report; for detached mode B, the new redirect target — and
  appends another metadata line naming the same issue. The open-ended `.r<k>` is a
  **naming** scheme, not permission to keep re-dispatching: what bounds relaunches
  is the strike rule in [`supervision.md`](supervision.md) step 2 (#1021). One
  worker's whole story — including the 27s claim-conflict exit before the 557s
  successful run — is greppable by issue number. In mode A a
  `SendMessage` nudge is not a relaunch: append the resumed worker's final report
  and a second usage line to the existing `.log`, no new file.

Never let a resumed session land under a fresh, unrelated name; that is exactly
the split-attribution failure #570 was filed for.

## Executor note

`rpw build --live` speaks wave topology via `--pr-base <wave-branch>` +
`--no-merge` (#346). If an executor fights wave rules by construction, **fall
back to a launch mode above rather than patching mid-wave.**

## Base-branch resolution (#1164)

The wave branch — and every worktree cut for this wave — is based on the **fetched
upstream default branch**, resolved by `plugins/rpw-published/scripts/git-base-branch.sh`
(`make base-ref`, or `make base-worktree PATH_=… BRANCH=…` for branch+worktree in one
step). It detects a fork, bases off the **parent** repo's remote rather than the fork's,
resolves that remote's default branch dynamically (no `main`/`master`/`production`
literal anywhere), and fetches before handing the ref back.

Branching off a local ref, or off the fork's default when the repo has a parent, is what
fills a PR with already-merged work and conflicts on contact. Two rules follow:

- **Never hand-write the base** in a `checkout -b` / `worktree add`. Call the helper.
- **Exit 3 means a fork with no parent remote.** Add the `upstream` remote it names in
  its error, then re-run. Falling back to `origin` is the bug this prevents.

Workers branch off the **wave branch** — a deliberate base the supervisor already cut
from the helper's ref — so they use the wave branch directly, not `make base-ref`.

## Watch `production` for overlap with in-flight fences (#1153)

The wave branch takes `production` in **exactly once** — that rule does not change
([`merge-and-closeout.md`](merge-and-closeout.md)). What #1153 adds is the *moment*:
the once-only sync gets a **trigger** instead of a supervisor's whim.

At each checkpoint, alongside the tally, ask whether `production` has moved a file
an in-flight worker owns:

```bash
git fetch origin production
git diff --name-only HEAD...origin/production   # what production moved under us
```

Intersect that list against the in-flight workers' fences:

- **Non-empty intersection ⇒ sync `production` into the wave branch now**, while
  those workers are still live and can own their own files.
- **Empty ⇒ do nothing.** The sync safely waits for close-out — the common case,
  and it stays cheap.

Deferring has a measurable cost. Wave `2026-08-17-llm-proxy` synced at close-out,
after `production` shipped #1108 / PR #1142 (the Unity Catalog v3 cutover) editing
the same three files as in-flight #1077 — four conflicts resolved by hand during
close-out with the wave PR blocked behind them, and one a real defect: both sides
had independently added a 501 failure class and the broader branch swallowed the
narrower one, so a stale base URL was reported as a withdrawn pin (#1151). Sync
commit: `ddd2917`.

The check is one command a supervisor runs at each checkpoint; it is not a merge,
so it does not spend the exactly-once sync by itself — the sync still happens once,
whenever the check first returns non-empty.

