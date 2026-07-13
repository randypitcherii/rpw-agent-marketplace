---
name: human-todo
description: HUMAN to-do list / personal task management — canonical operating model for the human's work backlog. Use when setting up the human's task-tracking repo, selecting or creating the GitHub repository for tasks, resuming a repo this skill already manages, updating task status, handing off work between sessions, or triaging the backlog.
skill_version: 2
managed_repo_topic: rpw-human-todo
---

# Human To-Do

**HUMAN task management.** This skill defines the canonical operating model for the human's personal to-do list (GitHub Issues + Project). The human owns their tasks; agents create, update, and sync task state within this model.

## Skill Versioning & Managed-Repo Detection

This skill is versioned via the `skill_version` frontmatter field (currently **2**). Versioning serves two purposes:

1. **Detect repos this skill manages.** At setup, the skill stamps the repo with the GitHub **topic** `rpw-human-todo` (the `managed_repo_topic` field) and records `skill_version` in local config. A repo carrying that topic is managed by this skill — list it as a resume candidate, not a new-setup target.
2. **Support upgrades.** Compare the `skill_version` saved in `~/.claude/rpw-published.local.md` against this skill's `skill_version`. If the saved version is lower (or absent — treat absent as v1), the config predates the current model; run the setup/validation flow to upgrade it (add missing fields, apply the managed-repo topic, re-stamp `skill_version`).

```bash
# Find repos this skill already manages (topic-based detection)
gh repo list <owner> --visibility private --limit 100 \
  --json name,url,repositoryTopics \
  --jq '.[] | select(.repositoryTopics[]?.name == "rpw-human-todo") | "\(.name) \(.url)"'

# Stamp a repo as managed (run once at setup, idempotent)
gh repo edit <owner>/<repo> --add-topic rpw-human-todo
```

## Configuration State (Required)

Persist task-system configuration in a local, user-managed file:

- State file: `~/.claude/rpw-published.local.md` (global, in user's home directory)
- This is a user-managed file outside any project repo; no gitignore or template commit needed.
- The file is named after the **plugin** (`rpw-published`), not this skill — keep the path stable across skill renames.

Minimum frontmatter fields:

```markdown
---
enabled: true
skill_version: 2
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

If the state file is missing, incomplete, points to an inaccessible/missing repository, or records a `skill_version` lower than this skill's, run the setup flow before doing task operations.

## Setup Flow (First Run)

The setup flow is split into two phases: **(A) select the repo**, then **(B) handle the issues already in it**. Do not skip the repo-selection phase even when the user names a repo — confirm against the managed-repo detection first.

### Phase A — Select the repository

1. **List private repos first.** Before asking anything, enumerate the user's private repos and detect which (if any) this skill already manages:

   ```bash
   gh repo list <owner> --visibility private --limit 100 \
     --json name,url,repositoryTopics,updatedAt --jq 'sort_by(.updatedAt) | reverse'
   ```

2. **Present existing repos as markdown hyperlinks.** Render each candidate as a clickable link to its GitHub web page, e.g. `[owner/tasks](https://github.com/owner/tasks)`. Group them so the human can scan quickly.

3. **Then ask existing-vs-new**, making each suggestion explicit about whether it points at an **existing repo** or a **proposed new repo**:

   - **If exactly one repo carries the `rpw-human-todo` topic** → explicitly recommend **resuming from it**: "This repo is already managed by your human-todo skill — resume from [owner/repo](url)?" Make clear this is an *existing* managed repo.
   - **If multiple managed repos exist** → list all of them as resume candidates (markdown links) and ask which to use.
   - **If no managed repo, but a private repo's name matches task/backlog/todo/work naming** → suggest it as an *existing* candidate (markdown link), clearly labeled "existing repo (not yet managed)".
   - **If no obvious candidate exists** → suggest **creating a new private repo** with a proposed name (e.g. `<owner>/tasks` or `<owner>/todo`), clearly labeled "proposed new repo", and allow the user to override the name.

4. **If the user chooses a public repo**, warn clearly that task history can accumulate sensitive context; require explicit confirmation before proceeding.

5. **Create or adopt the repo:**

   ```bash
   # Create a new private repo
   gh repo create <owner>/<repo> --private --confirm
   ```

6. **Stamp the repo as managed** (idempotent — safe to re-run on an adopted repo):

   ```bash
   gh repo edit <owner>/<repo> --add-topic rpw-human-todo
   ```

7. **Ensure the project exists.** Confirm the chosen repo has a project with a board view titled `All Tasks` (use `gh project` / `gh api graphql` to create fields/view if missing).

### Phase B — Handle issues in the selected repo

After the repo is selected and stamped, inspect its issues and act:

```bash
gh issue list --repo <owner>/<repo> --state all --limit 50
```

- **If the repo has no issues** → bootstrap tracking end-to-end:
  1. Ensure the `All Tasks` project + fields (Execution State, Priority, Impact) exist.
  2. Create one **sample task** issue so the human sees the model working (e.g. "Sample task — try moving me across the board"), add it to the project, set Execution State to `Backlog`.
  3. Open the project view for review (print the project URL and, where possible, `gh project view` / open it) so the human can confirm the setup looks right.

- **If the repo already has issues** → do not assume; recommend, then confirm:
  1. **Sample a few** issues (read titles/bodies/labels of ~3–5) to understand what's there.
  2. **Form a recommendation** per the existing issues: `keep` (already valid tasks — adopt into the model), `ignore` (apply the `ignore_in_tasks_views` label and filter task views), or `delete` (clearly not tasks — e.g. stale noise). For epic-based repos, recommend the **convert** path (epic-to-milestone, below).
  3. **Ask the user to confirm** the recommendation before acting. Destructive actions (delete) require explicit confirmation every time.

8. **Save final configuration** to `~/.claude/rpw-published.local.md`, including the current `skill_version`.

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
2. `skill_version` in the state file matches this skill's `skill_version` (lower/absent → run the upgrade via setup flow).
3. Configured repository is reachable with current GitHub auth and still carries the `rpw-human-todo` topic.
4. Configured project/fields still exist and are usable.

If any check fails, stop task operations, explain what failed, and re-run the setup flow to repair state.

## Setup Commands

All `gh` commands appear inline in the flow above (`gh repo list`/`create`/`edit`, `gh issue list`). Use `gh project` / `gh api graphql` to ensure project fields and the `All Tasks` view exist.

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

1. Read `~/.claude/rpw-published.local.md` before task operations.
2. If missing, invalid, stale, or a lower `skill_version`, run the setup flow and repair/upgrade it.
3. Validate repo/project accessibility (and the `rpw-human-todo` topic) before mutating tasks.
4. Create and update tasks as GitHub Issues; sync state via project fields.
5. Use Execution State for status; use `blocked` label for blocked work.
6. Record progress and handoffs in issue comments.
7. Propose Priority/Impact when triaging or when values are missing.
8. Keep output short, practical, and execution-focused; include issue numbers and links.
