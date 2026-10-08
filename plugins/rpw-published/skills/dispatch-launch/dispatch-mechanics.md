# Dispatch mechanics — worktree, brief, and the three launch paths

Step 4 of [SKILL.md](SKILL.md), in full. Evidence, the complete field surface, and
parity gaps: [reference.md](reference.md).

## 1. Resolve host and agent at dispatch time

```bash
LAUNCH=<this-skill-dir>/scripts
source "$LAUNCH/omni-api.sh"; BASE=$API_BASE   # the configured server, with auth
# Auth on every call (a Databricks App needs the bearer + slice key; localhost needs none):
curl() { command curl ${AUTH_HEADERS[@]+"${AUTH_HEADERS[@]}"} "$@"; }
curl -s "$BASE/v1/hosts"  | python3 -c 'import json,sys; [print(h["id"], h.get("status")) for h in json.load(sys.stdin)["data"]]'
curl -s "$BASE/v1/agents" | python3 -c 'import json,sys; [print(a["id"], a.get("name"), a.get("harness")) for a in json.load(sys.stdin)["data"]]'
```

- **`host_id`** must be an **online** host. `git` and `workspace` are both rejected
  without it (422).
- **`agent_id`** is normally the builtin whose harness is `claude-native` (the UI
  harness). **Never hardcode either id** — they change when a builtin's version bumps.
- Inside an omnigent turn the same two lists come from `sys_agent_list`.

Use an agent returned by the live registry. Existing agents launch by `agent_id`; only use `config_path` when the user supplied a local agent configuration to upload. Never assume a source checkout contains house-specific bundles or that an agent registered on one server exists on another.

## 2. Create the worktree (plain git — no workspace API)

```bash
MAIN=<main-checkout>
WT=<worktrees-root>/worker-<issue>-<slug>
cd "$MAIN" && make base-worktree PATH_="$WT" BRANCH=fix/<slug>       # feat/ for features
```

