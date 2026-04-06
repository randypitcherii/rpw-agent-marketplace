# Build Command Migration Implementation Plan

> **Historical note:** This file is archived execution history from `docs/plans/2026-03-05-build-command-migration-implementation.md` and is retained for provenance only (not an active plan).

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade `/build` for autonomous-safe execution with Claude-first standards, reliable Cursor compatibility, Beads-first orchestration, and explicit research/decision hygiene.

**Architecture:** Keep a Cursor-safe `build.md` and introduce a Claude-first variant path with deterministic conversion/linking. Add command policy changes in phases, backed by repository tests and Makefile-first workflows. Use Beads as the planning/execution backbone with feature-scoped sub-beads and worktree isolation.

**Tech Stack:** Markdown command specs, Makefile orchestration, Python unittest (`tests/test_repo_validations.py`), Beads CLI (`bd`), Git worktrees.

---

### Task 1: Baseline validation and safety snapshot

**Files:**
- Modify: none
- Test: `tests/test_repo_validations.py` (read-only baseline)

**Step 1: Capture current repo status**

Run: `git status --short --branch`  
Expected: current branch and any pre-existing unrelated changes listed.

**Step 2: Run baseline tests**

Run: `make verify`  
Expected: current suite passes or known failures are documented before edits.

**Step 3: Capture command linking baseline**

Run: `make list && make check`  
Expected: current command source/destination mapping visible for Cursor and Claude.

**Step 4: Commit safety checkpoint (optional, only if changed)**

Run:
`git add -A && git commit -m "chore: snapshot pre-migration baseline"`  
Expected: commit succeeds only if any generated baseline artifacts were intentionally added.

### Task 2: Add TDD guard tests for new `/build` structure

**Files:**
- Modify: `tests/test_repo_validations.py`
- Test: `tests/test_repo_validations.py`

**Step 1: Write failing test for Claude-first build command artifact**

Add test asserting expected command file strategy (for example existence of `build.md` Cursor-safe and Claude variant artifact path).

**Step 2: Run targeted tests to verify failure**

Run: `uv run python -m unittest tests.test_repo_validations.TestMarketplacePlugins.test_building_plugin_has_commands -v`  
Expected: FAIL due to missing new artifact/assertions.

**Step 3: Write minimal test updates for Makefile-driven linking expectations**

Add a focused test for expected behavior encoded in file layout and manifest assumptions.

**Step 4: Run targeted tests again**

Run: `uv run python -m unittest tests.test_repo_validations.py -v`  
Expected: still FAIL until implementation files/Makefile are updated.

**Step 5: Commit tests-only checkpoint**

Run:
`git add tests/test_repo_validations.py && git commit -m "test: add build command migration guardrails"`  
Expected: tests-first commit recorded.

### Task 3: Implement Claude-first build command format and Cursor compatibility path

**Files:**
- Create: `plugins/rpw-building/commands/build.claude.md`
- Modify: `plugins/rpw-building/commands/build.md`
- Modify: `Makefile`
- Modify: `plugins/rpw-building/.claude-plugin/plugin.json` (only if needed for explicit command selection)

**Step 1: Create `build.claude.md` as unified Claude-first command**

Include frontmatter and full policy updates:
- autonomous fast path + full planning mode
- commit/destructive-git policy
- Opus code-simplifier policy (3 parallel Opus for major refactors)
- Makefile-first execution
- Beads hierarchy and discovered-work handling

**Step 2: Keep `build.md` Cursor-safe**

Keep Markdown format compatible with Cursor and include compatibility notes.

**Step 3: Update `Makefile` linking rules**

Implement deterministic mapping so Cursor receives Cursor-safe command and Claude receives Claude-first variant.

**Step 4: Run quick static checks**

Run: `make list && make check`  
Expected: expected links and no ambiguous command mapping.

**Step 5: Commit implementation slice**

Run:
`git add plugins/rpw-building/commands/build.md plugins/rpw-building/commands/build.claude.md Makefile plugins/rpw-building/.claude-plugin/plugin.json && git commit -m "feat: add claude-first build command with cursor compatibility path"`  
Expected: atomic feature commit.

