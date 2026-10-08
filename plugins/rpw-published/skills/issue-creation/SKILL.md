---
name: issue-creation
description: The default path for authoring GitHub issues. Use when creating, drafting, filing, splitting, or substantially rewriting an issue in ANY repo. Trigger on "file an issue", "open a GitHub issue", "write this up as an issue", "split this into issues", or before any `gh issue create` / `gh issue edit --body`. Detects repo ownership first — owned repos get the canonical structure, external repos defer to their documented standards. NOT for triaging or closing existing issues.
---

# Issue Creation

Authoring a GitHub issue is a **policy decision before it is a writing task**: on a repo you own, a thin issue is your future self's problem; on a repo you don't, your house style is an imposition on someone else's tracker. This skill forks on that question first, then writes.

Pipeline: **detect ownership → discover standards → dedupe → classify + label → draft → file**.

Companions: [reference.md](reference.md) (canonical body shape, discovery checklist, label + hierarchy rules), [examples.md](examples.md) (three worked examples), [ownership.py](ownership.py) (the classifier).

## 1. Detect ownership — always first

```bash
uv run --no-project python "$CLAUDE_PLUGIN_ROOT/skills/issue-creation/ownership.py" --repo owner/name
```

Prints `{"classification": "OWNED"|"EXTERNAL", "owner": ..., "reason": ...}`. Equivalent by hand: compare `gh repo view --json owner -q .owner.login` against `gh api user -q .login`, plus any orgs named in `$RPW_OWNED_ORGS`.

Two rules the classifier encodes, and you must not relax:

- **Write or admin permission is not ownership.** Maintaining someone else's project is precisely when their conventions govern. `viewerPermission` is never consulted.
- **Unknown resolves to EXTERNAL.** If either login is unreadable, defer. Over-deferring costs a plainer issue on your own repo; under-deferring means ignoring a stranger's `CONTRIBUTING.md`.

## 2. Precedence model — state it, don't improvise it

| Repo | Authority order |
|---|---|
| **OWNED** | 1. A specialization the repo itself documents (`AGENTS.md`, `docs/process/`, issue templates) → 2. the canonical structure in [reference.md](reference.md) → 3. your judgment |
| **EXTERNAL** | 1. The target repo's required standards (templates/forms, `CONTRIBUTING*`, label set) → 2. its observable conventions (recent well-received issues) → 3. your preferences, **only in the gaps those leave** |

The asymmetry is the point. On an owned repo the canonical structure is the default and a documented local rule overrides it. On an external repo the canonical structure is never the default — it is only a source of *content* poured into whatever shape the host requires. Never add a house section to an external issue form, never apply a house label taxonomy to a foreign label set, never restructure a maintainer's template because a richer shape exists.

When an external repo's standards are silent (no templates, no `CONTRIBUTING`, unstructured issue history), fill the gap with the canonical structure **minus** anything that reads as process the maintainers didn't ask for: keep problem, reproduction, impact, and acceptance; drop priority labels, hierarchy links, and status ceremony.

## 3. Discover standards (EXTERNAL — mandatory; OWNED — quick)

Read before drafting: `.github/ISSUE_TEMPLATE/` (a `.yml` **form** is binding — every `required: true` field must be answered), `CONTRIBUTING*`, `AGENTS.md`/`CLAUDE.md`, `README` contribution section, `gh label list`, and 3–5 recent non-stale issues that maintainers engaged with. Full checklist and the "which signal wins" table: [reference.md](reference.md).

If a repo has issue forms and blank issues are disabled, `gh issue create --body` bypasses the form — that is a violation, not a shortcut. Fill the form's fields as headings in the same order, or file through the web form.

## 4. Search for duplicates — before drafting, not after

```bash
gh issue list --repo owner/name --state all --search "<3-5 distinctive keywords>" --limit 30
```

Search **all** states, twice, with different vocabulary (the user's words and the codebase's words). A near-duplicate that is open → comment on it with the new evidence instead of filing. Closed as fixed → verify the fix actually shipped before refiling. Closed as wontfix → do not refile without naming the changed circumstance.

## 5. Classify type + hierarchy, and label from the real set

Pick exactly one type; broken-behavior beats every other type. Epic = multi-session, spans several issues, holds a checklist — if it fits in one PR it is not an epic. Feature = one PR-sized new capability. Task = self-contained work that adds no capability. Full boundaries and the parent/child linkage rules: [reference.md](reference.md).

**Labels come from `gh label list` on the target repo. Never invent one, never carry a label name across repos.** `gh issue create` fails on an unknown label, so a guessed label is a filing error, not a style nit. Map intent to whatever the repo actually has; if it has nothing equivalent, apply nothing.

Splitting a large request into issues: file the parent first, then children referencing it, then edit the parent's checklist with the real numbers.

## 6. Draft and file

Bodies go through a quoted HEREDOC so markdown, backticks, and `$` survive intact:

```bash
gh issue create --repo owner/name \
  --title "<component>: <concise description>" \
  --label "type: feature" --label "priority: P2" \
  --body "$(cat <<'EOF'
## Problem
...
EOF
)"
```

Title: `<component>: <description>` on owned repos, sentence-case, no type markers (`[bug]`, `feat:`, `WIP`) — labels carry type. On external repos, match their observed title convention instead.

Never paste tokens, credentials, internal hostnames, customer names, or private URLs into a public tracker. Report the returned issue URL and the labels applied.

## Composition with specialized skills

Issue prose follows the `communication` skill (problem before solution, short sectioned bodies, link evidence instead of inlining logs) — this skill supplies the GitHub-specific pipeline and body shape on top of it.

This is the **default**, not an override. A more specific skill wins within its scope and inherits everything here that it does not restate:

- `marketplace-feedback` — feedback about this marketplace. Its classification, labels, and body shape win; ownership detection is moot (owned).
- `generate-backlog` — many engineering-backlog proposals at once. Its user checkpoint is authoritative; this skill governs the shape of each issue it files.
- `dispatch-launch` / `wave-supervisor` — file engineering-backlog issues as dispatch fuel; use this shape so a worker can act with no back-channel context.
- `issue-first-development` — the gate that decides an issue must exist before code, and applies the public/foreign-repo
  disclosure filter. It runs *before* this skill and hands the drafting here; it never replaces this body shape.
- `human-todo` — **the task board** (the human's personal task tracking), deliberately lighter. It overrides this
  skill wholesale inside the task board's repo. **This skill governs a repo's engineering backlog.** Which of the
  two a new item belongs in, and the tiebreaker when it could be either: `docs/process/task-vocabulary.md`.

If you filed an issue and none of these applied but you also didn't follow this skill, that gap is itself worth filing.