> **Base = the fetched upstream default branch (#1164).** Never a local ref,
> never the fork's default when the repo has a parent. Resolve it with
> `plugins/rpw-published/scripts/git-base-branch.sh` (`make base-ref`) — it
> detects the fork, picks the parent's remote, resolves that remote's default
> branch dynamically, and fetches before handing the ref back. It exits 3 with
> the exact `git remote add upstream …` command when a fork has no parent
> remote; do not work around that by using `origin`.

Do **not** hand-write the `git fetch` + `git worktree add` pair against a literal
base like the integration branch's name: it bakes in a base-branch name and silently
branches off the fork when the real base is the parent repo. Unlike the retired Superset path, **nothing rewrites the branch name** — no host-side prefix, so the branch you pass is the branch
that exists. A colliding `-b` name fails loudly instead of silently reusing the
branch; add a unique suffix.

## 3. Provision gitignored env files (#496)

**Gitignored env files do not travel with branches.** A fresh worktree starts with
none, so the first command that needs one dies at the door —
`FileNotFoundError: missing dev.env; copy template.env first` killed a baseline run
whose `libs/rpw_evals/dev.env` existed only in another worktree. Copy from a checkout
that has them, **after `worktree add`, before launching**:

```bash
SRC=<main-checkout>          # a checkout that actually has them
DST="$WT"
git -C "$SRC" ls-files --others --ignored --exclude-standard \
  | grep -E '(^|/)[^/]*\.env$' \
  | while read -r f; do
      mkdir -p "$DST/$(dirname "$f")" && cp "$SRC/$f" "$DST/$f" && echo "env: $f"
    done
```

`--others` lists only untracked files, so tracked `template.env` files are untouched.
Say in the brief that env files were provisioned this way — then a `missing …env`
failure reads as "the copy was missed", not "the repo is broken", and the agent never
invents credentials or commits an env file.

## 4. Write the brief as a FILE

Never a long prompt: long prompts spawn-die (evidence in [reference.md](reference.md)),
and a brief on disk survives every relaunch. Write it into the worktree root:

```bash
cat > "$WT/WORKER-BRIEF.md" <<'BRIEF'
<the brief — see the shape below>
BRIEF
```

### Brief shape

```markdown
# Worker Brief — #<issue>: <one-line goal>

## Task
Read the full issue: `gh issue view <issue>`. Work ALL of it.
<context the agent must not re-derive: what is already known, what is out of scope>

## Environment
Your worktree is `<abs-worktree-path>` (branch `<branch>`, cut from `<base-ref>` — the
fetched upstream default, per `make base-ref`).
Gitignored env files were copied in from `<main-checkout>` (#496). A missing one means
the copy was missed — re-run it; never invent credentials, never commit an env file.

## House rules
- Gate: `make verify` from the repo root must pass before commit.
- Claim: the pre-claim was stamped with branch `<branch>` — a `claimed-by-other`
  naming exactly that branch is YOUR claim; any other branch means stop and report.
- Never hand-edit any `plugin.json` version (#210 automation owns it).
- Long runs stay in the FOREGROUND and are polled to completion. Backgrounding one
  and ending your turn kills it — nothing re-invokes you (#495).

## Delivery
<Gate: "Open a PR closing #<issue> against `production`, then STOP."
 | Autonomous: "Open a PR closing #<issue> against `production` and squash-merge it.">

## HARD BOUNDARY
Public publishing is NEVER in scope. No `make publish-promote`, no PRs to
`published/<target>`, and no public-target delivery PRs.
```

### The Step 0 relocation block — path B only

On **path B** (`sys_session_create`) there is no `workspace` field, so the child
inherits the *parent* session's cwd and the shell resets to it after every Bash call.
That brief needs this block prepended, and it is what `wave-kickoff` carries (#795):

```markdown
## Step 0 — Relocation (MANDATORY)
Your worktree is `<abs-worktree-path>`.
You may NOT start in it, and the shell cwd resets after every command. Therefore:
- EVERY command carries its own `cd <abs-worktree-path> &&` prefix.
- EVERY file operation uses absolute paths.
- First command: `cd <abs-worktree-path> && git rev-parse --show-toplevel && git branch --show-current`
  — must print the worktree path and `<branch>`. If not, STOP and report.
```

**Paths A and C do not need it** — measured 2026-08-14 on a bind-mode session: cwd
starts at the bound `workspace`, persists across separate Bash calls, resolves
relative reads and bare `git`, and a stray `cd` is auto-reset before the next call
(probe table in [reference.md](reference.md)). Adding the block anyway costs only
noise; omitting it on path B costs commits on someone else's branch.

## 5a. Launch — path A: `POST /v1/sessions` + wake (default)

```bash
LAUNCH=<this-skill-dir>/scripts
source "$LAUNCH/omni-api.sh"; BASE=$API_BASE   # the configured server, with auth
curl() { command curl ${AUTH_HEADERS[@]+"${AUTH_HEADERS[@]}"} "$@"; }   # auth on every call
cat > /tmp/omni-create.json <<JSON
{
  "agent_id": "<agent id from GET /v1/agents>",
  "host_id":  "<online host id from GET /v1/hosts>",
  "workspace": "$WT",
  "title": "⏳ <repo>::<branch>::<YYYY-MM-DD>::<role> — #<issue> <work-summary>",
  "git": {"branch_name": "<branch>", "existing_worktree": true},
  "terminal_launch_args": ["--permission-mode", "acceptEdits"],
  "model_override": "<optional>",
  "reasoning_effort": "<optional>"
}
JSON
curl -s -X POST "$BASE/v1/sessions" -H 'Content-Type: application/json' \
  --data @/tmp/omni-create.json | python3 -m json.tool
```

Capture `id` — that is the `conversation_id` every later call keys off. Then **wake
it** ([liveness-and-surfacing.md](liveness-and-surfacing.md)); create alone runs
nothing.

| Field | Why it matters |
|---|---|
| `workspace` | **absolute** path, must exist, must fall inside the agent's `os_env.cwd` boundary. Tilde and relative paths are rejected. |
| `git.existing_worktree: true` | **bind** to the step-2 worktree. `false` makes the server create one (`base_branch` names the fork point) — use bind mode whenever a brief file must be pre-staged. |
| `host_id` | required whenever `git` or `workspace` is set (422 otherwise). |
| `terminal_launch_args` | harness flags. `["--permission-mode","acceptEdits"]` is what keeps an unattended agent from permission-wedging (#972). |
| `model_override` / `reasoning_effort` | per-launch, no config duplication — the Superset CLI had no equivalent. |
| `title` | set it **here**, and keep it **under 200 characters** — creation *rejects* a longer one with `HTTP 422 string_too_long` (a refused dispatch, **not** a silent truncation; measured 2026-09-14 at 205 chars, fine at 164), while the rename path caps at 60. Use `⏳ <repo>::<branch>::<date>::<state> — <work-summary>`, with the issue title or first substantive request reduced to one short line. **The ⏳ prefix is not decoration** — it is the in-progress state, flipped to ✅/❌/🛑 at close-out ([session-lifecycle.md](session-lifecycle.md)). Both the prefix and the structured body are defined once, in the session-title convention (`docs/process/agent-session-titles.md`). |

## 5b. Launch — path B: inside an omnigent turn (`sys_session_create`)

```
sys_session_create(
  agent_id = <the claude-native builtin from sys_agent_list>,
  title    = "⏳ <repo>::<branch>::<YYYY-MM-DD>::<role> — #<issue> <work-summary>",
  model    = <pinned model>,            # optional; omit for the agent default
  message  = "#<issue> <work-summary>. cd <worktree> first — that is your worktree,
              not the directory you start in. Then read WORKER-BRIEF.md in that
              worktree's root and execute it exactly.")
```

A strict subset of path A: **no `workspace`, no `git`, no `terminal_launch_args`** —
which is exactly why the Step 0 block exists (#795). Use it when you are already in a
turn and the parent's cwd is acceptable, or when reaching the REST port is awkward.

## 5c. Launch — path C: from a plain shell (`omni` under tmux)

```bash
tmux new-session -d -s worker-<issue> -c "$WT" \
  omni claude --use-native-config --dangerously-skip-permissions \
  -p "#<issue> <work-summary>. Read WORKER-BRIEF.md in your current working directory and execute it exactly. Work autonomously to completion."
```

| Piece | Why |
|---|---|
| `tmux new-session -d` | detaches the agent from your shell, so it survives your session ending. **The only cwd control on this path** |
| `-c "$WT"` | `omni` has no `--cwd`; the session's workspace is the process cwd |
| `-s worker-<issue>` | issue-keyed, so `tmux capture-pane -pt worker-<issue>` is a local liveness view |
| `--use-native-config` | authenticate via the host's own `~/.claude/` settings instead of the configured provider |
| `--dangerously-skip-permissions` | an unattended agent that stops to ask permission wedges invisibly (#972) |
| `-p "<summary>. <pointer>"` | the initial prompt. Start with the short work summary, then point at the brief; keep it one line |

**No `--title` exists on this path.** The server auto-derives the title from the
prompt's first ~60 chars, so putting the work summary first gives a useful
human-readable title without a second request — but it gets **no ⏳ prefix**, so the
session is invisible in a rail scanned by state. Both the prefix and a structured body
need a `PATCH /v1/sessions/{id}` afterwards (`sys_session_rename` refuses auto-titled
sessions), so send that PATCH immediately after launch:

```bash
curl -s -X PATCH "$BASE/v1/sessions/$SID" -H 'Content-Type: application/json' \
  -d '{"title": "⏳ <repo>::<branch>::<YYYY-MM-DD>::<role> — #<issue> <work-summary>"}'
```

That extra round-trip is the reason path A is the default. Other harnesses swap the
subcommand (`omni codex`, `omni pi`, …); `omni --help` lists them.

## 6. Pin the model deliberately

Paths A and B take the model per launch (`model_override` / `model`) — pin it;
dispatch work is multi-file. Path C inherits the harness's own default
(`omni claude --use-native-config` uses your Claude Code config), so control the model
there through that config, not through a flag.
