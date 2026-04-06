---
name: work-backlog
description: HUMAN task management — canonical operating model for the human's work backlog. Use when setting up task tracking, selecting or creating the GitHub repository for tasks, updating task status, handing off work between sessions, or triaging backlog.
---

# Work Backlog

**HUMAN task management.** This skill defines the canonical operating model for the human's task system (GitHub Issues + Project). The human owns and manages their tasks; agents operate within this model to create, update, and sync task state.

## Configuration State (Required)

Persist task-system configuration in a local, user-managed file:

- State file: `~/.claude/rpw-working.local.md` (global, in user's home directory)
- This is a user-managed file outside any project repo; no gitignore or template commit needed.

Minimum frontmatter fields:

```markdown
---
enabled: true
github_owner: "your-github-user-or-org"
github_repo: "your-private-tasks-repo"
github_repo_url: "https://github.com/your-github-user-or-org/your-private-tasks-repo"
github_project_number: 3
project_title: "All Tasks"
ignore_label: "ignore_in_tasks_views"
execution_state_field: "Execution State"
priority_field: "Priority"
impact_field: "Impact"
---
```

If the state file is missing, incomplete, or points to an inaccessible/missing repository, agents should run setup flow before doing task operations.

## Setup Flow (First Run)

1. Ask user to choose:
   - Use an existing repository, or
   - Create a new private repository for tasks.
2. Attempt to list private repos for the user's account and suggest a good candidate if one matches task/backlog/work naming.
3. If no strong candidate exists, recommend creating a new private repo.
4. If user chooses a public repo, warn clearly that task history can accumulate sensitive context; require explicit confirmation before proceeding.
5. Ensure the chosen repo has a project with a board view titled `All Tasks`.
6. If repo already has issues, ask how to handle existing issues:
   - `ignore`: apply `ignore_in_tasks_views` label and filter task views to exclude it
   - `convert`: normalize existing issues into this model (state/priority/impact where possible); for epic-based repos, use the epic-to-milestone bootstrap (see below)
   - `delete`: only after explicit confirmation
7. Save final configuration to `~/.claude/rpw-working.local.md`.

## Epic-to-Milestone Convert Path

When `convert` is selected and the repo has legacy epic issues, bootstrap milestone-based tracking:

1. **Discover epics**: Find issues with `- Type: epic` in body, or title prefix `Epic:` as fallback.
2. **Map children**: For each epic, find child issues via body references `Blocked by #<epic>` and `Part of #<epic>`.
3. **Create milestones**: One milestone per epic; title = epic title with `Epic:` prefix stripped.
4. **Assign milestone**: Assign the milestone to all child issues.
5. **Audit epic value**:
   - If epic has only boilerplate migration metadata and no meaningful comments: delete epic.
   - Else: migrate meaningful notes to milestone description, assign epic to milestone, close epic, add comment.
6. **Cleanup**: Remove stale `Blocked by #<epic>` lines from child issue bodies when the epic was deleted.
7. **Verify**: Report migration summary (counts, links).

**Safety rule**: Destructive deletion (epics, issue content) happens only in this convert flow and only after explicit user confirmation. Never delete without confirmation.

See `references/epic-to-milestone-migration.md` for the migration checklist.

## State Validation (Every Run)

Before task operations, validate state by checking:

1. State file exists and required fields are present.
2. Configured repository is reachable with current GitHub auth.
3. Configured project/fields still exist and are usable.

If any check fails, stop task operations, explain what failed, and re-run setup flow to repair state.

## Setup Commands (CLI Reference)

Use `gh` as the default interface:

```bash
# List private repos for the current user
gh repo list <owner> --visibility private --limit 100

# Create a new private repo
gh repo create <owner>/<repo> --private --confirm
```

Use `gh project` / `gh api graphql` as needed to ensure project fields and `All Tasks` view exist.

## Where Tasks Live

- **GitHub Issues** are the single source of truth.
- **GitHub Project** fields (Execution State, Priority, Impact) extend issues.
- Prefer project updates over custom local tracking files.
- Keep work discoverable via labels, comments, and project state.

## Status (Execution State)

Use these project field values for board movement:

| Value          | Meaning                          |
|----------------|----------------------------------|
| `Backlog`      | Not yet scheduled                |
| `To Do`        | Scheduled, ready to start        |
| `In Progress`  | Actively being worked on         |
| `Now`          | Current focus, used sparingly    |
| `Done`         | Completed                        |

## Blocked Work

- Use the **`blocked` label** on the issue.
- Do **not** use a separate blocked column.
- Add a comment explaining the blocker when applying the label.

## Updating and Handing Off Work

1. **Status changes**: Update the issue's Execution State in the project.
2. **Progress notes**: Add concise issue comments (not separate docs).
3. **Handoff**: Add a short comment with:
   - Current state
   - Next steps
   - Any blockers or context

Example handoff comment:

```markdown
**Handoff**
- State: In Progress, ~60% done
- Next: Implement validation in `src/validate.py`
- Blocker: None
```

## Scoring and Triage

- **Priority** and **Impact**: numeric `0-100` scale on project fields.
- If missing: suggest values with brief rationale.
- **Priority**: urgency/importance (higher = more urgent).
- **Impact**: outcome value (higher = more valuable).

## Expected Agent Behavior

1. Read `~/.claude/rpw-working.local.md` before task operations.
2. If missing, invalid, or stale, run the setup flow and repair/create it.
3. Validate repo/project accessibility before mutating tasks.
4. Create and update tasks as GitHub Issues; sync state via project fields.
5. Use Execution State for status; use `blocked` label for blocked work.
6. Record progress and handoffs in issue comments.
7. Propose Priority/Impact when triaging or when values are missing.
8. Keep output short, practical, and execution-focused; include issue numbers and links.
