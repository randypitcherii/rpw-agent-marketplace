# Issue Creation — reference

Supporting detail for [SKILL.md](SKILL.md): the canonical body shape for owned repos, the external-repo discovery checklist, type boundaries, hierarchy/linkage rules, and the ownership classifier's contract. Worked examples live in [examples.md](examples.md).

## Ownership classifier contract

[ownership.py](ownership.py) is the deterministic half of the skill. Everything else is judgment; this is not.

```bash
uv run --no-project python "$CLAUDE_PLUGIN_ROOT/skills/issue-creation/ownership.py" --repo owner/name
uv run --no-project python "$CLAUDE_PLUGIN_ROOT/skills/issue-creation/ownership.py"   # repo in cwd
RPW_OWNED_ORGS="my-org,my-other-org" uv run --no-project python .../ownership.py --repo my-org/thing
```

Python always runs through `uv`, never a bare `python3`. `--no-project` is load-bearing here rather than ceremony: step 1 runs in **whatever repo you are filing against**, and a plain `uv run` would resolve that repo's `pyproject.toml` first — so a target project with unsatisfiable dependencies would fail the ownership check instead of answering it. The classifier is stdlib-only and needs no project environment at all.

| Input | Source |
|---|---|
| repo owner login | `gh repo view <repo> --json owner -q .owner.login` |
| viewer login | `gh api user -q .login` |
| owned orgs | `$RPW_OWNED_ORGS` (comma-separated) or `--owned-orgs` |

Decision table (first match wins):

| Condition | Result | `reason` |
|---|---|---|
| owner login missing/blank | `EXTERNAL` | repo owner could not be determined |
| owner is a configured owned org | `OWNED` | repo owner is a configured owned org |
| viewer login missing/blank | `EXTERNAL` | authenticated user could not be determined |
| owner == viewer (case-insensitive) | `OWNED` | repo owner is the authenticated user |
| otherwise | `EXTERNAL` | repo owner is neither the authenticated user nor an owned org |

Deliberate non-inputs:

- **`viewerPermission`.** ADMIN or WRITE on a repo you do not own is the *most* important case to classify EXTERNAL — a maintainer bypassing the project's own issue conventions is worse than a stranger doing it.
- **Org membership (`gh api user/orgs`).** Being in an org is not owning its repos. Orgs must be named explicitly in `RPW_OWNED_ORGS`.
- **Fork status.** A fork of an external project is still governed by the upstream community's conventions when you file upstream; if you file on your own fork, the owner login already says OWNED.

Unknown always fails toward `EXTERNAL`. The classifier never raises on malformed input — a missing key, a `None`, or a non-dict payload all resolve to `EXTERNAL`.

## Canonical body shape (OWNED repos)

Sections in this order. Drop any that genuinely do not apply; do not reorder, and do not silently drop **Acceptance criteria**.

```markdown
## Problem
What is wrong or missing today, and the outcome that counts as solved.
One paragraph. Lead with the observed behavior, not the proposed fix.

## Context
How this surfaced, what is already known, links to prior art (`#N`, PRs, ADRs,
file:line). Enough that a fresh agent needs no back-channel.

## Scope
What this issue covers.

### Non-goals
What it explicitly does not cover — the section that stops scope creep and
tells a worker where to stop.

## Acceptance criteria
- [ ] Observable, checkable outcomes. Behavior, not activity.
- [ ] "Test X passes" / "command Y prints Z", not "investigate Y".

## Dependencies
Blocked by / blocks (`#N`), credentials or infrastructure required, work that
must land first.

## Risks
What could go wrong, what is uncertain, what the blast radius is.

## Implementation guidance
Optional. Target files, an approach sketch, constraints to respect. Include it
when you know something the implementer would otherwise rediscover; omit it
rather than pad it.

## Verification
How the reviewer confirms it works: the exact command, the gate to run, the
observable end state. Name the actual check — not "verified manually".
```

**Bugs** additionally carry a `## Reproduction` block right after Problem: exact command or steps, then observed vs expected.

Title: `<component>: <concise description>` — sentence case, imperative or a tight noun phrase, no trailing period, no type/status markers in the title (`Epic:`, `[bug]`, `WIP`, `feat:`). Labels carry type; conventional-commit prefixes belong to PRs and commits.

