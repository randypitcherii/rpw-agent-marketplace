---
name: build
description: Full lifecycle development orchestrator with adaptive execution modes
argument-hint: <request>
---

# /build - Full Lifecycle Development Orchestrator

Execute a full development lifecycle for the requested work item.

Treat everything typed after `/build` as the build request and use it as the primary scope input.

For agent role definitions and naming conventions, see `plugins/rpw-building/AGENTS.md`.

> **AUTONOMOUS EXECUTION — CRITICAL**: Once you begin a build, execute ALL phases (1 → 2 → 3 → 4 → 5) to completion in a single continuous run. **Never pause between phases, never pause after tool calls, never wait for user input.** After every tool call returns (including EnterWorktree, Agent dispatches, and build_state_set), immediately continue to the next action. The only exceptions requiring human input are: (1) destructive git operations, (2) ambiguous requirements with no safe default, (3) 3+ worker failures in one cycle, (4) Phase 3d human validation (the ONE mandatory human checkpoint). Everything else — proceed without stopping.

> **AGENT AUTONOMY — CRITICAL**: The agent does ALL the work. Never ask the user to run commands, start servers, open browsers, or test things manually. Run dev servers yourself, execute tests yourself, verify endpoints yourself. The ONLY time to involve the user is Phase 3d human validation (subjective UX/behavioral feedback that requires human eyes). Everything else — you do it.

> **NEVER ASK "READY?" — CRITICAL**: Never ask confirmation questions at transition points ("Ready to proceed?", "Does this look right?", "Shall I continue?", "Ready for the next section?"). This applies to the build skill AND every sub-skill invoked during the build (brainstorming, writing-plans, executing-plans, TDD, etc.). Flow directly from one phase to the next. The user will interrupt if they have feedback. The only exception is Phase 3d human validation, which explicitly requires human approval.

## Invocation Patterns

- **`/build <request>`**: Start in planning-first mode. Choose Autonomous Fast Path only when safety eligibility passes.
- **`/build without planning: <request>`**: Skip to fast path. Falls back to full planning if safety eligibility fails.
- **`/build`** (no arguments): Auto-select work. See "No Arguments Default" below.

## No Arguments Default

When `/build` is invoked without a request, do NOT ask the user what to build. Instead:

1. **Review ready work**: Run `bd ready` to find issues with no blockers.
2. **Analyze the batch**: Dispatch a subagent to evaluate ready beads for dependencies, synergies, impact, and risk. Consider which beads share code/files/concepts, which unblock other work, and which are safest to batch together.
3. **Present recommendation**: Show the user a prioritized recommendation of 2-3 beads to tackle together, with brief rationale for the grouping and ordering.
4. **Wait for approval**: This is the ONE pause point — wait for the user to confirm the recommended batch or adjust it.
5. **Proceed with build**: Once approved, treat the batch as the build request and continue with Phase 1 planning.

## Autonomous Safety Eligibility Checklist

All must be true for Autonomous Fast Path:

1. Scope is narrow and local (small number of files/systems).
2. Request is unambiguous with concrete acceptance criteria.
3. No destructive operations, secret handling, auth resets, or production-impacting changes.
4. Verification path is clear (`make verify` and/or focused tests).
5. A safe fallback exists if implementation hits uncertainty.

If any item is false, use Full Planning Mode. Both modes execute autonomously — the difference is whether you pause for plan approval.

## Makefile-First Execution

- Run `make list` to discover available commands.
- Use `make verify` for all validation.
- Prefer `make` targets over ad hoc shell commands.

## Branch Naming Convention

All branches created during `/build` MUST follow these patterns:

| Branch Type | Pattern | Example |
|-------------|---------|---------|
| Feature branch (build worktree) | `feat/{short-slug}-{bead-id}` | `feat/auto-dispatch-i4d` |
| Task worktree branch | `feat/{feature-slug}-{feature-bead-id}/task/{task-slug}-{task-bead-id}` | `feat/auto-dispatch-i4d/task/add-tests-a3f` |

