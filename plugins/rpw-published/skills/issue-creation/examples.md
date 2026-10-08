# Issue Creation — worked examples

Three end-to-end runs of the [SKILL.md](SKILL.md) pipeline, one per policy path. Each shows the ownership call, what discovery returned, the decision it forced, and the exact filing command. Repo names are illustrative.

---

## Example 1 — Owned repo (canonical structure)

**Request:** "The build worker keeps re-running the gate after a flaky exit 137. File an issue."

### Ownership

```console
$ uv run --no-project python "$CLAUDE_PLUGIN_ROOT/skills/issue-creation/ownership.py" --repo you/agent-toolbelt
{
  "classification": "OWNED",
  "owner": "you",
  "viewer": "you",
  "reason": "repo owner is the authenticated user"
}
```

`OWNED` → canonical structure is the default. Quick check for a documented local specialization: `docs/process/issue-conventions.md` exists and defines the title shape and the `type:`/`priority:` families → **that overrides the generic canonical defaults where it speaks**, and the canonical body shape fills the rest.

### Dedupe

```console
$ gh issue list --repo you/agent-toolbelt --state all --search "exit 137 gate retry" --limit 30
#412  CLOSED  build worker: gate OOMs on large diffs
```

#412 is the OOM itself, not the retry loop — related, not duplicate. It gets a `Related:` link.

### Labels

```console
$ gh label list --repo you/agent-toolbelt
type: bug          Broken or incorrect behavior
type: feature      PR-sized deliverable
priority: P1       High — schedule soon
quick win          Small, well-scoped, high-value
status: in-progress  (machine-managed — do not hand-apply)
```

Broken behavior beats every other type → `type: bug`. Retry storms burn wave capacity → `priority: P1`. Skip `status:` (machine-managed).

### File

```bash
gh issue create --repo you/agent-toolbelt \
  --title "build worker: gate retry loop repeats after a flaky exit 137" \
  --label "type: bug" --label "priority: P1" \
  --body "$(cat <<'EOF'
## Problem
A gate run killed with exit 137 is retried, but the retry counter is reset on
each new phase, so a worker whose gate OOMs twice in different phases retries
indefinitely instead of failing over to a reported blocker.

## Reproduction
1. Dispatch a worker whose `make check` exceeds the memory ceiling.
2. Observe the gate killed with exit 137 in phase `verify`.

- Observed: the worker retries the gate without bound; the wave stalls.
- Expected: at most one retry per issue, then a reported blocker.

## Context
Retry handling lives in `scripts/build-state.sh`; the counter is written into
per-phase state, which is re-initialized at each phase transition. Surfaced
during the 2026-07 wave, where two workers spent ~40 min in the loop.
Related: #412 (the underlying OOM).

## Scope
Make the exit-137 retry budget per *issue* rather than per *phase*, and report
a blocker once it is exhausted.

### Non-goals
- Fixing the OOM itself (that is #412).
- Changing retry policy for any other non-zero exit code.

## Acceptance criteria
- [ ] A second exit-137 gate failure on the same issue reports a blocker
      instead of retrying.
- [ ] The retry budget survives a phase transition.
- [ ] A regression test drives two exit-137 failures across two phases and
      asserts exactly one retry.

## Dependencies
None. Independent of #412 — this is correct behavior even once the OOM is gone.

## Risks
The retry counter is read by the wave supervisor's stall detector; a state-key
change must keep that read working or waves lose stall detection silently.

## Verification
`make verify` (includes the new regression test), plus one dispatched worker
against a deliberately memory-capped gate showing a single retry then a
reported blocker.
EOF
)"
```

Note what the canonical path bought: **Non-goals** kept #412 out of scope, **Risks** flagged a coupling the implementer would otherwise break, and **Verification** named a real command instead of "verified manually".

---

## Example 2 — External repo, strict issue forms

**Request:** "`ledger-cli` crashes on empty CSV input. File it upstream."

### Ownership

```console
$ uv run --no-project python .../ownership.py --repo octo-analytics/ledger-cli
{
  "classification": "EXTERNAL",
  "owner": "octo-analytics",
  "viewer": "you",
  "reason": "repo owner is neither the authenticated user nor an owned org"
}
```