## Type boundaries

Exactly one type label. Applied in this order — the first that fits wins:

| Type | Test |
|---|---|
| **bug** | Something that should work doesn't. Beats every other type: a broken feature is a bug, not a feature request. |
| **epic** | Multi-session initiative delivered across several issues/PRs; holds the phase checklist. **If it fits in one PR it is not an epic.** |
| **feature** | One PR-sized deliverable adding or enhancing capability. |
| **task** | Self-contained work that adds no capability: refactors, migrations, cleanups, docs passes, process/ADR authoring. |
| **docs** | Pure documentation gap, no code change. Some repos express this as a `documentation` label *instead of* a type. |

**Friction** ("it works, but using it is painful") is not a separate type: decide whether the fix is behavioral (bug) or a new ergonomic capability (feature), apply that, and lead the Problem section with `friction:`.

## Hierarchy and linkage

- **Child → parent:** the child body says `Part of #N`. Do not rely on the parent's checklist alone; the link must survive reading either issue in isolation.
- **Parent → children:** the epic body carries a task list of `- [ ] #N` entries. File the parent first so children have a number to reference, then edit the parent once the children exist.
- **Blocking:** `Blocked by #N` / `Blocks #N` in the Dependencies section. If a repo has a native blocked-by field or a `status: blocked` label, use it *in addition* — the prose survives export, the field survives triage tooling.
- **Related but not dependent:** `Related: #N` in Context. Keep it distinct from Dependencies so a wave planner does not treat a nice-to-know link as a hard ordering constraint.
- **Cross-repo:** bare `#N` only within the same repo. Anything in another repo is fully qualified `owner/repo#N` or a URL — bare numbers silently resolve to an unrelated local issue.
- **Splitting:** each child must be independently deliverable and independently verifiable. If two children can only be reviewed together, they are one issue.

## Label selection

1. `gh label list --repo owner/name` — the live set is the only source of truth.
2. Map intent onto what exists. Namespaced families (`type:`, `priority:`) are common but not universal; bare `bug`/`enhancement` is just as common.
3. If the repo has no equivalent label, **apply nothing.** A missing label is triage work for a maintainer; an invented one is a failed `gh issue create` or a polluted label set.
4. Never carry a label name across repos. `type: feature` is meaningless on a repo that uses `enhancement`.
5. Status/claim labels are usually machine-managed — do not hand-apply them at filing time.

## External-repo discovery checklist

Run all of these before drafting. Cost is a few seconds; the failure it prevents is a maintainer closing your issue as noise.

| Signal | Where | Weight |
|---|---|---|
| Issue **forms** (`.github/ISSUE_TEMPLATE/*.yml`) | repo | **Binding.** Every `required: true` field must be answered. |
| Issue **templates** (`*.md`) | repo | **Binding shape.** Keep their headings and order verbatim. |
| `blank_issues_enabled: false` (`config.yml`) | repo | The maintainers disabled freeform filing on purpose — do not route around it with `gh issue create --body`. |
| `CONTRIBUTING*` | root, `.github/`, `docs/` | Binding. Often carries a required title format, a version/repro requirement, or "ask in Discussions first". |
| `AGENTS.md` / `CLAUDE.md` | root | Binding where it speaks to issue filing. |
| `SUPPORT.md`, README contribution section | root | Frequently redirects questions to Discussions/forum — a question filed as an issue is the most common rejection. |
| `gh label list` | repo | The only legal label vocabulary. |
| 3–5 recent engaged issues | `gh issue list --state all --limit 30` | Observable convention: title style, body length, how much repro detail maintainers actually expect. |

Conflict resolution: a **form's required fields** beat a markdown template, which beats `CONTRIBUTING` prose, which beats observed convention, which beats your preferences. Where two binding sources genuinely conflict, follow the more specific one and say so in the issue.

Signals that this should not be an issue at all: the repo routes questions to Discussions; security issues have a `SECURITY.md` disclosure path (**never** file a vulnerability as a public issue); the project asks for a reproduction repo you cannot provide yet.
