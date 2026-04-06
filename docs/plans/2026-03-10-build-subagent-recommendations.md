# Build Subagent Optimization Recommendations

**Date:** 2026-03-10
**Scope:** Maximizing subagent effectiveness in `/build` workflow

---

## 1. Reduce Orchestrator Overhead

**Problem:** The orchestrator spends significant context on planning, bead management, and merge coordination — context that could go to dispatching and reviewing.

**Recommendations:**

- **Pre-built prompt templates per role.** Create a `plugins/rpw-building/skills/agent-prompts/` directory with parameterized prompt templates for implementer, reviewer, and researcher roles. The orchestrator fills in variables (bead-id, file list, acceptance criteria) instead of composing full prompts each time. This cuts orchestrator token spend per dispatch by ~40%.
- **Batch dispatch over sequential dispatch.** The current doc says to dispatch with `run_in_background: true`, but doesn't emphasize batching. Add an explicit rule: "Dispatch all independent implementers in a single message block. Never dispatch one, wait, then dispatch the next unless there's a data dependency."
- **Move merge verification to a subagent.** After implementer worktrees squash-merge back, dispatch a `verify-{bead-id}` subagent (no worktree needed, read-only) to run `make verify` on the build worktree. The orchestrator only reviews pass/fail, not the full test output.

## 2. CLAUDE.md Improvements

**Current score: ~C+ (60/100).** The root CLAUDE.md is functional but missing key agent-facing context.

**Add to root CLAUDE.md:**

- **Architecture map.** Agents landing in this repo have no quick way to understand the plugin structure. Add:
  ```
  ## Structure
  - plugins/rpw-building/ — agentic dev workflow (commands: /build, /where-were-we, /marketplace-release)
  - plugins/rpw-working/ — human workflow tools
  - plugins/rpw-databricks/ — Databricks field work
  - docs/research/ — exploratory findings (non-binding)
  - docs/decisions/ — ADRs (binding)
  ```
- **Verification command prominence.** `make verify` is buried in Makefile. Add it as a top-level instruction: `Always run make verify before considering any work complete.`

## 3. AGENTS.md Improvements

**Current state:** Minimal — only covers worktree protocol. Missing critical subagent operating context.

**Add to AGENTS.md:**

- **Context self-sufficiency rule.** "You have no access to the parent conversation. Your prompt is your entire world. If it doesn't contain the file paths, acceptance criteria, and verification command, ask the orchestrator to re-dispatch with complete context."
- **Completion contract.** "On completion, output: (1) files changed, (2) tests run and results, (3) any discovered scope creep as a structured list. This is the merge-readiness signal."
- **Conflict avoidance rule.** "Never edit files outside your assigned scope. If you discover a needed change in an out-of-scope file, note it in your completion output — do not edit it."
- **Nested spawn policy reference.** Link to the existing research doc and state the depth-2, fan-out-3 limits directly.

## 4. Automation Hooks

**No hooks are configured.** This is the biggest quick win.

**Recommended hooks for `.claude/settings.json`:**

- **PreToolUse: block `.env`/`dev.env` edits.** Prevents agents from accidentally writing secrets.
- **PostToolUse: auto-format on Edit.** If a formatter exists (ruff, black), run it after every file edit so subagents don't produce style drift that creates merge noise.
- **PreToolUse: block edits to `manifest.json` and `marketplace.json`.** Only the orchestrator/release flow should touch these. Subagents editing them causes version conflicts.

## 5. Patterns from Past Sessions to Codify

From research docs and decision records:

- **Squash-merge is non-negotiable.** ADR-2026-03-05 and AGENTS.md both require it, but `subagent-dispatch.md` says "merge worktree branches after verification" without specifying squash. Make it explicit everywhere.
- **Nested subagents: allow but constrain.** The feasibility research (2026-03-08) recommends depth-2, fan-out-3. This is documented in research but NOT in build.md or subagent-dispatch.md where agents actually read it. Copy the guardrails into both files.
- **Research vs decisions separation.** The research README explains this well, but build.md Phase 6 should explicitly say: "Lessons learned go to `docs/research/`. Only promote to `docs/decisions/` if the lesson becomes a binding policy."
- **Code-simplifier parallel pattern.** build.md mentions "three parallel Opus code-simplifier subagents from distinct scopes" but doesn't define what "distinct scopes" means. Codify: one agent per concern (structure, naming, logic simplification).

## 6. Build → Subagent → Merge Cycle Improvements

- **Implementer completion signal standardization.** Define a structured output format that every implementer must produce. This lets the orchestrator parse results programmatically instead of reading free-form text. Proposed format:
  ```
  ## Completion Report
  - Status: success | partial | failed
  - Files changed: [list]
  - Tests: [passed/failed/skipped counts]
  - Scope creep: [list of out-of-scope items discovered]
  - Merge ready: yes | no (reason)
  ```
- **Parallel verification after merge.** Currently Phase 3 runs `make verify` once. Instead: after each implementer squash-merges, dispatch a lightweight verify subagent immediately. This catches integration failures early instead of batching them.
- **Worktree cleanup as a post-merge hook.** Implementer worktree cleanup is documented as "immediately after squash-merge" but relies on the orchestrator remembering. Add it to the completion contract: the implementer itself should exit its worktree and clean up, not wait for the orchestrator.

## Priority Order

1. **AGENTS.md completion contract + context rule** — highest leverage, zero infrastructure
2. **Hook configuration for file protection** — prevents the most common subagent mistakes
3. **Prompt templates directory** — reduces orchestrator overhead per dispatch
4. **Nested spawn guardrails in build.md** — prevents the scariest failure mode
5. **Standardized completion report format** — enables future automation of merge decisions
6. **Verify subagent after each merge** — catches integration issues earlier