### Task 4: Beads orchestration policy implementation

**Files:**
- Modify: `plugins/rpw-building/commands/build.claude.md`
- Modify: `plugins/rpw-building/commands/build.md`

**Step 1: Add parent-bead and feature-sub-bead creation flow**

Encode required parent/sub-bead hierarchy and dependency linking.

**Step 2: Add mandatory follow-up sub-beads**

Add policy for automatic creation of sub-beads for:
- build command versioning
- Claude->Cursor conversion reliability
- custom subagent definitions (`researcher`, `investigator`, `task-assistant`)
- subagent-created-subagent feasibility research

**Step 3: Add discovered-work bead policy**

Document that bugs/debt/future work discovered mid-build are captured via Haiku bead-admin subagents and marked with source metadata.

**Step 4: Run command doc sanity pass**

Run: `rg "bead|sub-bead|haiku|agent-created|worktree" plugins/rpw-building/commands/*.md`  
Expected: all required policy terms present.

**Step 5: Commit policy slice**

Run:
`git add plugins/rpw-building/commands/build.md plugins/rpw-building/commands/build.claude.md && git commit -m "feat: encode beads hierarchy and agent-created follow-up policies"`  
Expected: clean policy commit.

### Task 5: Research and decision repository structure rollout

**Files:**
- Create: `docs/research/README.md` (fallback when no agent-root metadata structure exists)
- Create: `docs/decisions/README.md`
- Create: `docs/research/2026-03-05-build-command-upgrade-findings.md`

**Step 1: Create research policy docs with freshness metadata rules**

Include `date`, `status`, `review_by`, optional `superseded_by`.

**Step 2: Add current research output from parallel research tracks**

Write findings and recommendations into the dated build-upgrade findings document.

**Step 3: Add ADR guidance for durable decisions**

Add lightweight ADR conventions in `docs/decisions/README.md`.

**Step 4: Validate directory conventions**

Run: `ls -la docs && ls -la docs/research && ls -la docs/decisions`  
Expected: structure exists and files are readable.

**Step 5: Commit documentation slice**

Run:
`git add docs/research docs/decisions && git commit -m "docs: separate research findings from durable decision records"`  
Expected: docs commit created.

### Task 6: Verification, cleanup, and integration guardrails

**Files:**
- Modify: as needed based on failures from verification

**Step 1: Run full validation**

Run: `make verify`  
Expected: test suite passes.

**Step 2: Run lint-like sanity scans**

Run:
`rg "destructive|reset --hard|force push" plugins/rpw-building/commands/*.md`  
Expected: policy language matches non-destructive requirements.

**Step 3: Worktree/branch cleanup check**

Run: `git branch --list` and clean merged temporary branches per policy.

**Step 4: Final commit for any fixes**

Run:
`git add -A && git commit -m "chore: finalize build migration verification fixes"`  
Expected: only if verification produced follow-up edits.

**Step 5: Delivery summary prep**

Prepare final output with:
- changed files
- behavior changes
- verification commands and outcomes
- remaining risks/follow-up beads.

### Task 7: Beads execution checklist for this migration

**Files:**
- Modify: none (CLI operations)

**Step 1: Ensure Beads is initialized and available in repo**

Run: `bd doctor` then repair/init path as needed.

**Step 2: Create parent bead for this migration**

Run: `bd create --title "Build command migration and upgrade" --type task --priority 1 --description "<goal + acceptance criteria>"`.

**Step 3: Create feature sub-beads and dependencies**

Create sub-beads for:
- Claude-first command + Cursor compatibility
- autonomous fast path + guardrails
- code simplifier policy
- research/decision structure
- versioning follow-up
- custom subagents investigation
- subagent-spawn-subagent research

Then connect with `bd dep add`.

**Step 4: Mark active feature bead and proceed**

Run: `bd update <feature-bead-id> --status in_progress`.

**Step 5: Sync beads state**

Run: `bd sync`  
Expected: board state persisted.
