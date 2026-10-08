# Dispatch failure modes

Companion to [SKILL.md](SKILL.md) (#592 pattern; extracted in #1605 to restore the
skill's word-cap headroom). Every entry below is a way a dispatch has actually gone
wrong — read it when a dispatch misbehaves, and skim it before your first launch of
the day. The two that are *decisions* rather than diagnoses stay in SKILL.md.

- **Created but never woken** (path A) — the single most likely way to get a
  permanently idle session. Both calls, always.
- **Trusting `status`** — `idle` is what both a finished turn and a never-started
  session report. Step 5 catches it; relaunch in place (the brief file survives), and
  **twice-dead ⇒ stop looping** and report.
- **Long launch message** — spawn-dies; the brief-file pattern is not optional.
- **Wrong worktree** — a path-B child ran in the parent's cwd because the brief lacked
  the Step 0 relocation block. Symptom: commits on someone else's branch.
- **Wedged on an invisible question (#972)** — the session stopped to ask permission and
  nothing renders it. Signature: `pending_elicitations` **non-empty** plus a history
  frozen on a `tool_use` with no `tool_result`. Note `acceptEdits` does **not** cover
  `mcp__omnigent__sys_*`, so an edits-only pre-grant still wedges on the first MCP call —
  unattended supervisors launch `bypassPermissions`. When you could not pre-grant, the
  cure is `POST /v1/sessions/{id}/elicitations/{elicitation_id}/resolve` with
  `{"action":"accept","content":{"remember":true}}`, one per distinct tool name:
  [liveness-and-surfacing.md](liveness-and-surfacing.md).
- **Wedged with `pending_elicitations: []` — the managed-policy stall (#1777)** — the
  worst one, because every permission flag *looks* honored. Signature, all four together:
  a **pane-only prompt** (nothing in the API surface) · **`pending_elicitations: []`**, so
  #1761's `/elicitations/{id}/resolve` route never fires · **`status: running`** with a
  frozen history whose **last item is a `tool_use` with no `tool_result`** · then
  `runner_disconnected` after the 3600s idle timeout. Cause: an enterprise
  managed-settings policy, evaluated before any flag, which makes
  `--permission-mode bypassPermissions`, `acceptEdits` and `--allowedTools` **silent
  no-ops** — the runner **must** launch through `claude-home-unattended` instead. Cost
  when unchecked: wave 2026-09-13 lost its supervisor and all five cohort-1 workers at
  their first `Edit`. Full anatomy and the preflight:
  [liveness-and-surfacing.md](liveness-and-surfacing.md).
- **Reported done, nothing landed (#971)** — never accept a completion claim without a
  PR URL, commit SHA, or green gate.
- **`422` on create** — `git` and `workspace` both require `host_id`; `workspace` must
  be absolute, exist, and sit inside the agent's own cwd boundary; `title` must be under
  200 characters (`string_too_long` **rejects** the dispatch, it does not truncate it).
- **Branch already exists** — pick a unique suffix; `worktree add -b` refuses a
  collision rather than silently reusing it.
- **No online host** — dispatch nothing until `status: online` (see SKILL.md Step 1).
