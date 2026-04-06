# Release Log

Append one entry per production merge. Newest entry should be added at the top.

## Entry template

```markdown
## YYYY-MM-DD - YYYY.MM.DDNN

- **Type:** release | hotfix
- **Scope:** plugin names or `marketplace`
- **PR:** <link-or-id | `Unavailable (no remote configured)`>
- **Summary:** one sentence on user-visible impact
- **Checks:** command + status (for example: `make verify` ✅)
```

Release metadata checklist (no `TBD` values in committed entries):
- PR field is a concrete URL/ID, or explicit `Unavailable (no remote configured)`.
- Checks field names the command and pass/fail result.

## Releases
## 2026-03-11 - 2026.03.1101

- **Type:** release
- **Scope:** `rpw-building`
- **PR:** Unavailable (no remote configured)
- **Summary:** Automated production merge version bump.
- **Checks:** `make verify` ✅

## 2026-03-10 - 2026.03.1001

- **Type:** release
- **Scope:** `rpw-building`
- **PR:** Unavailable (no remote configured)
- **Summary:** Automated production merge version bump.
- **Checks:** `make verify` ✅


## 2026-03-07 - 2026.03.0701

- **Type:** release
- **Scope:** `marketplace`, `rpw-building`, `rpw-working`
- **PR:** Unavailable (no remote configured in local repo; release commit: `2a93ca5`)
- **Summary:** Establish calendar-first versioning policy and validations.
- **Checks:** `make verify` ✅ (20 tests passed locally)
