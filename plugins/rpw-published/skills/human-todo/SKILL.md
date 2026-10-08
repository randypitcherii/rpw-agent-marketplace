---
name: human-todo
description: HUMAN to-do list / personal task management — canonical operating model for THE TASK BOARD, the human's personal task tracking. NOT a repo's engineering backlog (that is issue-creation plus the wave skills). Use when setting up the human's task-tracking repo, selecting or creating the GitHub repository for tasks, resuming a repo this skill already manages, updating task status, handing off work between sessions, or triaging the board.
skill_version: 3
managed_repo_topic: rpw-human-todo
---

# Human To-Do

**This skill owns the task board** — the human's personal task tracking: one private GitHub repo + one project board. The human owns their tasks; agents create, update, and sync task state within this model.

**The task board is not an engineering backlog** — that belongs to `issue-creation` plus the wave skills, and this skill overrides `issue-creation` wholesale inside the task board's repo. Both names, the routing rule, and the tiebreaker for an item that could be either: `docs/process/task-vocabulary.md`.

## Skill Versioning & Managed-Repo Detection

Versioned via the `skill_version` frontmatter field (currently **3**), which serves two purposes:

1. **Detect repos this skill manages.** At setup, the skill stamps the repo with the GitHub **topic** `rpw-human-todo` (the `managed_repo_topic` field) and records `skill_version` in local config. A repo carrying that topic is managed by this skill — list it as a resume candidate, not a new-setup target.
2. **Support upgrades.** Compare the `skill_version` saved in `~/.claude/rpw-published.local.md` against this skill's. If it is lower (or absent — treat absent as v1), the config predates the current model; run the setup/validation flow to upgrade it (add missing fields, apply the topic, re-stamp `skill_version`).

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
- User-managed, outside any project repo; no gitignore or template commit needed.
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

If the state file is missing, incomplete, points to an unreachable repository, or records a lower `skill_version`, run the setup flow before any task operation.

## Setup Flow (First Run)

Two phases: **(A) select the repo**, then **(B) handle the issues already in it**. Never skip phase A even when the user names a repo — confirm against the managed-repo detection first.

### Phase A — Select the repository

1. **List private repos first.** Before asking anything, enumerate the user's private repos and detect which (if any) this skill already manages:

   ```bash
   gh repo list <owner> --visibility private --limit 100 \
     --json name,url,repositoryTopics,updatedAt --jq 'sort_by(.updatedAt) | reverse'
   ```

2. **Present existing repos as markdown hyperlinks** — e.g. `[owner/tasks](https://github.com/owner/tasks)` — grouped so the human can scan quickly.

3. **Then ask existing-vs-new**, labeling each suggestion as an **existing repo** or a **proposed new repo**:

   - **One repo carries the `rpw-human-todo` topic** → recommend resuming from it, and say it is already managed by this skill.
   - **Multiple managed repos** → list them all as resume candidates and ask which to use.
   - **No managed repo, but a private repo is named like a task/todo/work tracker** → suggest it as an *existing* candidate (markdown link), labeled "existing repo (not yet managed)".
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
  1. Ensure the project + fields (`Status`, `Destination`, Priority, Impact) exist.
  2. Create one **sample task** issue so the human sees the model working (e.g. "Sample task — try moving me across the board"), add it to the project, set `Status` to `Detected` so the triage step is visible.
  3. Open the project view (print the URL; `gh project view`) so the human can confirm the setup.

- **If the repo already has issues** → do not assume; recommend, then confirm:
  1. **Sample a few** issues (read titles/bodies/labels of ~3–5) to understand what's there.
  2. **Form a recommendation** per the existing issues: `keep` (already valid tasks — adopt into the model), `ignore` (apply the `ignore_in_tasks_views` label and filter task views), or `delete` (clearly not tasks — e.g. stale noise). For epic-based repos, recommend the **convert** path (epic-to-milestone, below).
  3. **Ask the user to confirm** the recommendation before acting. Destructive actions (delete) require explicit confirmation every time.

8. **Save final configuration** to `~/.claude/rpw-published.local.md`, including the current `skill_version`.

## Epic-to-Milestone Convert Path

When `convert` is selected and the repo has legacy epic issues, follow
`references/epic-to-milestone-migration.md`. Destructive deletion happens only in that flow and
only after explicit user confirmation.

## State Validation (Every Run)

Before task operations, confirm: the state file exists with required fields; its `skill_version`
matches this skill's (lower/absent → upgrade via the setup flow); the repo is reachable and still
carries the `rpw-human-todo` topic; the project and its fields still exist.

If any check fails, stop, explain what failed, and re-run the setup flow to repair state.

## The Model: detect → triage → destination

Use this vocabulary exactly. Tasks are **detected** from **sources**, then **triaged** to
**destinations**. Every task keeps its full lineage in its issue and comments.

- **GitHub Issues** are the single source of truth; **one** project board is the working surface.
- **Source** is an issue **label**, not a project field: `source: slack`, `source: agent`,
  `source: human`. Labels survive an item leaving the board and are visible to `gh issue list`;
  project fields are neither.
- **`Status`** is the single lifecycle field. Never add a second one.
- **`Destination`** is a separate single-select — the output of triage. Keep it off Status:
  lifecycle and destination are independent axes and one single-select cannot carry both.

| `Status` | Meaning |
|---|---|
| `Detected` | Arrived from a source, not yet triaged — the inbox |
| `Backlog` | Triaged, not scheduled — a **task-board column**, never "the backlog" |
| `Todo` | Triaged and queued |
| `Today` / `Now` | Doing it today / right now (use sparingly) |
| `In Progress` | Started |
| `Done` | Complete — see the cleanup rule below |

`Destination`: `Me` (human does it) · `Agent` (dispatch to an agent) · `Delegate` (hand to a
person) · `Calendar` (becomes a scheduled event) · `Drop` (deliberately not doing it).

### Done triggers cleanup — do not do the cleanup yourself

Moving an item to `Done` is the *signal*, not the finish. The task service (high-voltage) reacts
to that board change: it marks the source (e.g. a Slack emoji), adds the final comment, and then
closes the issue. It runs as a batch pass, so expect a delay — that is by design.

**So: set `Status = Done` and stop.** Do not close the issue by hand; closing is the last step of
a sequence you are not running, and doing it early strands the cleanup.

## Blocked Work

- Use the **`blocked` label** on the issue.
- Do **not** use a separate blocked column — `Status` carries lifecycle only.
- Add a comment explaining the blocker when applying the label.

## Updating and Handing Off Work

1. **Status changes**: Update the issue's `Status` in the project.
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

1. **Validate state first** (State Validation, above) before mutating any task.
2. Create and update tasks as GitHub Issues; sync state via project fields.
3. Use `Status` for lifecycle and `Destination` for triage output; use the `blocked` label for
   blocked work. Setting `Status = Done` is where your involvement ends — never close a task issue
   by hand.
4. Record progress and handoffs in issue comments.
5. Propose Priority/Impact when triaging or when values are missing.
6. Keep output short, practical, and execution-focused; include issue numbers and links.