**Slug rules:**
- Lowercase, hyphenated, 2–4 words max
- Derived from the request or bead title (not the full description)
- The `{bead-id}` suffix ensures uniqueness and traceability

**Examples:**
- Request "Add auto-dispatch for subagents" with bead `i4d` → `feat/auto-dispatch-i4d`
- Task "Write unit tests for dispatcher" under feature `i4d` with bead `a3f` → `feat/auto-dispatch-i4d/task/add-tests-a3f`

## Worktree Isolation Protocol

All `/build` work MUST execute inside git worktrees. The main conversation working tree stays clean for orchestration only.

**Build Worktree (created in Phase 1):**
1. Detect the default branch (`main` or `production`) from git metadata.
2. Create a feature branch from the default branch named `feat/{short-slug}-{bead-id}` (see Branch Naming Convention above).
3. Enter a **build worktree** on that feature branch via `EnterWorktree`. All planning, bead tracking, and coordination happen here.

**Task Worktrees (created in Phase 2):**
1. Each task bead is dispatched to a Build Worker with `isolation: "worktree"` branching from the build worktree's feature branch. Task branches are named `feat/{feature-slug}-{feature-bead-id}/task/{task-slug}-{task-bead-id}` (nested under the feature branch namespace).
2. Build Workers work exclusively inside their own task worktree.
3. On completion, each Build Worker's changes are **merged** back into the build worktree's feature branch using a regular merge (`git merge --no-ff <task-branch>`). Regular merges (not squash) preserve the commit history so `git branch -d` can cleanly delete the task branch afterward.
4. Task worktrees are cleaned up immediately after their merge completes.

**Finalization (Phase 5):**
1. All verification, commit checks, and validation run inside the build worktree.
2. The build worktree creates a PR from the feature branch to the default branch.
3. On merge approval, the feature branch is merged to the default branch and the build worktree is cleaned up.

**Exceptions:** Only the orchestrator (main conversation) operates outside worktrees. Research-only agents that make no edits may skip worktree isolation.

---

## Phase 1 — Plan

> **GATE**: Phase 1 ends with `build_state_set plan_complete`. Do not proceed to Phase 2 without this.

### Autonomous Fast Path

- Break work into discrete, testable tasks. Map files and tools.
- Create beads hierarchy (if `bd` available):
  1. The existing bead from the build request becomes the **feature bead** (parent). If no bead exists, create one: `bd create --title="<feature>" --type=feature --priority=<P>`
  2. Create **task beads** for each discrete unit of work: `bd create --title="<task>" --type=task --priority=2`
  3. Link tasks to the feature: `bd dep add <task-id> <feature-id> --type=parent-child`
  4. Optionally link the feature to an existing **epic**: `bd dep add <feature-id> <epic-id> --type=parent-child`
  See `docs/beads-hierarchy-standard.md` for the full hierarchy standard.
- Proceed to implementation immediately — do not wait for approval.
- Surface assumptions in delivery notes (Phase 5).

### Full Planning Mode

- Clarify scope, constraints, success criteria. Surface edge cases, risks, non-goals.
- Present plan to user and wait for approval before proceeding.
- Create implementation plan with dependencies.
- Track in Beads if `bd` available:
  1. The build request bead is the **feature bead** (or create one with `--type=feature`).
  2. Each plan step becomes a **task bead** (`--type=task`) linked as a child of the feature.
  3. Task beads are the unit of task worktree isolation — one task = one Build Worker = one worktree.
  See `docs/beads-hierarchy-standard.md` for the full hierarchy standard.
  If `bd` unavailable, use a plain checklist.
- For discovered bugs/debt/future work mid-build: create new beads tagged for follow-up.

### Phase 1 Actions (both modes)

> **DO NOT STOP after any step below. Execute all steps in sequence, then immediately proceed to Phase 2.**

