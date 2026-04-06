---
name: subagent-dispatch
description: Naming conventions, dispatch patterns, and guardrails for spawning Build Workers and other subagents
---

# Subagent Dispatch

This skill governs dispatch during `/build` sessions. For ad-hoc dispatch outside `/build` (research, debugging, minion tasks), see the `auto-dispatch` skill.

## 1. Agent Role Reference

| Role | Model | ID Pattern | Worktree | Bead Level | Typical Task | Context to Include in Prompt |
|------|-------|-----------|----------|------------|--------------|------------------------------|
| Build Lead | Opus | `build-{feature}` | build worktree | Feature (creates and owns the feature bead) | Decompose feature into beads, coordinate Build Workers, merge results | Feature spec, bead plan, file ownership map |
| Build Worker | Opus/Sonnet | `bw-{task}` | task worktree (required) | Task (executes a single task bead) | Implement a single bead: write tests, implement, commit | Bead ID, task description, file scope, acceptance criteria |
| PR Security Guard | Opus | `guard-{feature}` | none | — | Review diff for secrets, vulnerabilities, scope violations | Full diff, security checklist |
| Simplifier | Opus | `simplify-{feature}` | none | — | Reduce complexity, remove dead code, improve readability | Full diff or file set, complexity goals |
| Research Lead | Opus | `research-{topic}` | none | — | Plan research, dispatch Research Workers, synthesize findings | Research question, desired output format |
| Research Worker | Sonnet | `rw-{topic}-{n}` | none | — | Fetch, read, and summarize a specific source or subtopic | Subtopic, source URLs, summary template |
| Debug Lead | Opus | `debug-{issue}` | none | — | Diagnose bugs, dispatch Research Workers, recommend fixes | Problem description, error output, relevant files |
| Minion | Haiku | `minion-{action}` | none | — (used for bead creation, not ownership) | Bead creation, simple lookups, metadata updates, file renaming | Exact action, input data, expected output format |

## 2. Dispatch Template

Use this exact Agent tool call pattern when dispatching a Build Worker:

```
Agent(
  name: "bw-{task-slug}",
  description: "{3-5 word summary}",
  model: "sonnet",  // default; use "opus" for complex tasks
  isolation: "worktree",
  run_in_background: true,
  mode: "bypassPermissions",
  prompt: "... (MUST include absolute worktree path — see Prompt Template)"
)
```

## 3. Prompt Template for Build Workers

Use this template when constructing the `prompt` field for a Build Worker dispatch:

```
You are a Build Worker implementing task bead {bead-id}.

## Task
{task-description-from-bead}

## File Scope
You are authorized to modify ONLY these files:
{list-of-files-or-directories}

## Working Directory
Your worktree is at: {absolute-worktree-path}
All file paths must be relative to this directory. Use absolute paths when calling tools.

## Acceptance Criteria
{bullet-list-of-acceptance-criteria}

## Test Requirements
Write tests FIRST (TDD), then implement. Run `make verify` (if Makefile exists) before committing. All tests must pass.

## Commit Instruction
Commit with message: '{type}: {description}'

## Constraints
- Do not modify files outside your scope.
- Do not ask questions — make reasonable assumptions and document them in your result.
- Do not push to any remote — the Build Lead controls all merges and pushes.
- Return a brief result summary: success/failure, files changed, assumptions made.
```

## 4. Model Selection Guide

| Model | Use When |
|-------|----------|
| **Sonnet** (default) | Standard implementation tasks, file modifications, test writing, straightforward bead work |
| **Opus** | Architectural decisions, complex refactoring, multi-file coordination, prompt engineering, Build Lead role |
| **Haiku** | Minion tasks only — bead creation, simple lookups, metadata updates, renaming |

## 5. Dispatch Guardrails

- Max **5 Build Workers** per Build Lead
- Max **3 Research Workers** per Research Lead
- Max **depth 1**: subagents are leaves — they cannot spawn further subagents. The Agent tool is not available at depth=1.
- **NEVER** dispatch workers that modify the same files in parallel
- Shared files (`package.json`, lock files, config files) must be assigned to ONE worker or sequenced
- Always use `run_in_background: true` for Build Workers
- Always use `isolation: "worktree"` for Build Workers
- **ALWAYS** include the absolute worktree path in Build Worker prompts — workers get confused by nested `.claude/worktrees/` paths without explicit CWD context

### bypassPermissions Security Deny-List

When using `mode: "bypassPermissions"`, workers can bypass interactive permission prompts. To prevent accidental exposure:

- **NEVER** read or write `.env` files, `.env.*`, or any dotenv variants
- **NEVER** access `~/.aws` credentials, `~/.ssh` keys, or `~/.config` auth tokens
- **NEVER** commit files matching `.env`, `credentials.json`, `*.pem`, `*.key`
- Workers must check `git diff --cached` for secret patterns before committing

## 6. Failure Handling

When a Build Worker fails or returns an incomplete result:

1. **Assess**: Is the failure isolated (one task) or systemic (environment, dependency)?
2. **Retry once**: Re-dispatch with clarifying context if the failure was ambiguous.
3. **Fallback**: If retry fails, mark task bead as blocked and continue with remaining tasks.
4. **Partial merge**: Only merge successful worktrees. Report incomplete tasks in delivery.
5. **Escalate**: If 3+ workers fail in the same cycle, stop and ask the human.

## 7. Task Branch Merge Protocol

After a Build Worker completes:

1. Review the returned result for success/failure
2. **If successful**: merge the worker's branch to the feature branch using a regular (non-squash) merge:
   ```bash
   git merge --no-ff <task-branch>
   ```
   Use `--no-ff` to preserve a merge commit so `git branch -d <task-branch>` works cleanly afterward. Do NOT use `--squash` — squash merges create new SHAs that make git think the branch is "not fully merged", causing `git branch -d` to fail.
3. **If failed**: log the failure, do NOT merge, clean up with `git worktree remove <path> && git branch -D <branch>`
4. Run `make verify` after each merge

## 8. Hierarchy-Aware Dispatch

The Build Lead manages the beads hierarchy during `/build`:

1. **Feature bead**: The build request bead serves as the feature-level parent. If none exists, the Build Lead creates one (`bd create --type=feature`).
2. **Task beads**: Each discrete work unit gets a task bead (`bd create --type=task`) linked as a child (`bd dep add <task> <feature> --type=parent-child`).
3. **Epic linkage**: If the feature belongs to a larger initiative, link it to an epic (`bd dep add <feature> <epic> --type=parent-child`).

### Dispatch Rule
- Build Workers receive their **task bead ID** in the prompt — they work on exactly one task bead.
- Build Workers do NOT create or manage beads — they implement and commit.
- The Build Lead closes task beads after successful merge.

See `docs/beads-hierarchy-standard.md` for the full hierarchy standard.
