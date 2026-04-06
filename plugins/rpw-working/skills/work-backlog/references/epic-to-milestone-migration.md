# Epic-to-Milestone Migration Checklist

Use when converting legacy epic issues to milestone-based tracking during first-run setup.

## Steps

1. Discover epics (Type: epic or Epic: prefix)
2. Map children (Blocked by #N, Part of #N)
3. Create milestone per epic; strip Epic: from title
4. Assign milestone to all child issues
5. Audit epic: delete if boilerplate only; else migrate notes, close, comment
6. Cleanup stale Blocked by lines on children of deleted epics
7. Verify: report counts and links

## Safety

- Destructive deletion only after explicit user confirmation
- Never delete without confirmation