You have WRITE on this repo as an occasional contributor. **That does not change the answer** — `viewerPermission` is not an input, and a maintainer bypassing the project's own conventions is the worst version of this mistake.

### Discovery

```console
$ gh api repos/octo-analytics/ledger-cli/contents/.github/ISSUE_TEMPLATE --jq '.[].name'
bug_report.yml
config.yml
feature_request.yml
```

`bug_report.yml` requires: `version` (input), `what-happened` (textarea), `repro` (textarea), `logs` (textarea, optional), and a `terms` checkbox. `config.yml` sets `blank_issues_enabled: false`. `CONTRIBUTING.md` requires the title prefix `[BUG]` and a minimal reproduction. Recent issues confirm: short, one repro block, no headings beyond the form's.

### The decision this forces

Blank issues are disabled and the form has required fields, so **`gh issue create --body` with a house body shape would be a violation, not a shortcut.** Two legal routes: fill the form in the browser, or reproduce the form's fields exactly as headings in the same order. The canonical structure supplies *content* only — Problem becomes `What happened`, Reproduction becomes `Steps to reproduce`. Everything with no home in the form (Scope, Non-goals, Risks, Acceptance criteria, priority labels, hierarchy links) is **dropped, not appended**.

```bash
gh issue create --repo octo-analytics/ledger-cli \
  --title "[BUG] Empty CSV input panics instead of exiting cleanly" \
  --body "$(cat <<'EOF'
### Version
ledger-cli 4.2.1 (homebrew), macOS 15.5

### What happened
Running `ledger import` against a zero-byte CSV panics with an index-out-of-range
in the header parser instead of reporting an empty-input error and exiting 1.

### Steps to reproduce
1. `: > empty.csv`
2. `ledger import empty.csv`

Observed: `panic: runtime error: index out of range [0] with length 0`
Expected: `error: empty.csv contains no rows` and exit code 1.

### Relevant log output
```
panic: runtime error: index out of range [0] with length 0
  ledger/internal/csvparse.headers(...)
```

### Terms
- [x] I have searched existing issues.
EOF
)"
```

Labels: `gh label list` shows only `bug`, `enhancement`, `question`. Apply `bug`; **do not** map a house priority onto a repo that has no priority family — triage is the maintainers' job.

---

## Example 3 — External repo, minimal guidance

**Request:** "`dotfmt` has no way to ignore a directory. Ask for it."

### Ownership

```console
$ uv run --no-project python .../ownership.py --repo tiny-tools/dotfmt
{
  "classification": "EXTERNAL",
  "owner": "tiny-tools",
  "viewer": "you",
  "reason": "repo owner is neither the authenticated user nor an owned org"
}
```

### Discovery

No `.github/ISSUE_TEMPLATE/`, no `CONTRIBUTING.md`, no `AGENTS.md`. `gh label list` returns GitHub defaults only. Recent issues are two to five sentences, no headings, and the maintainer answers within a day.

### The decision this forces

Standards are silent, so preferences fill the gap — but the gap-filling rule is **canonical minus anything that reads as imposed process.** Keep problem, current behavior, desired behavior, and a concrete acceptance sentence. Drop headings the host never uses, drop priority and hierarchy entirely, and match the observed length. A seven-section body with checkboxed acceptance criteria on a repo whose issues are one paragraph reads as a process demand, and it is the single most common way this skill can fail.

```bash
gh issue create --repo tiny-tools/dotfmt \
  --title "Support an ignore file or --exclude flag for directories" \
  --body "$(cat <<'EOF'
`dotfmt .` formats everything under the working directory, including `vendor/`
and generated output, and there is no documented way to exclude a path. Today
the workaround is to enumerate the directories to format, which breaks whenever
a new top-level directory is added.

A `.dotfmtignore` file (gitignore syntax) or a repeatable `--exclude <glob>`
flag would cover it — either shape works; the ignore file composes better with
pre-commit hooks.

Happy to send a PR if you tell me which of the two you'd prefer.
EOF
)"
```

Labels: `enhancement` (a real label in that repo's default set). No priority label, because the repo has no priority family.

---

## The one-line summary of all three

Same underlying content; the *shape* is dictated by the host every time. The canonical structure is the default only where you own the tracker — everywhere else it is a checklist of things to *know*, not a template to impose.
