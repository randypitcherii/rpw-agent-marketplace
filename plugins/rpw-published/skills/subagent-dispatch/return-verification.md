# Verifying a worker's return — ground truth before "done" (#914)

Companion to [SKILL.md](SKILL.md) section 6. Read this when a dispatched agent
comes back claiming it produced something: an issue, a commit, a file, a PR.

## The failure this exists to prevent

Across nine reviewed omnigent sessions, **three dispatches reported success having
done nothing observable**:

1. One emitted a single preamble line and never called `gh issue create`.
2. One finished its code, left it uncommitted, and never mentioned it.
3. One batch came back as `produced no output`.

Every one was caught by an ad-hoc check the coordinator happened to think of —
which means the ones nobody thought to check were reported to the user as done.

Part of the mechanism is upstream and not ours to fix: `omnigent-ai/omnigent#4448`
— when a sub-agent name does not resolve, the runner silently substitutes the
parent's spec, and the substituted child reports success. `omnigent-ai/omnigent#4447`
covers 502s under concurrent fan-out producing the same phantom-completion
signature. **Neither is under our control, which is exactly why the dispatch-side
check has to exist regardless.** A future runner fix does not retire this page;
verification is cheap and a wrong "done" is not.

Note what this is *not*: [`dispatch-liveness.md`](dispatch-liveness.md) is about
telling a stalled agent from a working one, and its discriminator (for in-process
subagents, a `task-notification` with `status=completed`) proves only that the
agent **stopped**. Liveness and delivery are separate questions. A completed
notification plus a confident summary is still zero evidence that the artifact
exists.

## Scope — durable artifacts only

Verify when the dispatch claimed something that outlives the conversation: an
issue, commit, branch, file, PR, or posted comment.

**Exempt:** read-only research and debug dispatches, whose report *is* the
deliverable. They get one weaker obligation instead — a return of `produced no
output`, or a report with no file/URL citations, is a **failed dispatch**, not a
finding to pass along.

Keeping the requirement to durable artifacts is deliberate: a verification round
trip on every trivial delegation would make small delegations not worth doing.

## The checks, by artifact class

Each command is written the way you must actually run it. **The scoping is not
optional** — an unscoped check is how you produce a false "unverified", and a
verification step that cries wolf gets ignored within a week.

### Issue filed

```sh
gh issue list --repo <owner>/<repo> --search "<distinctive title words> in:title" \
  --state all --json number,title,url
```

- `--repo <owner>/<repo>` explicitly: `gh` otherwise resolves the repo from the
  worker's cwd or yours, and a worker in a worktree of a different remote files
  into a repo your unscoped check never searches.
- `--state all`: a worker that filed and closed an issue still filed it.
- `in:title` against **distinctive** words from the title you asked for. A generic
  search term matches a pre-existing issue and verifies the wrong thing — worse
  than no check.
- **Pass condition:** a JSON array with a number you can quote to the user.

### Commit landed

**This block is canonical (#1025).** SKILL.md's table points here rather than
re-spelling it; the two copies had already drifted apart around the `--` clause.

```sh
git -C <abs-worktree-path> log --oneline <base-branch>..<worker-branch> -- <scoped-paths>
git -C <abs-worktree-path> status --porcelain
```

- **`<scoped-paths>` = the paths the dispatch fenced the worker to**, verbatim from
  the brief's file-ownership list (`plugins/rpw-published/skills/wave-supervisor/`,
  `libs/rpw_config/`, …), space-separated after the `--`. It is the difference
  between "a commit exists" and "the commit you asked for exists": a worker that
  committed only outside its fence is a found artifact **and** an ownership
  violation, which is the pair this scoping exists to catch. If the dispatch fenced
  nothing, drop the `--` clause and say in your report that scope was unverifiable
  — never guess a path, because a wrong path is how you produce the false
  "unverified" this file's opening rule warns about.
- `git -C <abs-path>` and never `cd` — parallel Bash calls share a cwd, so a `cd`
  in one call silently reports on another worker's tree (same trap as the #135
  isolation assertion in SKILL.md section 6).
