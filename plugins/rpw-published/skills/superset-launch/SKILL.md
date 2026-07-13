---
name: superset-launch
description: Use to file a GitHub issue and kick off a fresh Superset workspace with a Claude agent, dispatch an existing issue as the next task, or manage workspaces locally — rename, delete/clean up, or self-terminate a finished one. Trigger on "file a github issue and kickoff a workspace", "spin up a superset workspace to fix X", "dispatch the next task", "delegate this to a fresh agent", "rename this workspace", "delete this workspace", "clean up my workspace", or "kill this workspace when done".
---

# Superset Launch Skill

Turn a piece of work into a GitHub issue plus a fresh isolated Superset workspace with a Claude agent already running on it, driving the `superset` and `gh` CLIs. Grounded against `superset` v1.14.3 (2026-07-12; the superset.sh agent-workspace orchestrator, NOT Apache Superset). Deep detail, commands, and evidence: [reference.md](reference.md).

## When to invoke

See the frontmatter triggers. Rename / delete / clean-up → [Managing live workspaces](#managing-live-workspaces-rename-delete-cleanup). Already have an issue number → [Next-task fast path](#next-task-fast-path-dispatch-an-existing-issue). Skip this skill when the user just wants an issue (use `gh`) or the fix is quick enough to do inline.

**Scope boundary:** *single* dispatches (one issue, or a small handful fired sequentially) plus workspace lifecycle. A **multi-issue wave** (parallel cohort, shared wave branch, liveness monitoring, serialized merges) is the **wave-supervisor** skill — don't reimplement that loop; it composes over these steps.

Full pipeline below; the [Next-task fast path](#next-task-fast-path-dispatch-an-existing-issue) collapses Steps 2–3 for an existing issue.

## Step 1 — Auth

`superset auth whoami`. On `Not logged in`, ask the user to run `! superset auth login` (OAuth device code; re-run switches orgs) and wait — don't log in for them. CI/headless uses `--api-key` / `$SUPERSET_API_KEY` ([reference.md](reference.md)).

## Step 2 — Scope + delivery mode

Defaults: repo = the current project's repo (`gh repo view --json nameWithOwner`); title prefixed with the component; `priority: P2`; `type: bug|feature|task` + `plugin: <name>` labels. Decide **delivery mode** now (Gate vs Autonomous) — it shapes the Step 6 prompt.

## Step 3 — File the issue

Body must let the agent work with no back-channel context: **Scope**, **Target file(s)** (paths + lines), **Recommended approach**, **Acceptance** (tests / observable behavior), **Related** (`#N`). `gh issue create` with a HEREDOC `--body`; capture the issue number from the returned URL.

## Step 4 — Project ID & Step 5 — Host

Project ID from `superset projects list --json` (match by slug); if absent, adopt it with `superset projects setup <id> --local --path <repo-path>` (`--parent-dir` to clone) or pick another target. Host: `superset hosts list`; use `--local` unless the user wants a remote host.

## Step 6 — Create the workspace

```bash
superset workspaces create --local --project <id> \
  --name "fix-<slug>" --branch "fix/<name>" --base-branch <default> \
  --agent <host-agent-config-uuid> --prompt "<prompt>" --json
```

Branch: `fix/` for bugs, `feat/` for features. Base: confirm (`production`/`main`). Other flags (`--pr`, `--command`, `--attachment`) + full response shape: [reference.md](reference.md). The **prompt** (agent's initial input) is one block:

```
Implement <goal> — see <issue URL> for full context.
Target: <path>:<line>. <approach copied from the issue>.
Add the test coverage in the issue (<test path>) before shipping. <live check>.
<DELIVERY line — Gate: "open a PR closing #N, then STOP." | Autonomous: "…and squash-merge it.">
```

Capture from the JSON: `workspace.id`; `workspace.branch` — the **real** branch (the host can prefix it, `fix/x` → `superset/fix/x`; never assume `--branch` verbatim); `agents[0].sessionId` — the **terminal id** for Step 7. `Error: Target host required` ⇒ you forgot `--local`.

## Step 6.5 — Verify the agent is running (MANDATORY GATE)

`ok:true` only means *requested*. Two hidden failures — **spawn-death** (terminal dies on launch) and the **visibility illusion** (runs headlessly, unsurfaced). Confirm the process is **alive** (`ps ... | grep "[c]laude"`) AND either **advancing** (`.rpw/build/state.json` / new commits) or burning **real CPU** (`ps -o time,%cpu -p <pid>` — blocked-on-PTY shows ~0). Otherwise delete and respawn; twice-dead ⇒ surface `host-service.log`. Exact commands: [reference.md](reference.md).

## Step 7 — Open with the agent terminal focused (SOLVED)

Not bare `superset workspaces open <id>` — send the focus deep link, which also **registers** the pane (CLI-spawned sessions aren't pane-registered — #5103 — so a plain open leaves the agent *invisible*):

```bash
open "superset://v2-workspace/<workspace.id>?terminalId=<agents[0].sessionId>&focusRequestId=$(uuidgen)"
```

`focusRequestId` must be fresh each call; use `chatSessionId=<id>` for a `superset`-runtime chat session. First open of a new workspace works first try. The stale-cache caveat, its bounce-and-retry fix, and evidence: [reference.md](reference.md).

## Step 8 — Report back

Issue #+URL, workspace id/name/**real branch**, **delivery mode**, Step 6.5 liveness (not just "spawned"), claim state, and the `workspaces delete <id> --local` cleanup command.

## Next-task fast path (dispatch an existing issue)

Work that's **already an issue** skips the authoring ceremony — Steps 2–3 collapse; goal/approach/test come from the issue body (`gh issue view $ISSUE`). **Reuse the previous dispatch's choices as defaults:** a prior run this session already fixed project ID, host, delivery mode, agent-config UUID, and base branch — carry them forward silently, re-confirming only what you're changing. Then run Step 6's `create` and Steps 6.5 / 7 / 8 as normal (**never skip the 6.5 gate**). Claim before each `create`:

```bash
make build-honor-check ISSUE=$ISSUE   # MANDATORY — already claimed elsewhere?
make build-claim ISSUE=$ISSUE         # pre-claim: close the spawn→build-init window
```

**Dispatch the next N from the backlog** (`gh issue list --label "priority: P1" -L <N>`): run the honor-check **live, right before each `create` — not once up front**. Orientation is stale by definition (`gh issue list` can't see sibling worktrees whose work hasn't pushed, and a batch takes minutes to walk), so **skip** any issue that comes back freshly claimed rather than double-picking — the [Claiming](#claiming-avoid-double-picking) lesson, per-item. Keep N small and sequential; a parallel wave belongs to the **wave-supervisor** skill.

## Managing live workspaces (rename, delete, cleanup)

The **current workspace** is `$SUPERSET_WORKSPACE_ID` — injected into every agent terminal with `$SUPERSET_WORKSPACE_PATH`, `$SUPERSET_ROOT_PATH` (the project's main clone, safe to `cd` to), and `$SUPERSET_TERMINAL_ID` (this pane, for self-focus links). `superset workspaces get [-f <field>]` reads it.

**Rename the current workspace** — cloud-backed (no `--local`, needs the org reachable): `superset workspaces update "$SUPERSET_WORKSPACE_ID" --name "<good name>"`.

**Delete workspaces** (spawned children, finished ones) — safe any time; variadic:

```bash
superset workspaces delete <id> [<id2> ...] --local
git -C "$SUPERSET_ROOT_PATH" branch -D "<branch>"   # delete leaves the branch behind — prune it (real prefixed name)
```

**Delete the current workspace** — TERMINAL: it removes this session's worktree *synchronously*, so the CWD is gone the moment it returns. For an agent ending its own finished workspace, use the recipe next.

### Agent self-termination (an agent ending its own finished workspace)

Final step for an agent inside a workspace whose PR has landed — "kill this workspace when done". Two gotchas drive the order: **self-delete kills the terminal mid-command** (nothing after it runs) and **`delete` leaves the branch behind**.

1. **Confirm the PR merged** (`gh pr view <n> --json state -q .state` ⇒ `MERGED`) — in Gate mode a human merges; anything else ⇒ STOP, leave the workspace alive.
2. **Send your final report FIRST** — the delete destroys this terminal, so nothing after it is recoverable.
3. **Prune the branch** — `delete` won't (squash-merge `--delete-branch` removes only the remote): `git -C "$SUPERSET_ROOT_PATH" branch -D "<real prefixed branch>" 2>/dev/null || true`.
4. **Delete so the report survives** — never call `superset workspaces delete "$SUPERSET_WORKSPACE_ID" --local` inline; hand off or detach:
   - **Preferred:** an orchestrator/host in another workspace runs that delete — your terminal never dies mid-command.
   - **Detached** (no orchestrator): background it *outside* the worktree, then exit — the reap outlives the pane: `( cd "$SUPERSET_ROOT_PATH" && superset workspaces delete "$SUPERSET_WORKSPACE_ID" --local ) & disown`
   - **Last resort, synchronous:** `cd "$SUPERSET_ROOT_PATH"` (CWD must leave the worktree), then that delete as the literal last line.

(`delete` on a gone id is a no-op, `branch -D … || true` swallows "not found" — hence re-run safe.) Reaping a whole cohort is the wave-supervisor's job.

`update`/`list` are cloud-backed (need network); `create`/`delete --local` hit the local daemon (`list` filters: `--local`, `--project`, `-s <substring>`).

## Delivery mode (gate vs autonomous)

A spawned headless `/build` runs to completion with no human, so the prompt is the **only** merge gate — it self-certifies its own validation receipt and (no branch protection) auto-merges unattended ([reference.md](reference.md) for the mechanism). **Gate (default):** prompt ends "open a PR, then STOP" — a human merges. **Autonomous:** prompt ends "open a PR and merge" — lands unattended. Default to Gate; state the mode in Step 8.

## Claiming (avoid double-picking)

The spawned agent's `make build-init` **auto-claims** once `/build` reaches planning (`status: in-progress` label + comment). Pre-claim with `make build-claim ISSUE=<N>` to close the spawn→init window (label is `status: in-progress`, NOT bare `in-progress`). Before spawning, confirm no existing claim and no sibling worktree references it — local work is invisible to `gh issue list` until pushed.

## Agent configs (what `--agent` accepts)

`--agent` resolves a HostAgentConfig **instance UUID first, then a preset id** (`superset agents list --local --json`) — no fallbacks, so **`--agent claude` fails here**. For headless `/build`, the config's args should carry `--permission-mode acceptEdits` before the `/build` positional. There's **no `--model` flag** — model is baked into the config. Live config UUID table, model-cloning recipe, and `agents/terminals create` one-liners: [reference.md](reference.md).

## Failure modes

- **Spawn-death / visibility illusion** — Step 6.5 catches both; respawn the first, Step 7 link surfaces the second.
- **`--agent claude` NOT_FOUND** — use a config UUID from `agents list --local --json`.
- **Silent auto-merge** — under-specified prompt ⇒ unattended merge; pick delivery mode deliberately.
- **Branch already exists** — `--base-branch` only forks when absent; use a unique suffix.
- **`--agent` without `--prompt`** (rejected), or **auth expired** (re-check `superset auth whoami`).
