# The wave PR — body and metadata standard (#897)

Companion to [SKILL.md](SKILL.md) step 6 and
[`merge-and-closeout.md`](merge-and-closeout.md). A wave ends with **exactly one
PR, `wave/<…> → production`**, and this is its shape.

## Why a template, when the other artifacts already had one

The wave PR is the densest thing a wave produces and the only artifact a human
actually reads — every other record (`WAVE-STATE.md`, `.wave/` logs, the wave
branch) is gone or unread by the time review happens. It was also the last wave
artifact with no template.

PR #884's body was good: phases, a worker-PR table, the counterbalance findings,
a deferred section, and one line disclosing that a database was destroyed during
the cutover. **Nothing required any of it.** The section most likely to be
dropped by the next supervisor is the incident disclosure, because it is the
only one that makes the wave look worse. That is exactly the kind of section a
template has to force rather than hope for.

## Metadata standard

| | |
|---|---|
| **Title** | `Wave <YYYY-MM-DD>-<slug>: <what it did>` |
| **Base → head** | `production` ← `wave/<YYYY-MM-DD>-<slug>` |
| **Label** | `wave` — the same label the wave issue carries |
| **Assignee** | the authenticated user (`--assignee @me`) |

**This template is for wave PRs only.** Ordinary feature PRs use the
repository's standard PR shape and do not carry wave provenance fields,
diagrams, or the `wave` label. The mechanical CI check still applies to every
PR from a `wave/*` branch; do not use that branch naming pattern for an
ordinary feature PR. For a direct, single-issue implementation, avoid a
`wave/*` branch; the CI contract requires wave-specific provenance and a
wave-shape diagram for every PR using that branch namespace.

The title repeats the wave name used by the issue, the branch, the worktrees and
the log keys, so one `grep` still finds every artifact of one wave. The `wave`
label makes `gh pr list --label wave --state all` the complete history of waves
ever run.

> **Assignee, not reviewer — and this is a mechanism, not a preference.** GitHub
> refuses a self review-request, and it fails *silently*:
> `gh pr edit <pr> --add-reviewer <the author>` exits 0 and prints the PR URL
> while attaching nobody (verified on PR #831 — `reviewRequests` stayed empty).
> A supervisor told to "request a review" would report success and leave the PR
> with no one on it. `--assignee` is the mechanism that works when the author is
> the human owner. Use `--reviewer` **only** when the PR author is somebody else.

```bash
make wave-pr-check BODY=<path> TITLE="Wave <…>: <what it did>"   # before opening
gh pr create --base production --title "Wave <…>: <what it did>" \
  --body-file <path> --label wave --assignee @me
make wave-pr-check PR=<n>                                        # after
```

**This is a gate, not advice** (#897). CI runs
`scripts/check_wave_pr_body.py` on every PR whose head is a `wave/*` branch:
required sections, a non-empty `Closes` list, the wave-issue reference, the
title shape, the `wave` label, and any template placeholder left unfilled.
`make wave-pr-check` is the same check, so a supervisor finds out before
opening rather than from a red check.

## Body template

````markdown
# Wave <YYYY-MM-DD>-<slug> — <what this wave did, in a human-readable phrase>

![wave shape](https://github.com/<owner>/<repo>/blob/<merge-or-branch-sha>/docs/architecture/waves/wave-<YYYY-MM-DD>-<slug>.png?raw=1)

<Two or three sentences. The theme, and what is different about the repo now
that it merged. Written for someone who was not here.>

| | |
|---|---|
| **Wave issue** | #<n> |
| **Supervisor** | <harness> · <model> |
| **rpw-published** | <installed version> · <drift verdict from `make plugin-check DEEP=1 FETCH=1`, e.g. `current — every shipped file matches origin/production`> |
| **Started → ended** | <ISO-8601 UTC> → <ISO-8601 UTC> (<duration>) |
| **Workers** | <n> dispatched · <n> merged · <n> abandoned |
| **Base** | `production` @ `<fork-point-sha>` |

## Release notes

<What changed, in plain language, for someone who *uses* this repo rather than
built it. Two to five bullets. Not a diff summary — an outcome summary.>

## Issues closed

| Issue | | Worker PR | Notes for review |
|---|---|---|---|
| [#<n> <title>](<url>) | ✅ | #<pr> | |
| [#<n> <title>](<url>) | ‼️ | #<pr> | <the surprise, in one line> |

## Issues created

| Issue | | Why it exists | Notes for review |
|---|---|---|---|
| [#<n> <title>](<url>) | ⚠️ | counterbalance / retro / worker finding | |

## Incidents & risk

**REQUIRED whenever any occurred; omit the section entirely when none did.**
Data loss, a production service interruption, a security finding, a destructive
command run outside the repo, or anything a reviewer would be angry to discover
later. One line each: what happened, what was lost, what was filed.

## Verification

<What actually ran. Name each check and its result — `make verify` exit 0;
`launchctl kickstart <agent>` then a 200 from `<endpoint>`; member gates by
name. Never a hand-wave: "verified" and "tested" are not checks.>

## Deferred

<What was cut from this wave and why — scope reduction is a decision, and it is
only visible if it is written down. Link the issue carrying each leftover.>

## Agent notes

<Optional. Anything the supervisor thinks is worth a human's attention:
proposals for this template, a pattern worth codifying, a rule that fought the
work. Free-form on purpose.>

---

## Closes

Closes #<a>, Closes #<b>, Closes #<c>
````

## Status emoji — fixed, so it means the same thing every wave

| | Meaning |
|---|---|
| ✅ | landed as specified |
| ‼️ | surprise or deviation — a human should look at this one |
| ⚠️ | landed, with a caveat worth knowing |
| ⏭️ | deferred or abandoned |

## Section rules

- **`## Closes` goes last, under a rule.** It is wiring, not reading material —
  a human reviewing a wave should never have to scroll past it to reach the
  substance. Bottom placement costs nothing: GitHub honours `Closes #N` anywhere
  in the body.
- **It is still not optional.** Worker PRs into a non-default branch do not
  auto-close their issues, so this list is the only thing that does. An issue
  promoted to `production` mid-wave closes on its own PR and must be **absent**
  here, or it closes twice on the wrong event.
- **The wave-shape diagram sits at the top of the body** (#789) — above the
  prose and above the provenance table, so the wave's shape reads at a glance.
  That placement is this template's business; everything else about the diagram —
  where the artifact lives, how many files it is, how to embed it and what
  `make wave-pr-check` enforces — is specified ONCE in
  [`merge-and-closeout.md`](merge-and-closeout.md) and is not restated here
  (#1755).
- **Worker PR links live in the Issues-closed table**, satisfying the
  [`merge-and-closeout.md`](merge-and-closeout.md) contract without a second
  list. The per-worker reviews are the real review; these links are what keeps
  history navigable after the squash collapses them.
- **`## Incidents & risk` is the section a template exists to force.** Write it
  before the release notes, not after — a supervisor that has just finished a
  wave is exactly the reader most inclined to leave it out.
- **The details table is provenance nobody can reconstruct later.** The
  supervisor's model, the plugin version it ran, and the real durations all die
  with the worktree. Read the version **and its drift verdict** from
  `make plugin-check DEEP=1 FETCH=1` at wave start — never from memory, and
  never from the plugin cache directory name, whose content can disagree with
  `origin/production` (#1252). That command prints `installed_version` plus a
  content-match verdict (`current — every shipped file matches
  origin/production`), so the row is one command instead of an inference.