- The **range** `<base>..<worker-branch>` matters: bare `git log` shows commits
  that were already there before the dispatch.
- `status --porcelain` is half the check, not a bonus. Failure mode 2 above was
  finished code sitting uncommitted; a `log` that finds an earlier commit passes
  while the actual work is unsaved. **Empty porcelain output is the pass
  condition.**
- Landed-on-the-branch ≠ pushed. If you asked for a push, add
  `git -C <abs-path> log --oneline <remote>/<worker-branch> -1`.

### File written

```sh
test -s <absolute-path> && wc -l <absolute-path>
```

- **Absolute path inside the worker's worktree.** A relative path resolves against
  your cwd; finding the file in your own tree proves nothing about the worker's.
- `test -s` (non-empty), not `test -f`: a created-then-never-written file is the
  exact shape of a worker that started and died.
- For an edit rather than a new file, verify the *content*:
  `grep -c "<expected marker>" <absolute-path>`.

### PR opened

```sh
gh pr view <branch-or-number> --repo <owner>/<repo> \
  --json number,url,state,baseRefName,headRefName
```

- Check `baseRefName` and `headRefName` against what you asked for. A PR that
  exists against the wrong base (`production` instead of the wave branch) is a
  found artifact and a failed dispatch at the same time.
- **`headRefName` is a bare branch name even from a fork** — it never carries an
  `owner:` prefix, so compare it to the branch you asked for verbatim. Add
  `headRepositoryOwner` to the `--json` list when you need to know *which* repo
  the head lives in; do not infer a mismatch from the missing prefix.
- `state` must be `OPEN` unless you asked for a merge.
- **Pass condition:** a URL you can quote.

### Out-of-fence tests still pass

**Run it, don't reason it (#1086).** "Out-of-fence tests untouched … still pass"
is a claim about code you did not open, and the only way to make it is to
execute the suite **in the environment where the new gate fires**. PR #1031
asserted exactly that by reasoning and shipped a fail-closed gate that had never
once failed closed: the new `land` lease guard (`scripts/wave_worker.py`) is
reached only when a `WAVE-STATE.md` exists — true in a supervisor worktree,
false in CI and a fresh clone — so the integrated `make check` failed with
5 × `AssertionError: default_lease_checker shells out` after 27 green worker PRs.
Name the command, the environment, and its exit code; a reasoned "should still
pass" is `unverified`, not a pass.

## Require the identifier, not a prose summary

Verification is cheap only when the worker hands you the lookup key. End every
artifact-producing dispatch prompt with the ask:

```
Return, as the last line of your final message, the artifact's identifier:
the issue number, the commit sha, the PR URL, or the absolute file path.
A prose summary without an identifier does not count as a result.
```

A return that summarizes work and names no identifier is **unverified by
default**. You may still try to verify it by search — often you can — but you
never upgrade prose to "done". Note which side the failure was on: no identifier
means the return was unusable, whether or not the artifact turns out to exist.

## Two strikes, then do it yourself

The stopping rule, from a coordinator who worked it out the expensive way: *two
failed dispatches is the point where delegation costs more than it saves.*

| Attempt | What you do |
|---|---|
| 1 fails verification | Re-dispatch **once**, quoting the exact check that failed and its output, and repeating the identifier ask. |
| 2 fails verification | **Stop delegating this unit of work.** Do it directly, inline, yourself — *except* for a fenced wave worker, which gets the carve-out below. |
| 3rd attempt | Is *your* attempt — never a third **undiagnosed** dispatch. If doing it directly is also blocked, stop and report blocked to the user, naming both failed checks. |

Two failures on the *same unit of work* is the trigger, and the counter does not
care what you changed between them (model, prompt, agent type) — those are
re-rolls of the mechanism that already failed. Re-dispatching a third time on the
same undiagnosed failure is the behavior this rule exists to stop: it burns
another round trip on that mechanism, and it is how a phantom completion becomes
three phantom completions.

Two things are **not** strikes, and neither resets the counter — they never
incremented it:

