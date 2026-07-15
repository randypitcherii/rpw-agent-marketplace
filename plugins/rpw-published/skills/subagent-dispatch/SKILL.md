---
name: subagent-dispatch
description: Naming conventions, dispatch templates, and guardrails for spawning subagents — both Build Workers inside /build and ad-hoc research/debug/minion dispatch outside it. Use when dispatching an Agent, deciding whether a request should fan out to subagents, or picking a subagent model. Trigger on "dispatch a worker/agent", "research X" / "compare X vs Y" (multi-source), "why is X broken?" / "debug this", or a bounded minion task (issue creation, renames, metadata updates).
---

# Subagent Dispatch

Spawn subagents via the Agent tool in two modes: **inside `/build`** (Build Lead coordinates Workers, Guards, Simplifiers — sections 1–7) and **outside `/build`** (auto-dispatch ad-hoc research/debug/minion tasks — section 8).

> **Runtime (#69):** these roles map to DeepAgents `task`-tool subagents — see [`build-subagents-langgraph.md`](../../../../docs/architecture/build-subagents-langgraph.md). Executable orchestration is a runtime primitive (ADR-2026-05-27); this skill is the human-readable dispatch guidance.

## 0. Agent Tool Schema — Use ONLY These Parameters

The Agent tool accepts exactly: `subagent_type`, `description`, `prompt`, `model` (`sonnet` | `opus` | `haiku` | `fable`), `isolation` (`worktree` | `remote`), `run_in_background`.

There is **no `name:` parameter** and **no `mode:` parameter** — do not pass them. Put the role/ID label (e.g. `bw-{task}`) in `description`; select the role via `subagent_type`. Permission mode is a session setting, not a per-call argument (see section 5).

## 1. Agent Role Reference

`subagent_type` values are prefixed `rpw-published:`. The ID pattern goes in `description`.

| Role | subagent_type | Model | ID | Worktree | Typical Task |
|------|---------------|-------|----|----------|--------------|
| Build Lead | (main agent) | Opus | `build-{feature}` | build | Decompose, coordinate Workers, merge (owns Feature issue) |
| Build Worker | `build-worker` | Opus/Sonnet | `bw-{task}` | task (required) | Implement one Task: tests, code, commit |
| Security Guard | `security-guard` | Opus | `guard-{feature}` | none | Review diff for secrets, vulns, scope |
| Simplifier | `simplifier` | Opus | `simplify-{feature}` | none | Reduce complexity, remove dead code |
| Research Lead | `research-lead` | Opus | `research-{topic}` | none | Plan + synthesize research |
| Research Worker | `research-worker` | Sonnet | `rw-{topic}-{n}` | none | Fetch/read/summarize one source |
| Debug Lead | `debug-lead` | Opus | `debug-{issue}` | none | Diagnose, recommend fixes |
| Minion | `minion` | Haiku | `minion-{action}` | none | Bounded lookups, renames, metadata, issue creation |

## 2. Build Worker Dispatch Template
```
Agent(
  subagent_type: "rpw-published:build-worker",
  description: "bw-{task-slug}",
  model: "sonnet",          // default; "opus" for complex tasks
  isolation: "worktree",
  run_in_background: true,
  prompt: "... (MUST include absolute worktree path — see section 3)"
)
```

## 3. Prompt Template for Build Workers

The Build Lead is the **coordinator** and owns the ledger; the worker gets everything in this prompt.

```
You are a Build Worker implementing task #{issue-number}.

## Task
{task-description}

## File Scope
Modify ONLY these files: {list-of-files-or-directories}

## Working Directory
Your worktree is at: {absolute-worktree-path}
First step: run `git rev-parse --show-toplevel`; if it doesn't match, abort — your worktree is misconfigured.

## Isolation rules (#135 — DO NOT VIOLATE)
- Your isolated worktree is ALREADY set up. The branch you start on is the branch you commit on.
- DO NOT run `git checkout`/`switch`/`branch`. DO NOT `cd` elsewhere (use `git -C <abs-path>` if needed).
- A mentioned "task branch name" is informational only — do not enforce it via `git checkout -b`.
- If `--show-toplevel` equals the build worktree ({absolute-build-worktree-path}), abort: "ABORT: worktree isolation failure."

## Build Context (coordinator-owned ledger — read-only for you)
feature_branch: {feature-branch-name} · feature_worktree: {absolute-build-worktree-path} · current_phase: {phase-name} · issue_id: {feature-issue-number}
You do NOT touch build state files, receipts, or artifacts. Report results in your final message; the Build Lead updates state.

## Acceptance Criteria
{bullet-list-of-acceptance-criteria}

## Requirements
Write tests FIRST (TDD), then implement. Run `make check` (or `make verify` if undefined) before committing; all tests must pass. Commit with: '{type}: {description}'.

## Constraints
- Do not modify files outside your scope/worktree. Do not push (the Build Lead controls merges).
- Do not ask questions — make reasonable assumptions and document them.
- Return a brief result: success/failure, files changed, assumptions made.
```

**Coordinator-owned ledger:** each worker's worktree has its own stale `.rpw/`/`.claude/`, so the Build Lead is the single source of truth. **Escape hatch:** if a worker must emit a receipt, set `RPW_BUILD_COORDINATOR_DIR={absolute-build-worktree-path}` in the dispatch env; scripts honor it first.

## 4. Model Selection

**Sonnet** (default) for standard implementation, file edits, and test writing; **Opus** for architectural decisions, complex refactoring, multi-file coordination, and Lead roles; **Haiku** for Minion tasks only (issue creation, lookups, metadata, renaming).

## 5. Dispatch Guardrails

- Max **5 Build Workers** per Build Lead; max **3 Research Workers** per Research Lead; max **5 Minions** per batch.
- Max **depth 1**: subagents are leaves — they **cannot spawn subagents**. For fan-out, dispatch multiple workers directly from the main conversation and synthesize yourself.
- **NEVER** dispatch workers that modify the same files in parallel. Shared files (`package.json`, lock files, config) go to ONE worker or are sequenced.
- Build Workers: always `run_in_background: true` + `isolation: "worktree"`, and include the absolute worktree path in the prompt. Research and Debug agents are **read-only** — no file edits.

### bypassPermissions Security Deny-List

When the session runs in `bypassPermissions` mode, subagents inherit it and can bypass interactive prompts. To prevent exposure:

- **NEVER** read or write `.env` files, `.env.*`, or any dotenv variants.
- **NEVER** access `~/.aws` credentials, `~/.ssh` keys, or `~/.config` auth tokens.
- **NEVER** commit files matching `.env`, `credentials.json`, `*.pem`, `*.key`.
- Workers must check `git diff --cached` for secret patterns before committing.

## 6. Failure Handling

1. **Assess**: isolated (one task) or systemic (environment, dependency)?
2. **Retry once** with clarifying context if the failure was ambiguous.
3. **Fallback**: mark the task issue blocked and continue with remaining tasks.
4. **Partial merge**: only merge successful worktrees; report incomplete tasks.
5. **Escalate**: if 3+ workers fail in the same cycle, stop and ask the human.

**Post-dispatch isolation assertion** — after each worker finishes/stalls, the Build Lead runs `git -C <build-worktree-abs-path> status --porcelain` and `rev-parse --abbrev-ref HEAD`. If HEAD is not the feature branch or unexpected files appear, a worker leaked in — STOP merging and warn (#135). Never `cd && git status` — parallel Bash calls share cwd.

## 7. Merge Protocol & Issue Hierarchy

After a Build Worker succeeds, merge with a **regular (non-squash) merge** — `--squash` breaks `git branch -d`. Run `make verify` after each merge. On failure, do NOT merge; clean up.
```bash
git merge --no-ff <task-branch>
make build-worker-cleanup WORKTREE=<path> BRANCH=<branch>   # canonical cleanup
# manual fallback: git worktree remove -f -f <path>; git branch -D <branch>; git worktree prune
```

**Issue Hierarchy (Build Lead owns it):** the build request issue is the Feature parent (`gh issue create --label feature` if none exists). Each work unit is a checklist item or linked task issue; epics use GitHub milestones/labels. Workers get their task + issue number and implement exactly one task; they do NOT manage issues. The Build Lead closes task issues after merge.

## 8. Auto-Dispatch Outside `/build`

When NOT in a `/build` session, auto-dispatch qualifying requests to keep context clean and fan out for thoroughness. **This section does NOT apply during `/build`** — that lifecycle uses sections 1–7.

**Inline-first threshold (check FIRST):** if you can answer with ≤3 tool calls using context you have — a file read, one `grep`/`glob`, a quick git command, a factual lookup — handle it inline. Dispatch only for 4+ sources/searches, parallel investigation, or fan-out. When uncertain, bias inline.

Every dispatch prompt includes a **Context** block: the user's goal, files/paths examined, approaches tried/rejected, stated preferences/constraints.

### Minion Tasks (Haiku)
Simple, bounded, low-risk: issue creation, renames/metadata, single-value lookups, boilerplate from a template. NOT for judgment, multi-file coordination, or user-facing decisions.
```
Agent(
  subagent_type: "rpw-published:minion",
  description: "minion-{action}",
  model: "haiku",
  run_in_background: false,     // fast, foreground; no worktree
  prompt: "You are a Minion. Task: {exact-action}. {Context}. Complete this single action, make reasonable assumptions, do not modify files outside scope, return a brief result."
)
```

### Research Tasks (Opus / Sonnet)
"Research X", "Compare X vs Y", "options for X", "how does X work here?" — anything needing 3+ sources. NOT for questions answerable from one read/search.
```
Agent(
  subagent_type: "rpw-published:research-lead",
  description: "research-{topic-slug}",
  model: "opus",
  run_in_background: true,      // read-only, never worktree
  prompt: "You are a Research Lead. Question: {topic}. {Context}. Desired output: {format}. Investigate with parallel tool calls, cite files/URLs, note gaps rather than guess, return early on blocking errors, use the Result Format below."
)
```
For multi-angle research, dispatch up to **3** `research-worker` agents (Sonnet, background) in ONE message and synthesize yourself.

### Debugging Tasks (Opus)
"Why is X broken?", "this test fails", error/stack-trace reports, "debug this". NOT when the user already knows the fix.
```
Agent(
  subagent_type: "rpw-published:debug-lead",
  description: "debug-{issue-slug}",
  model: "opus",
  run_in_background: true,      // diagnose only, NEVER edits files
  prompt: "You are a Debug Lead. Problem: {description + error output}. {Context}. Systematic debugging: reproduce → 2-3 hypotheses → test with parallel tool calls → confirmed root cause → specific fix (file paths). Do NOT edit files. Use the Result Format below."
)
```
The main agent implements the fix after reviewing. If an agent surfaces related work, create a GitHub issue and suggest `/build` for non-trivial items.

### Result Format (Research/Debug Leads; Minions exempt)
```
**Status**: success | partial | failed    **Confidence**: high | medium | low
**Summary**: 2-3 sentence answer/diagnosis.
**Findings**: key findings with source/file references.
**Gaps**: what couldn't be determined and why.
**Follow-up**: next actions; GitHub issues to create.
```
Present by confidence: **high** → summary only; **medium** → + findings + gaps; **low** → full report with caveats. Always tell the user what was dispatched and why.
