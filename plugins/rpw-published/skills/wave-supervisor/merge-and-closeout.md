# Merge-back and close-out

Companion to [SKILL.md](SKILL.md) steps 5–6 (#531).

## Wave branch topology

Workers branch **off the wave branch** and PR **into it**. Three things follow,
and they are why the topology is not negotiable:

- `production` never sees partial state;
- abandoning a wave is deleting one branch;
- the #480 auto-bump never fires mid-wave, so no bot moves the branch under a
  running worker.

Worker PRs into a non-default branch do **not** auto-close their issues — the
single wave PR's `Closes` list is the only thing that does (below).

If `production` moves mid-wave (a hotfix), the supervisor merges
`production` → wave branch **ONCE**. Workers never track `production` directly.
**What triggers that once — the checkpoint diff against in-flight fences (#1153) —
is in [`dispatch-mechanics.md`](dispatch-mechanics.md);** deferring it to close-out
cost four hand-resolved conflicts and one real defect on `2026-08-17-llm-proxy`.

## Counterbalance: periodic-review defaults (#374)

Waves optimize velocity; `periodic-review` is the standing counterweight —
read-only lenses catching cross-worker defects per-PR review cannot see. Invoke
the skill; never duplicate its procedure. Defaults:

- **Cadence** — every 5 wave-branch merges, plus always at close-out.
- **Scope** — incremental since the last pass's marker; the first pass runs from
  the fork point.
- **Enforcement** — advisory. Ranked issues, never a merge gate. Same-wave
  regressions are folded in rather than filed.

Its tally joins the checkpoint tally, the wave issue, and the wave PR body.

### A fold-in is code and gets a reader (#785)

A **counterbalance fold-in** — the supervisor's own direct commit to the wave
branch — is the one code path in a wave with no second reader. It is also
written in the worst conditions: mid-wave, attention split across N workers, on
a surface the supervisor did not build. Wave `2026-08-02-backlog`'s three
fold-ins produced three defects, each caught by the *next* pass rather than at
write time:

- a `setsid` call (a binary macOS does not ship) and a `RUNNER_TEMP` reference
  that made the CI filter unrunnable locally;
- an eviction path that validated a **PID** and then signalled a process
  **GROUP** — for a non-leader holder, the script's own documented expected
  case, that kills a bystander group, leaves the incumbent alive, and starts a
  second instance: exactly the state the supervisor exists to prevent;
- a hard-coded log directory the plists no longer used.

**Two of the three were in a published skill** (`automation-standards`), so they
would have mirrored publicly. Three-for-three is a rate, not an accident.

So: **a fold-in is code and gets a reader.** In preference order:

1. **Executable-code fold-ins go to a worker**, like anything else — unless the
   surface is genuinely unowned *and* the change is a one-liner.
2. **When the supervisor does fold in directly, the next pass's scope explicitly
   includes the previous fold-in commits.** Wave 2026-08-02 arrived at this by
   accident, and it is what caught all three defects.
3. **Prose and doc fold-ins stay inline**; a behavioral change takes the worker
   path.

## Why merges are serialized

Worker PRs land in the wave branch **one same-plugin PR at a time**, refreshing
the next against the moved wave branch before merging it. Intra-wave conflicts
are cheap — every worker shares the wave branch as its base and no bot touches
the branch mid-wave — but only if exactly one PR is being integrated at a time.
Rebase still-running workers onto the advancing wave branch as merges land, so
their eventual PR is already current.

**Tell a live multi-PR worker to rebase — and do not pass `--delete-branch`
while a worktree still holds the branch (#1090).** After merging PR *n*, that
worker must `git fetch origin` and rebase onto the updated wave branch before
opening PR *n+1*; a squash-merge deletes the head branch and freezes the
merge-base at the fork commit, so an unrebased second PR re-shows the merged
content in its three-dot diff (PR #1060 carried +1245/−18 of already-merged
#1019's work). `gh pr merge --delete-branch` also *fails* while a worktree still
holds the branch — the merge itself succeeds — so drop the flag; the repo already
sets `deleteBranchOnMerge` and the branch is pruned at teardown.

Cross-plugin PRs can't collide and may merge on arrival.

**`make wave-merge PR=<n> [ISSUE=<n>|KEY=<key>] REPORT_FILE=<report.md>` is the
serialized merge as one verb (#2210)** — run it per PR, in the foreground. It
guards the lease, checks the base against `WAVE-STATE.md`'s wave branch and the
head is a `worker/*` branch, refreshes a head missing the wave tip with `gh pr
update-branch` and **waits** for the new head (`NO_REFRESH=1` skips that for a
cross-plugin PR merging on arrival), waits on the check runs of the **exact head
SHA** with each `|`-alternative of `CHECKS=` (default `Member checks|Repo gate`)
matching a green run, squashes with `--match-head-commit`, then lands the report
*before* recording `merged` (#2422) and appends the merge-log line. Both commits
in the "contains the tip" test are named by SHA, never via `FETCH_HEAD`. Exit 0
merged · 1 red · 2 refused (nothing mutated) · 3 lease · 4 pending at timeout · 5
unprovable (`gh`/`git` did not answer — never read as green) · 6 merged but not
recorded (run the printed command). A keyless `wave-worktree` worker lands and
records by `KEY=` on `wave-land`/`wave-record-status`/`wave-record-session`
(#2510).

**Review before merging — not a rubber stamp.** On skill-authoring PRs the
`description:` frontmatter is the model-routing mechanism (#268): a changed
trigger phrase changes when the skill fires, so read it as behavior.

**A green claim naming a gate target is not evidence (#1086).** Before merging,
read the PR body for **command + exit code per check**: `make <member>-test`
hides 2–5 commands, and PR #1060 reported `make high-voltage-test` green having
run only its `pytest` half, never the `ruff check`/`format --check` half. Ask
which commands ran — "tests pass" answers a different question.

**Confirm the base before each merge** — `gh pr view <pr> --json baseRefName` must
print the wave branch. `gh pr merge` honors the PR's own base, so a wrong-base PR
is executed here, not rejected: merging one whose base is `production` lands a
single worker's slice on `production` mid-wave and fires the #480 auto-bump. Intake
already gates this ([`supervision.md`](supervision.md)); this is the backstop for a
PR that was edited after triage (#1023).

**Revalidate the lease before each merge** — `make wave-guard`, exit 3 means
stop (#823). A merge is the most expensive mutation a de-throned supervisor can
make: on 2026-08-05 the losing supervisor merged a PR the real owner had declared
dead. Serialization only holds if there is one serializer.

### Wait on the run for the head SHA, never on `statusCheckRollup` (#2061)

**A rollup with nothing in progress is not a green.** Pushing a commit cancels
the old run *before* the new one registers, and in that gap the rollup holds no
in-progress checks — "nothing running" reads as "done". Measured on PR #2042
(wave `2026-09-28-skill-learner`): a rollup loop exited `mergeState=CLEAN`
**20 s** after fold-in `8c06b091` was pushed, while `gh run list` still showed
the new run `queued` and the old one (`59f4b61f`) `cancelled`. The real run went
green 5 min later; merging on the false green would have landed an unverified
commit.

So key the wait on the PR's `headRefOid`. `gh run list --commit <SHA>` filters
runs by commit (gh 2.102.0, `gh run list --help`: `-c, --commit SHA  Filter runs
by the SHA of the commit`), which also drops the cancelled run of the previous
head:

```bash
SHA=$(gh pr view "$PR" --json headRefOid --jq .headRefOid)
# 1. until at least one run exists for this SHA, 2. until every one is completed
until runs=$(gh run list --commit "$SHA" --limit 50 --json name,status,conclusion) \
  && [ "$(jq length <<<"$runs")" -gt 0 ] \
  && jq -e 'all(.status == "completed")' <<<"$runs" >/dev/null; do
  sleep 30
done
# 3. read each conclusion — every workflow for the SHA must pass
jq -r '.[] | "\(.name): \(.conclusion)"' <<<"$runs"
jq -e 'all(.conclusion == "success" or .conclusion == "skipped")' <<<"$runs"
```

**One SHA can have several workflows, and they register seconds apart.** The
loop waits on *all* runs it sees, but a second workflow can appear after the
first completes; if the PR's branch triggers more than one workflow (the
`pr-to-production__*` set does), check the run count matches before trusting the
verdict. A parked `action_required` run is `completed` with a non-success
conclusion, so step 3 fails it rather than passing it (#509 below). Re-read
`headRefOid` right before merging: a push after the loop exits makes its verdict
stale.

### A green root gate proves ONE platform — confirm Linux before merging (#1750)

**The serialized root gate runs on the supervisor's laptop, so it says nothing
about Linux.** Every root gate in a wave runs on one platform by construction,
which makes a Linux-only defect structurally invisible until an unrelated PR's CI
surfaces it — where it reads as *that PR's* failure.

Measured: a `ps -axo` that Linux truncates to the screen width shipped on
`wave/2026-09-12-wave-tooling` through PR #1744. It passed the worker's member
gate (macOS) **and** the supervisor's serialized root gate (macOS), then went red
on #1746 — a PR whose diff never touched the failing code. Attribution cost a
full diagnosis pass before the merge could proceed. The mutex worked perfectly;
single-platform coverage is what failed.

So the local gate is not the branch's verdict. `make wave-gate` now names the
platform it covered and the one it did not, and one command reads the other:

```bash
make wave-platform-check BRANCH=<wave-branch> HEAD_SHA=$(git rev-parse HEAD)
```

| Verdict | Exit | What it means |
|---|---|---|
| `green` | 0 | Linux passed **on that commit**. Merge. |
| `red` | 1 | **The branch's failure, not the next PR's.** Diff the branch before attributing it. |
| `pending` | 2 | Linux has not finished. Wait; a local gate cannot substitute. |
| `stale` | 2 | Newest Linux run is on an earlier commit — this one has no coverage. |
| `green-by-tree <run> <commit>` | 0 | No run on the head, but a completed Linux run passed on a commit with the **same tree** (#2062). |
| `red-by-tree` | 1 | That same-tree run failed — the same bytes, so the same failure. |
| `absent` | 2 | No run on the branch and no same-tree run. Parked `action_required` runs look identical to no CI (#509 above). |
| `unknown` | 2 | A `gh`/git read did not answer. Unprovable, never `absent` ([`unasked-is-not-no.md`](../automation-standards/unasked-is-not-no.md)). |

**Tree identity** (#2062): a wave branch that was never a PR head has no run of
its own, yet after an up-to-date squash-merge its tip shares a tree with the
merged PR's head, which ran the full `ubuntu-latest` matrix. With no run on
`HEAD_SHA`, the check compares `HEAD^{tree}` against the commits of the branch's
last 20 runs and the heads of the last 20 PRs based on it (`gh pr list --base`),
then reads runs only for tree-equal commits. A different tree never counts.

`red` is 1 and everything unproven is 2 on purpose: "Linux says no" and "Linux
has not said" are different decisions, and collapsing them hides the second.

**Run it at close-out, and again after any fold-in touching a process, path or
subprocess surface** — those are the changes whose defects are platform-shaped.
`HEAD_SHA` is what makes it honest: a green run on an earlier commit reports
`stale`, never green.

Append each merge to the `WAVE-STATE.md` merge log as it happens (#569), through
the guarded path so the same check covers the write:

```bash
make wave-state-append SECTION='Merge log' LINE='- <ISO-8601 UTC> — PR #<x> (#<n>) merged'
```

Close-out lines are long prose full of inline code spans. Write them to a file
and use `LINE_FILE=` — the payload is appended byte-verbatim either way (#1104),
and a file is the natural home for a multi-sentence line:

```bash
make wave-state-append SECTION='Events' LINE_FILE=/tmp/closeout-line.md
```

## Teardown as issues complete

Issues are NOT closed per-worker — close-out happens via the final wave PR. As
each worker finishes and its PR has merged: close its session, then prune its
worktree and branch. Order matters, because archiving can delete the bound worktree
(`git worktree remove --force`, branch kept, #2571): anything uncommitted in it, and
the gitignored `WORKER-BRIEF.md`, goes with the close. Teardown order and the guard:
`dispatch-launch`'s `session-lifecycle.md`. A failed `git push --delete` on a remote
branch usually means the repo auto-deleted it on merge — not an error.

**The supervisor's own session closes last, after retro mining** (close-out step 4)
— its worktree holds `WAVE-STATE.md` and `.wave/`, both gitignored and both
retro-miner input. Closing it first deletes the wave's record.

**Close and reap in one step** (#2427): `sys_session_close` can leave a
native-harness child's `tmux` + harness running at `ppid 1` (5 of 9 closes at
wave #2406, claude **and** codex). `make wave-close-children` closes each session
through `session-close.sh`, then reaps whatever still carries its
`@omnigent-conversation-link` tag — keyed on the conversation, never on cwd:

```bash
make wave-close-children SESSIONS='<id> <id>…'                          # dry run: guard + tagged processes
make wave-close-children SESSIONS='<id> <id>…' WAVE_CLOSE_ARGS=--kill   # close, then reap
```

It **refuses** a session whose bound workspace has uncommitted or unpushed work, or
a gitignored wave record (`WAVE-BRIEF.md`, `WAVE-STATE.md`, `WORKER-BRIEF.md`,
`.wave/`) (exit 4, `outcome=refused`) — archiving a bound session has deleted its
worktree before. Push or discard that work; `--force` overrides, and passes
`--force` through to `session-close.sh`, which runs the same guard. The reap is the sweep's
membership-gated kill, so the outcomes read the same (`clean` / `unprovable` /
`unkillable`). Still run the worktree sweeps below — this covers what carries the
tag, not a process that escaped it.

## Process sweep — REQUIRED before and after teardown (#644)

**Deleting a worktree does not kill what is running in it** — the #644 incident,
told once in [`load-harness-safety.md`](../subagent-dispatch/load-harness-safety.md).

Sweep once per wave worktree, **before** removing it and again after the last
teardown — and that list **includes the supervisor's own worktree** (#2295).
An Omnigent child created with no `workspace` inherits the parent's cwd, and
closing it (`sys_session_close`) tombstones the session but leaves its
claude-native `tmux` + harness running. Wave #2276 closed 10 children; the
worker-worktree sweeps reported clean, and only the supervisor-worktree sweep
found 9 survivors at `ppid 1` (one `tmux … new-session … claude-home-unattended`
per claude-native child, each tagged `@omnigent-conversation-link`). Run it
after closing the child sessions:

```bash
for wt in <supervisor-worktree-path> <worker-worktree-paths…>; do
  make wave-sweep WORKTREE="$wt"   # 0 clean / 1 survivors / 2 UNPROVABLE (#1785)
done
uptime   # load average should be back near idle for this machine

# Second signal, for a harness whose argv no longer names the worktree. This one
# needs a readable process table, and `/bin/ps` is DENIED in the sandbox waves
# run inside (#1785) — when it errors, say the CPU sweep was NOT run. Silence
# from a denied `ps` is not an idle machine; `uptime` above is.
ps -axww -o pid,ppid,etime,%cpu,command | awk '$4 > 50 {print}' | grep -v grep
```

Any hit is a **loud failure, not a note**: report it in the close-out with the
PIDs, reap it with the sweep's own kill mode, and file a finding issue against
the worker's brief. Never declare a wave done with a survivor outstanding — a
leaked loop outlives every artifact that could explain it.

```bash
make wave-sweep WORKTREE="$wt" WAVE_SWEEP_ARGS=--kill   # 0 reaped / 3 UNKILLABLE
```

**Do not hand-roll `kill -- -<PGID>` / `kill -9 <pid>` here** (#2005). Those forms
do work on this host, but their exit codes are not evidence: a supervised harness
respawns its child under a new pid, so the signal exits 0 and the next read still
matches. And the group form is the wave 2026-08-02 defect above, waiting to
happen again: a pgid here is **not** a per-worktree container. Measured on this
host, one supervisor Bash call put 32 processes in a single pgid — its own shell,
one worker's `claude -p`, and that session's whole MCP fleet — of which exactly
one referenced the worktree being swept. The kill mode signals a survivor's
process group **only when every live member of that group is itself a survivor**,
falls back to per-pid otherwise (naming the group it declined and why), escalates
SIGTERM to SIGKILL only after **polling the table for up to 2s of grace**, and
**re-reads the table after every pass** — and when something outlives that, it
says `outcome=unkillable` (exit 3) instead of reporting success. Treat
`unkillable` exactly like `unprovable` below: report it verbatim, and do not
remove the worktree on its strength.

Two lines in its output change what a `clean` means, so read for them:

- **`N sibling-path near-miss(es) ignored`** — a tree whose path merely *contains*
  the swept one (`<worktree>-metadata`) was spared. Expected when sibling
  worktrees are live; a near-miss count where you expected survivors means the
  `WORKTREE=` you passed was mistyped.
- **`group signalling was SKIPPED for N target(s)`** — for each of those targets
  the sweep was blind in one of two ways: a group's membership could not be read,
  or the survivor's own pgid could not be read. Either way it sent a pid signal
  instead of a group one. A pid signal reaches the survivor, not its children, and a child whose argv
  omits the worktree path is invisible to the confirming read. Do not upgrade
  that `clean` to "the worktree is empty" — re-sweep, or escalate.

Neither is a failure and neither changes the outcome word; both narrow what it
proves, which is why they print beside it rather than in the per-pid log.

**And never declare it done on `outcome=unprovable` either** (#1785). A sweep
that could not read the process table has ruled nothing out, so recording it as
a clean one is how this checklist stayed satisfied for months while `/bin/ps`
was denied and no sweep ran at all. Report the unprovable result verbatim in the
close-out, name the worktrees it covered, and do not remove them on its
strength.

## The single wave PR

The wave ends with **ONE PR `wave/<...> → production`** through the normal CI
gate (`make verify` + secret scan). The #480 post-merge auto-bump fires after
that squash, exactly once — which is why nothing may touch `production`
mid-wave.

**Body and metadata: [`wave-pr-template.md`](wave-pr-template.md) (#897).** It
carries the section list, the fixed status emoji, and the title / `wave` label /
assignee standard — including why the assignee is the mechanism and a
self-`--add-reviewer` is not (it exits 0 and attaches nobody).

Two rules from that template are contracts, not formatting:

- the full `Closes #a, Closes #b, …` list — worker PRs into a non-default branch
  do not auto-close their issues, so this list is the only thing that does;
- a link to every constituent worker PR (the template puts them in the
  issues-closed table). The per-worker reviews are the real review; the links
  are what keeps history navigable after the squash-merge collapses them.

### The wave-shape diagram — a required close-out artifact (#789)

The wave PR body carries a diagram of the wave's shape at the top. A bulleted
list of 29 links cannot show which issues formed one arc, what the review loop
produced, or where the wave's own process broke; a picture can.

- **Lives at** `docs/architecture/waves/wave-<wave-name>.{html,png,qa.json}` —
  all three committed on the **wave branch**, so they survive the squash; never a
  PNG alone (`project-readme` convention, #674). `<wave-name>` is the wave name
  (`2026-08-02`, or `<YYYY-MM-DD>-<slug>` when the name carries a slug), so waves
  accumulate a visual changelog.
- **Embedded at the top of the wave PR body** by absolute `blob/<sha>/…?raw=1`
  URL, never by repo path: a PR body is not rendered in repo context, so a
  relative path renders as nothing at all (PR #937). `raw.githubusercontent.com`
  is not the alternative — on a private repo it needs a token and 404s in a
  browser, while a `github.com` blob URL rides the reader's own session.
  `make wave-pr-check` fails a relative image target, and the wave PR gate
  requires the diagram. Body placement:
  [`wave-pr-template.md`](wave-pr-template.md).
- **Repoint the URL after the squash lands (#1759).** At authoring time the only
  SHA available is a **wave-branch** commit, and the wave branch is deleted at
  merge — that commit then survives only through `refs/pull/<n>/head`, a ref
  nothing in this repo guards. So the URL is durable only after step 5b below
  rewrites it to the squash commit on the default branch. Closing wave
  2026-09-12 this was done by hand, and nothing asked for it.
- **This section is the one owner of that spec (#1755).** `wave-pr-template.md`
  and `wave-state-template.md` point here; they do not restate the path, the
  three-file rule or the embed rule, because three copies of one rule drift.
- **Reference instance:**
  `docs/architecture/waves/wave-2026-09-12-wave-tooling.{html,png,qa.json}` —
  copy its shape, not its content.

Editorial rules that made that instance readable:

- **Group by theme, not by cohort.** Cohort boundaries are a scheduling artifact
  (which file surfaces happened to be free); themes are the shape of the work.
- **Draw the review loop as a stage, not a cycle.** Fold-ins do land back on the
  wave branch and filed issues do return to the backlog — but back-edges are the
  top cause of an unreadable diagram, so state those in prose instead.
- **Anchor on the wave branch** — the node everything converges on.

The `diagram` skill produces the artifact and owns its format, theme and QA
gate. Invoke it; do not restate its rules here. Choosing the themes is editorial
judgment, which is why this is not generated automatically — the same conclusion
#715 reached about auto-generating agent diagrams. One diagram per wave, never
per worker PR.

### Zero checks on the wave PR = parked runs, not slow CI (#509)

`statusCheckRollup: []` together with `mergeStateStatus: UNSTABLE` is the
signature of workflow runs parked in `action_required`: GitHub creates the run
record but never dispatches it, and the PR page shows **nothing at all**. "CI is
slow" and "CI never started" are indistinguishable from the PR, for humans and
supervisors alike — PR #500 stalled ~7 minutes on exactly this.

If the wave PR still shows zero checks ~2 minutes after opening:

```bash
gh pr view <pr> --json statusCheckRollup,mergeStateStatus   # confirm the signature
gh run list --branch <wave-branch> --limit 20               # look for action_required
gh api -X POST repos/{owner}/{repo}/actions/runs/<id>/approve
```

Approve every parked run, then continue the sequence — they go green in minutes.

The trigger is the **actor, not a fork**: a `pull_request` event whose head
commit was pushed by a bot identity (`github-actions[bot]` — i.e. any workflow
that pushes to a PR head branch with `GITHUB_TOKEN`) is held for approval, and
no repo Actions setting turns that off. Approving is the workaround; removing
the bot push from the PR branch is the fix.

## Close-out sequence

1. Finish or explicitly abandon all in-flight work.
2. Run the final `periodic-review` pass, before the wave PR — cadence, scope and
   enforcement are "Counterbalance" above.
3. Serialize the remaining merges. **Confirm the wave branch is green on Linux**
   (`make wave-platform-check BRANCH=<wave-branch> HEAD_SHA=$(git rev-parse HEAD)`)
   — the local root gates covered macOS only (#1750, above).
4. Run [`retro-miner.md`](retro-miner.md): branch preflight, missing-log report,
   mining lenses, issue filing, then the Slack wave digest.
5. Generate the wave-shape diagram and commit it on the wave branch, then open
   the single wave PR from [`wave-pr-template.md`](wave-pr-template.md) —
   `wave` label, assignee, full `Closes` list, and the diagram (#789) embedded at
   the top of the body. Storage, editorial rules and the reference instance:
   "The wave-shape diagram" above. Run
   `make wave-pr-check BODY=<draft> TITLE=<title>` first; CI runs the same gate
   on every `wave/*` PR (#897). If the PR then shows zero checks ~2 min later,
   clear the parked runs (above) before treating CI as slow.

   **Sweep for issues the `Closes` list missed, while the PR is still open**
   (#1846). This is the only point where the cheap remediation exists: a missing
   issue is one `gh pr edit --body` away and GitHub auto-closes it on merge. After
   5a there is no open PR to edit, so every hit costs a hand-close instead. The
   command, its fail-closed guard and what to do with a hit:
   [`delivered-but-open.md`](delivered-but-open.md).
5a. **Merge the wave PR yourself the moment it is green** (#1878). You opened
   it, so you own the merge — not the human, not the kickoff session, not a
   chief-of-staff. Wait only on a real open question. If you are a relaunched
   supervisor resuming a dead one's worktree, you inherit the PR and the merge
   with it. Then `gh pr merge --squash --delete-branch`. (The #1757 assignee
   false-negative, and the undiscoverable `wave`-label toggle that was the only
   way to clear it, are fixed — the gate now reads the assignee from the API and
   re-fires on `assigned`.)

   **Then run the wave's live steps from the merged code** (#2567): every deploy,
   `apply` and live smoke a worker handed back. Run each, verify it, put the
   result in the close-out report. Only a stop-list step goes to 5c as a question:
   `docs/process/live-steps.md`.
5b. **After the squash lands, repoint the diagram URL (#1759).** The SHA in the
   body is a wave-branch commit and the wave branch is gone, so the wave record's
   one image is hanging off GitHub's PR-ref retention. Rewrite it to the squash
   commit and re-run the gate:

   ```bash
   sha=$(git rev-parse origin/$(make base-ref))        # the squash commit
   gh pr view <n> --json body --jq .body > /tmp/wave-pr-body.md
   # replace blob/<old-sha>/ with blob/$sha/ in that one URL, then:
   gh pr edit <n> --body-file /tmp/wave-pr-body.md
   make wave-pr-check PR=<n>                            # resolves the URL now
   ```

   `make wave-pr-check` resolves the diagram URL against GitHub and fails when it
   does not resolve, so a skipped repoint is caught rather than discovered a year
   later by a reader. With no network (or no `gh` auth) the resolution is
   **skipped and disclosed**, never failed — an offline gate that goes red teaches
   supervisors to ignore it.

5c. **Ask the human items with `AskUserQuestion`, never a closing paragraph**
   (#806). `WAVE-STATE.md`'s `## Needs-input bucket` is this call's queue: ask
   what is parked in it verbatim, plus any human item the wave produced after the
   last park. Four questions per call, overflow filed as issues. The qualifying
   test, the bucket-reading rule and a worked example:
   [`asking-the-user.md`](asking-the-user.md#close-out-the-ask-is-the-delivery-806).
   The prose report still ships — it explains, the questions decide. **Not a
   question:** whether to merge the wave PR (step 5a is yours).

6. Run the process sweep above over every wave worktree, **the supervisor's
   own included** (#2295); fail loudly on any survivor (#644). Re-run `make wave-platform-check` on the merge commit if any
   fold-in landed after step 3.
7. **Re-run that sweep as a post-merge backstop, before the wave issue is
   closed** (#1846) — it catches a late fold-in, and a step 5 run that was
   skipped. An issue a worker PR `Refs`'d but the wave PR never listed stays open
   forever and reads as eligible work in the next wave, which is what cost wave
   `2026-09-18-backlog` a full dispatch on #1202. A hit here is a hand-close with
   the delivering worker PR linked — expensive next to step 5's one-line edit,
   and far cheaper than the next wave's wasted dispatch.

8. **Close the wave issue** (#849) — after the wave PR merges, never before, with
   a final comment carrying what merged, what was abandoned, and what carries
   forward. See [`wave-issue-template.md`](wave-issue-template.md).
9. **Release the lease** — `make wave-release ISSUE=<n>` (#886). It records the
   release, drops the `wave: owned` label, and deletes
   `refs/wave-owner/<wave>` **last**: the ref is what a racing supervisor tests,
   so a lease left behind blocks the next wave on that name.
10. Walk the `WAVE-STATE.md` close-out checklist; report anything left unchecked.
11. **Hand back the links.** The closing message to the human ALWAYS carries the
    full wave PR URL and the wave issue URL, written out — not "#937", not "the
    wave PR". Those two links are how a human re-enters the wave after the
    branch and worktrees are gone; a close-out report that names them only by
    number makes the reader go hunting for their own wave.

**Unbounded mode hand-off.** On backlog-drained or a stop condition, do the above,
then report: what merged, what is parked in needs-input (**asked** via step 5c,
not narrated), and what is left in the slice. A wave that ends without naming the
remainder forces the next supervisor to re-derive it.