- **A dispatch that never ran.** An environment death — VPN drop, supervisor-runner
  death, spawn-flag drift (#498) — produced no return to verify, so there is
  nothing to strike. Relaunch it under the salvage protocol
  ([`wave-supervisor/supervision.md`](../wave-supervisor/supervision.md)).
- **A relaunch carrying a newly diagnosed cause** — a *specific* failure you can
  name that the earlier dispatches did not know about. That is a narrowed unit of
  work, not a re-roll of the same mechanism, and it is the only thing that buys a
  third dispatch. It has a price (below), and it applies to any dispatch; what is
  wave-specific is only the terminal state.

### Wave workers — park, never do it yourself (#1021)

A **wave worker** (the `wave-supervisor` skill: one issue, one fenced worktree, a
brief naming the files it owns) inverts row 2. The generic terminal state —
*do it yourself* — is **forbidden** here, not merely discouraged: a supervisor
implementing a fenced issue inline, in the worker's worktree, breaks **One
worktree, one worker** (#827) and the file-ownership fencing that is the only
reason the parallel cohort is safe. The wave terminal state is **park the issue
and escalate**, which is what
[`wave-supervisor/supervision.md`](../wave-supervisor/supervision.md)'s salvage
protocol already ends in.

That leaves the question the two skills used to answer in opposite directions:
*how many times may a supervisor relaunch one worker?* **The strike is an
undiagnosed repeat, not a dispatch count.**

| Situation | Strike? | Do |
|---|---|---|
| The dispatch never ran (runner death, VPN drop, spawn-flag drift) | **no** | relaunch as `.r<k>` — salvage protocol, not this table |
| The return failed verification and you have **no** new cause to name | **yes** | the second of these is the stop: park the issue and escalate. Never inline supervisor work |
| The return failed and you diagnosed a **new, specific** cause | **no** — it is a narrowed unit of work | one relaunch, paid for as below |

A diagnosis is currency only if it is **written down and handed over**: the
failing run's identifier, the error verbatim, the root cause, and the prescribed
fix, left in the worker's worktree (`FOLLOWUP.md`) and quoted in the relaunch
prompt. Each diagnosis buys **exactly one** relaunch and cannot be spent twice —
if the prescribed fix itself fails verification you are back at row 2 with nothing
new to name, so park and escalate. A relaunch whose prompt says "try again" is an
undiagnosed repeat wearing a `.r<k>` filename.

**Why not a hard `.r2` cap:** wave `2026-08-11-backlog`, worker #841 needed three
and was right to. Dispatch 1 (omnigent child) died with the supervisor's runner —
nothing committed, no strike. `.r2` delivered PR #1054, green locally and red on
CI. `.r3` carried a `FOLLOWUP.md` naming the run id, the assertion error, and the
root cause (`/bin/python` exists on `ubuntu-latest`, not on macOS); the worker
fixed it in one commit. Three dispatches, **zero undiagnosed repeats**. Under a
literal count cap the supervisor would have had to implement that fix itself,
inside the worker's worktree — the exact #827 violation the cap was meant to
prevent. Count is the wrong variable; a named cause is the right one.

## Open the return with the five-state status line

A mid-run "still going" must not read like a final "done" — that is how an unverified
claim gets skimmed as success. Open every return with the house status line. A `DONE`
return must quote the identifier the checks above confirmed; a return that only *claims*
success is `NEEDS YOU`, not done. States, shapes, and examples:
[`../communication/references/status-updates.md`](../communication/references/status-updates.md).

## Report unverified as unverified

If a check fails, or you could not run it, that is what the user hears:

```
unverified — `gh issue list --repo <owner>/<repo> --search "dispatch ground truth in:title" --state all`
returned an empty array. The worker reported filing the issue; no issue exists.
```

Rules for that report:

- Name the **check that failed**, verbatim, with its output. "Could not verify" on
  its own gives the user nothing to act on.
- **Never report it as done**, and never bury it in a summary of what the worker
  said it did.
- Never silently re-dispatch to make the problem go away before the user sees it —
  one retry is allowed (the table above), and the retry is reported too.
- Verified is equally specific: quote the identifier you confirmed (`#914`,
  `0e4000e`, the PR URL), not "verified".