0. **Pre-flight**: Run `git status`. If tree is dirty, summarize and ask whether to proceed, stash, or isolate work. Check for stale worktrees with `git worktree list`.
1. Create feature branch from default branch named `feat/{short-slug}-{bead-id}` (see Branch Naming Convention).
2. Initialize build state: `make build-init BEAD=<bead-id>` (must happen before entering worktree so state file lives in the main working tree, not inside the worktree)
3. Enter the **build worktree** on this branch via `EnterWorktree` (see Worktree Isolation Protocol). **When EnterWorktree returns, immediately continue to step 4 — do not pause or wait for user input.**
4. Mark phase complete: `make build-checkpoint CP=plan_complete`
5. **MANDATORY**: Proceed immediately to Phase 2. All 5 phases are required — the build-completion-gate hook blocks session end without evidence from every phase. Do not summarize, do not ask for confirmation.

---

## Phase 2 — Implement

> **GATE**: Phase 2 ends when all task worktrees are merged (regular merge) back to the feature branch. Do not skip to Phase 5.

- **REQUIRED**: All Build Workers MUST use `isolation: "worktree"`. Research-only agents that make no file changes may skip isolation.
- Use the `subagent-dispatch` skill to dispatch task beads as Build Workers (`bw-{task-slug}`) with `isolation: "worktree"` and `run_in_background: true`.
- **Red-green TDD is mandatory**: Every bug fix and feature MUST follow red-green TDD — write a failing test FIRST, then implement the minimal code to make it pass. Never declare a fix working without a test that proves it. Full-path verification is required: test what users actually hit (the complete request flow), not just the isolated new code. If the user flow involves proxies, routers, or multiple hops, the test must exercise the full path.
- Model selection: Build Workers default to Sonnet (`model: "sonnet"`). Use `model: "opus"` for complex/architectural tasks requiring deep reasoning.
- Subagents are leaves (max depth = 1) — Build Workers cannot spawn Research Leads or Minions. The Agent tool is not available to subagents. For parallel fan-out, dispatch all workers directly from the main conversation (depth=0). Build Workers use parallel tool calls within their own context instead of sub-delegating.
- Track out-of-scope discoveries as new beads.

### Build Worker Dispatch

Use the dispatch template and prompt template from `subagent-dispatch` skill (sections 2–3).

### Failure Handling

Follow the failure handling protocol from `subagent-dispatch` skill (section 6).

### Merge Conflict Protocol

Before merging each task worktree back to the feature branch:

- **Pre-merge check**: diff task branch against feature branch to identify shared file conflicts.
- **Shared file strategy**: files commonly touched by multiple workers (e.g., `package.json`, lock files, shared config) must be assigned to a single worker or sequenced — never parallelized.
- **Conflict detection**: if merge reports conflicts, stop. Resolve before continuing.
- **Verify after resolution**: run `make verify` after resolving any conflict.

### Phase 2 Completion

After all workers finish and merges complete:
```bash
make build-checkpoint CP=implement_complete
```

> **Note**: `implement_complete` is an advisory checkpoint for state tracking. Phase enforcement is via evidence artifacts checked by the Stop hook.

**MANDATORY**: Proceed to Phase 3. Skipping verification/review is not an option — the Stop hook enforces this via required evidence artifacts.

---

## Phase 3 — Verify and Review

> **DO NOT SKIP THIS PHASE.** The Stop hook will block build completion if evidence artifacts are missing.

Each sub-phase MUST produce an evidence artifact in `.claude/build-evidence/`. The build cannot complete without all six evidence files (verify, security-review, simplification, human-validation, docs-review, retro).

### 3a. Verification

Run `make verify`. Fix any failures. Then save evidence:

```bash
make build-evidence PHASE=verify DATA='{"tests_run": <count>, "tests_passed": <count>, "tests_failed": 0}'
```

### 3b. Security Guard Pass

Review all changed files (`git diff --name-only <default-branch>...HEAD`) for:
- Regressions in existing behavior
- Security issues (hardcoded secrets, unsafe inputs, missing auth checks)
- Missing edge-case tests
- Files modified outside declared scope

Fix critical findings. Then save evidence:

```bash
make build-evidence PHASE=security-review DATA='{"files_reviewed": [<list>], "findings": [<list-or-empty>], "critical_issues": 0}'
```

