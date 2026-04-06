---
description: Bootstrap or repair task tracking setup; optionally convert legacy epics to milestones
argument-hint: [repo-url]
---

# Task Setup

Run the work backlog setup flow.

1. **Validate state**: Check `~/.claude/rpw-working.local.md` exists and has required fields (github_owner, github_repo, github_repo_url, github_project_number, etc.). Verify repo is reachable with current GitHub auth.

2. **If state missing or invalid**: Run setup:
   - Ask user: use existing repo or create new private repo.
   - If existing: list private repos, suggest candidates matching task/backlog/work naming.
   - If public repo chosen: warn about sensitive context; require explicit confirmation.
   - Ensure chosen repo has a project with board view titled `All Tasks`.
   - Ask how to handle existing issues: `ignore`, `convert`, or `delete` (only after explicit confirmation).

3. **If convert selected**: Run epic-to-milestone bootstrap (use work-backlog skill):
   - Discover epics (Type: epic or Epic: prefix).
   - Map children (Blocked by #N, Part of #N).
   - Create milestone per epic, assign to children.
   - Audit epic value: delete if boilerplate only; else migrate notes, close epic, comment.
   - Cleanup stale Blocked by references on deleted epics.
   - **Before any destructive deletion**: require explicit user confirmation.
   - Verify and report migration summary (counts, links).

4. **Save**: Write final config to `~/.claude/rpw-working.local.md`.

Use the work-backlog skill for detailed steps and safety rules.
