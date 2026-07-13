# superset-launch reference (CLI v1.14.3, verified 2026-07-12)

Deep detail backing SKILL.md. This is the Superset agent-workspace orchestrator ([superset.sh](https://superset.sh), GitHub `superset-sh/superset`) — NOT Apache Superset.

## Full `workspaces create` flag surface

`--host <machineId>` | `--local`; `--project <id>`; `--name <string>`; `--branch <string>` (required unless `--pr <number>`, which checks out the verified PR head instead); `--base-branch <string>` (fork point when the branch is absent; defaults to project default); `--agent <preset-id | HostAgentConfig-UUID | superset>`; `--prompt <string>` (required with `--agent`; attachments alone also satisfy the server); `--command "<shell cmd>"` (extra terminal running a command after creation); `--attachment <path>` (repeatable upload the prompt can reference). Omitting `--name`/`--branch` with an agent prompt makes the server AI-generate both.

Full create response shape:

```json
{
  "workspace": { "id": "…", "branch": "superset/fix/<name>", "type": "worktree", "…": "…" },
  "terminals": [ { "terminalId": "…", "label": "…" } ],
  "agents":    [ { "ok": true, "kind": "terminal", "sessionId": "<terminal-id>", "label": "…" } ],
  "alreadyExists": false,
  "txid": 0
}
```

`agents[].kind` is `"chat"` with a `sessionId` usable as `chatSessionId` when `--agent superset`. `terminals[]` carries setup-preset / `--command` terminals.

**Branch prefix:** the host's Git settings (host DB `host_settings`, per-project overridable) can prefix every workspace branch — on this host mode=`custom`, value=`superset`, so `--branch fix/x` → `superset/fix/x`. Worktree path: `~/.superset/worktrees/<project-id>/<branch-with-prefix>`.

## Terminal focus deep link — mechanism + evidence

The v2 workspace route validates three search params: `terminalId`, `chatSessionId`, `focusRequestId` (renderer route `/v2-workspace/$workspaceId/`, hook `useConsumeAutomationRunLink` → `focusOrAddTerminalPane`). The main process additionally restores/shows/focuses the app window on every deep link. Officially documented as "Session Deep Linking" in the [CLI reference](https://docs.superset.sh/cli/cli-reference).

Verified 2026-07-12 on v1.14.3 by experiment (throwaway workspaces, since deleted):

1. Fresh workspace, never opened, agent spawned via `workspaces create --agent` → focus link opened → pane layout (renderer localStorage) gained a tab whose `activePaneId` pane holds exactly that `terminalId`, and the session's `last_attached_at` was set in `~/.superset/host/<org>/host.db` `terminal_sessions` — pane mounted, shown, focused. Works first try.
2. Workspace page already open with a session list cached from before the agent spawned → link silently ignored (the belongs-to-workspace guard reads the stale cache, then the consume-key memoizes). Navigating to any other workspace first (forcing remount + fresh session query), then sending the focus link with a fresh `focusRequestId`, attached the pane every time.

Why plain `superset workspaces open <id>` is not enough: upstream bug [#5103](https://github.com/superset-sh/superset/issues/5103) — CLI/MCP-created terminal sessions are never registered in the workspace's pane-layout store, so the workspace opens with the agent terminal invisible (it still runs headlessly; it shows in Settings only). The focus link is what *registers* the pane, not merely focuses it.

`$SUPERSET_TERMINAL_ID` (injected into every agent terminal alongside `$SUPERSET_WORKSPACE_ID`, `$SUPERSET_WORKSPACE_PATH`, `$SUPERSET_ROOT_PATH`, `$SUPERSET_AGENT_ID`) is the current pane's terminal id — usable for self-focus links.

## Delivery mode — why the prompt is the only gate

A spawned headless `/build` runs to completion with no human in the loop. It **self-certifies** the Phase 3d human-validation receipt, and with no branch protection on the repo it **auto-merges** at Phase 5d.5 — observed live: #188 → the agent merged its own PR #192. So the prompt's closing instruction ("open a PR, then STOP" vs "open a PR and merge") is the only thing standing between a spawn and an unattended merge. Default to Gate; state the mode in the Step 8 report.

## Step 6.5 liveness check — commands + evidence

`ok:true` from `create` only means *requested*. Two hidden failures: **spawn-death** (`~/.superset/host/<org>/host-service.log`: "PTY process exited immediately") and the **visibility illusion** (running, just not surfaced — Step 7 focus link is the fix).

```bash
ps aux | grep "[c]laude" | grep -- "/build" | grep "<branch-slug>"     # alive? (match your config's command)
WT=~/.superset/worktrees/<project-id>/<branch>
cat "$WT/.rpw/build/state.json"; git -C "$WT" log --oneline -3          # advancing?
```

Alive AND (advancing OR real CPU via `ps -o time,%cpu -p <pid>` — blocked-on-PTY shows ~0) ⇒ healthy. Otherwise delete and respawn; twice-dead ⇒ surface `host-service.log` instead of looping.

## Agent configs (what `--agent` accepts)

`--agent` resolves a HostAgentConfig **instance UUID first, then a preset id**, against the configs actually on the host (`superset agents list --local --json`). No built-in fallbacks — **`--agent claude` fails unless a config carries that presetId**. Configs are host-specific: always pull the real UUIDs from `superset agents list --local --json` at dispatch time. Illustrative shape (fake UUIDs):

| id | label | runs |
|---|---|---|
| `00000000-0000-4000-8000-000000000001` | Claude Automation Agent | `claude --model sonnet -p <prompt>` |
| `00000000-0000-4000-8000-000000000002` | Cursor Agent | `cursor-agent <prompt>` |
| `superset` | Superset | built-in chat runtime (returns `chatSessionId`) |

All use `argv` transport (prompt appended last); configs live in **Settings → Agents**. For headless `/build` reliability a config's args should carry `--permission-mode acceptEdits` before the `/build` positional; prefer that over `--dangerously-skip-permissions`. There is **no `--model` flag** on `workspaces create` / `agents create` — the model is baked into the config's args (see next section for running a non-default model).

`superset agents create --workspace <id> --agent <cfg> --prompt "…"` adds an agent to an existing workspace, returning `{kind, sessionId, label}` for the Step 7 link; `superset terminals create --workspace <id> [--command] [--cwd]` opens a plain terminal the same way.

## Per-launch model/effort: host API vs CLI

The host tRPC `agents.run` / `workspaces.create` accept optional `model` and `effort` per launch, and the desktop app's workspace dialog exposes them (July 2026 "Fable 5 & Reasoning Effort" changelog entry). But:

- The **CLI does not expose them** — no `--model`/`--effort` on `workspaces create` or `agents create` (confirmed against `--help`, v1.14.3).
- Even via the API, model args are only applied for **stock preset ids** with a support entry (`claude`: `fable`/`opus`/`sonnet`/`haiku` via `--model`; also `codex`, `gemini`, `copilot`, `cursor-agent`, `opencode`). `custom` configs get no model injection — the model is whatever the config's own args say.

So from the CLI the only model control is the HostAgentConfig's args. To run a fable agent: Settings → Agents → duplicate an existing claude config (e.g. one running `claude --model sonnet -p`), change `--model sonnet` to `--model <fable-model-id>`, save, and pass the new config's UUID to `--agent`.

Agent config resolution order (host source): exact HostAgentConfig `id` match first, then first config whose `presetId` matches, by display order. No built-in fallbacks — `--agent claude` errors with `No host agent config matching 'claude'` unless a config row has that presetId (none does on this host as of 2026-07-12).

## Wider CLI surface (context)

- `superset tasks …` — org task tracker (list/get/create/update/delete/statuses; `workspaces update --task-id <id>` links a workspace to one).
- `superset automations …` — scheduled agent runs (create with RFC 5545 `--rrule`, pause/resume/run/logs, `prompt get|set`).
- `superset organization list|switch|members`, `superset hosts list|wake|set-wake`.
- `superset start|stop|status` — host daemon lifecycle; `superset update` — self-update.
- `superset projects create --clone <url> --parent-dir <dir>` | `--import <path>`; `projects setup <id> --path|--import|--parent-dir [--allow-relocate]`.
- `superset workspaces get [id] [-f <field>]` — single workspace (defaults to `$SUPERSET_WORKSPACE_ID`); `-f worktreePath` prints one raw field.
- Global flags: `--json` (auto-on under CI/agent envs like `CLAUDE_CODE`), `--quiet` (IDs only), `--api-key sk_live_…` / `$SUPERSET_API_KEY`.
- Auth is OAuth device code + PKCE (works headless); `auth login` re-run switches orgs.

Sources: [docs.superset.sh CLI reference](https://docs.superset.sh/cli/cli-reference), [superset.sh/changelog](https://superset.sh/changelog), [superset-sh/superset#5103](https://github.com/superset-sh/superset/issues/5103), plus direct `--help` introspection and host-source/DB inspection on this machine.