### 3c. Code Simplification

Dispatch one Simplifier agent (`simplify-{feature-slug}`) reviewing changed files for:
- Unnecessary complexity or dead code
- Inconsistent naming
- Missed reuse opportunities

Simplifier agents do NOT use worktree isolation — they operate directly on the feature branch in the build worktree.

For major refactors: dispatch three parallel Simplifiers (structure, naming, logic). Reconcile findings, apply accepted changes, re-verify. Then save evidence:

```bash
make build-evidence PHASE=simplification DATA='{"changes_applied": <count-or-0>, "justification": "<summary>"}'
```

### 3d. Human Validation

> **THIS IS THE ONE PHASE THAT REQUIRES HUMAN INPUT.** Do not skip or auto-approve.

This phase ensures behavioral correctness beyond what automated tests can verify. It is enforced by the `human-validation.json` evidence artifact in the build-completion-gate hook.

1. **Auto-start dev environment**: Automatically run `make dev` (or the project's equivalent dev server target) so the user has a running instance to validate against. Do not ask — just start it. If no dev server target exists, skip to step 2.
2. **Present validation checklist**: Generate a checklist from completed task beads. For each task:
   - What changed (1 line)
   - How to verify it manually (specific action the user can take)
3. **Wait for user confirmation**: Use AskUserQuestion to present the checklist and wait for the user to confirm each item passes. Do not proceed until the user explicitly approves.
4. **Save evidence**:

```bash
make build-evidence PHASE=human-validation DATA='{"checklist_items": <count>, "user_approved": true, "dev_server_used": <true|false>}'
```

### Phase 3 Completion

```bash
make build-checkpoint CP=verify_passed && make build-checkpoint CP=simplification_done && make build-checkpoint CP=human_validated
```

> The `verify_passed` checkpoint is **required** — `git commit` is blocked by the compliance hook until this is set. `simplification_done` and `human_validated` are advisory (enforcement is via their respective evidence artifacts).

**MANDATORY**: Proceed to Phase 4. The build cannot complete without docs-review evidence.

---

## Phase 4 — Documentation

> **DO NOT SKIP.** The Stop hook will block build completion without docs evidence.

Check README, AGENTS.md, CLAUDE.md, and any docs/ files that reference changed behavior.

- Update docs where behavior changed. Keep scoped to actual changes.
- If no doc updates needed, document why in evidence.

```bash
make build-evidence PHASE=docs-review DATA='{"docs_checked": [<list>], "changes_made": [<list-or-empty>], "no_changes_reason": "<if-applicable>"}'
make build-checkpoint CP=docs_updated
```

> `docs_updated` is advisory. Enforcement is via the `docs-review.json` evidence artifact checked by the Stop hook.

**MANDATORY**: Proceed to Phase 5. The build cannot complete without retro evidence.

---

## Phase 5 — Delivery

> **DO NOT STOP TO ASK** about committing or creating PRs. Execute delivery autonomously.

> **PRE-DELIVERY GATE**: Before any delivery actions, verify ALL evidence artifacts exist: `make build-evidence-check`. If any are missing, go back and complete the missing phase. Do not proceed with delivery until all evidence is present.

### 5a. Post-Build Retrospective

> **DO NOT SKIP.** The Stop hook requires a `retro.json` evidence artifact before build completion.

Produce a brief retrospective while still on the feature branch, so findings can be actioned before merge. **Present the retro to the user in conversation** — the evidence file is for the Stop hook gate, but the human needs to see and iterate on the feedback. **Categorize all feedback by target** so it's actionable, not a wall of text:

1. **What worked**: Effective patterns, tools, dispatch strategies.
2. **What didn't**: Failures, retries, conflicts, rework causes.
3. **Categorized recommendations** — group every suggestion into exactly one category:
   - **Project learnings**: Insights specific to this codebase → `bd remember "insight text" --key short-key` for persistent memory
   - **Global preferences**: Workflow/tool preferences that apply across all projects → note for CLAUDE.md or global memory
   - **Marketplace feedback**: Improvements to rpw-agent-marketplace plugins/skills → create beads for follow-up
4. **Metrics**: Tasks count, workers dispatched, retries, conflicts resolved, beads closed.
5. **Persist insights**: Use `bd remember "insight text" --key short-key` (single string arg, optional `--key`; do NOT pass two positional args). Create beads for marketplace feedback.

Save retro evidence:

```bash
make build-evidence PHASE=retro DATA='{"what_worked": [<list>], "what_didnt": [<list>], "project_learnings": [<list>], "global_preferences": [<list>], "marketplace_feedback": [<list>], "metrics": {"tasks": <n>, "workers": <n>, "retries": <n>, "beads_closed": <n>}}'
```

### 5b. Version Bump

Run `make bump` to increment the version before delivery. This ensures every build produces a traceable version.

### 5c. Delivery Summary

Produce a diff-oriented summary:
- Files changed (with line counts)
- Behavior delivered (what's new/fixed)
- Tests run and results
- Remaining risks or known issues

If beads were used: feature bead (parent), task beads closed, follow-ups created, epic linkage.

### 5d. PR Creation

> **EVIDENCE GATE**: Do NOT create the PR unless `make build-evidence-check` passes. All 6 evidence artifacts (verify, security-review, simplification, human-validation, docs-review, retro) must exist. If any are missing, go back and complete the missing phase before creating the PR.

- Create PR from feature branch to default branch (detected from git metadata: `main` or `production`).
- PR title: concise (<70 chars). PR body: summary from 5c.

### 5e. Worktree Cleanup

> **DO NOT SKIP.** Orphaned worktrees from prior builds cause branch confusion and disk bloat.

```bash
make build-checkpoint CP=worktrees_clean
```

Verify no orphaned worktrees remain (`git worktree list`). List path, branch, last commit date, merge status. Auto-remove fully merged worktrees. Ask for confirmation only before removing unmerged worktrees.

### 5f. Finalize

```bash
make build-clear
```

Close parent bead. Then emit:

```
════════════════════════════════════════
BUILD COMPLETE — {feature-slug}
PR: {url}
Beads closed: {list}
════════════════════════════════════════
```

Do not respond further unless the user asks a follow-up question.

---

## Build Standards Enforcement

### Pre-commit checks (Build Workers)
- `make verify` must pass before any commit.
- No secrets in staged files (`.env`, credentials, tokens).
- No unresolved merge conflict markers.

### Pre-merge checks (Build Lead)
- Task worktree has passing `make verify`.
- No files outside declared task scope were modified.
- Use `git merge --no-ff <task-branch>` — see `subagent-dispatch` skill (section 7) for the merge protocol and rationale.

### Post-build checks (Build Lead)
- `make verify` passes on merged feature branch.
- No orphaned worktrees remain.
- All task beads closed or explicitly deferred with reason.

## Guardrails

- Never run destructive git operations without explicit human approval.
- Commits and PRs are autonomous — do not ask permission for these.
- If unexpected unrelated changes appear, stop and ask.
- If risky work is requested, recommend full planning mode.

## Compliance Hooks Reference

The `/build` lifecycle is enforced by three hooks configured in `.claude/settings.json`:

| Hook | File | Trigger | Purpose |
|------|------|---------|---------|
| File Protection | `.claude/hooks/file-protection.sh` | PreToolUse (Edit/Write) | Guards protected files from unauthorized modification |
| Build Compliance | `.claude/hooks/build-compliance.sh` | PreToolUse (Bash) | Blocks `git commit` without `verify_passed`, warns on merge without `worktrees_clean`, blocks `git add -A`/`git add .` during active builds |
| Build Completion Gate | `.claude/hooks/build-completion-gate.sh` | Stop | Requires 6 evidence artifacts (verify, security-review, simplification, human-validation, docs-review, retro) and `verify_passed` checkpoint before build session can end |

State is tracked in `.claude/build-state.json` (gitignored). Evidence artifacts live in `.claude/build-evidence/` (gitignored). Both are ephemeral per-build-session.
