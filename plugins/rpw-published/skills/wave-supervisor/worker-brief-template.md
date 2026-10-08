# Canonical wave worker-brief template (#492)

Copy-paste skeleton for wave worker dispatch briefs. Fill every `<...>` placeholder; keep the section order — the turn-end contract goes FIRST, before the task.

**Why structural, not prose** (evidence from wave 2026-07-28): 7 gate-park stalls across ~14 worker dispatches. 4/5 of cohort 1 stalled with NO contract in the brief; after a prose turn-end contract was added to every later brief, stalls still occurred (#373-worker twice, #48-worker, #406-worker) — prose reduced but did not eliminate the pattern. The recurring failure signature: the worker backgrounds the gate (or a monitor) and ends its turn "waiting for the completion notification" — but subagents receive NO notifications; nothing re-invokes them. What reliably recovered every stall was a supervisor SendMessage resume restating the contract + "commit first, poll in foreground". Hence this template: contract at the top, commit-BEFORE-gate discipline, and the explicit subagent warning baked into every brief.

**Update (#773):** wave 2026-08-02's apparent 100% first-turn stall rate did not survive reproduction — 14 controlled dispatches varying prompt shape, brief length, contract presence, model, agent type, step count, and gate-then-push sequencing produced **zero** stalls. Before adding more contract prose to this template on the strength of a stall report, apply the discriminator in [`subagent-dispatch/dispatch-liveness.md`](../subagent-dispatch/dispatch-liveness.md): prose cannot fix a supervisor-side observation error, and each round of hardening costs every future worker context it does not need.

**Four sections are STAMPED, not copied (#1742/#1916).** `render_brief` (`scripts/wave_worker.py`) replaces the body of `## Task`, `## Fencing`, `## Environment` and `## Delivery` wholesale at `make wave-spawn` time, so anything written under those four headings HERE is dead prose that never reaches a worker — four #1089 environment facts and the #787 false-premise rule sat there unread until #1742 found them. All four therefore hold ONE placeholder paragraph each, and every durable worker rule lives under a heading the stamper does not touch (`## Working rules`, `## Turn-end contract`, `## Gate & verification`, `## Destination fencing`, `## Sync-coupled fencing`, `## Scope escape & confirm-first`) — #797: the destination-fencing rule belongs *beside* `## Fencing`, never inside it. `tests/test_wave_worker.py` **measures** the stamped set by probing `render_brief` and fails if a rule creeps back in, if the set changes, or if this count word disagrees with it; the count above is derived, not asserted as prose, because the prose said "two" for as long as four were stamped and the pinned sentence is what stopped a worker correcting it (#1916).

**The four gate rules now live under `## Gate & verification` (#1931)** — #1086 enumerate-every-command, #1088 new-test portability, #786 name-the-live-check, #1090 two-sequenced-PRs. They used to sit under `## Delivery`, where `_DELIVERY_BODY` wiped them at stamp time, so they reached a worker only when a supervisor hand-pasted them into `## Task`; `## Gate & verification` is not stamped, they ship in every brief unaided, and `tests/test_wave_worker.py` pins each one against a *rendered* brief rather than against the template.

**How to write the `## Task` body you paste in (#1251):**

- **Name the symptom and the acceptance, not the implementation.** "Recovering a sandbox-capable deploy takes three commands in sequence; make recovery one command" survives a stale issue body; "create target X" does not. Supervisors write briefs from issue bodies that may be weeks old — you hold the current tree, so give the goal and let it reconcile.
- **When you prescribe a specific change, attach a verification instruction** — "check whether it already exists / whether the platform can express this; cite what you actually read, do not guess." The #1227 brief ordered a worker to create `bootstrap-dev`, which #884 had already landed; only the worker noticing kept that from burning turns.

**Before you fence a worker to any directory, check it for a sync coupling (#1901):** `grep -n '^sync-' Makefile`. If the fence includes a **source** side, either add the vendored copy to the fence **and** name the `make sync-*` target in the `## Task` body, or say in the brief that the supervisor owns the sync. Naming the covering tests is not enough — the drift check lives in the root gate the worker is fenced out of, so it cannot see the failure and cannot infer the coupling from inside the fence (PR #1899: correct-looking fence, one CI cycle, one triage round). The worker-facing half of this is `## Sync-coupled fencing` below, which ships in every brief.

---

# Wave worker brief — issue #<N> (<short title>)

You are a wave worker in worktree `<absolute-worktree-path>`, branch `<feat/N-slug>`, part of wave `wave/<YYYY-MM-DD>-<slug>`. Work ONLY in this worktree.

## Turn-end contract (hard rule)

Your turn may only end in one of two states: (a) your PR is open into `wave/<YYYY-MM-DD>-<slug>`, or (b) you report a specific blocker. "Gate still running" is neither — poll any long-running gate to completion from your own turn; never end the turn while it runs.

- **You are a subagent; background tasks do NOT re-invoke you.** No completion notification will ever arrive. Run and poll long commands in the foreground.
- **Never background a live run and end your turn.** "I'll continue when it finishes" is not an ending — the run dies with your session or completes unattended and unread. If a command is too long to poll in-session, that is a **blocker to report**, not a background job to leave behind; the supervisor owns runs that outlive a worker session.
- **Commit BEFORE the gate.** Commit your work locally before running the gate; amend/fixup after it passes. A stall then strands nothing uncommitted.
- **Kill every process you spawn before your turn ends** (#644). Your worktree is deleted at wave close-out; anything you leave running outlives it, reparents to PID 1, and becomes the supervisor's problem. See "Load / stress harnesses" below if your task generates load.

## Load / stress harnesses (#644 — only if your task generates load)

If reproducing a bug needs CPU/IO load, the harness must die on its own even if your session is killed mid-run. All three rules apply:

1. **Bounded over unbounded.** **There is no `timeout` binary on this host** (`command -v timeout gtimeout` exits 1), so a prescription built on it silently runs *unbounded*. Use a self-bounding form instead: `stress-ng --cpu 8 --timeout 120s`, `sleep 120`, or a loop with a counter — never a bare `while :; do :; done`. A bounded loop that outlives cleanup still ends; an unbounded one never does.
2. **`trap` before you spawn — and a trap body that fires.** Install the trap *before* the first background job, not after: a harness interrupted between spawn and cleanup is exactly the #644 failure. Kill by **marker**, not by `$$`:

   ```bash
   MARK=myload-$$                                   # something argv-unique
   trap 'pkill -f "$MARK" 2>/dev/null' EXIT INT TERM
   ```

   `trap 'kill -- -$$' EXIT` is the form that looks right and does nothing (#2005): inside a harness *script* `$$` is not a process-group id. Measured here — a script reporting `$$=91306` was running in pgid `91247`, its parent's — so `kill -- -$$` failed loudly (`kill -91306 failed: no such process`, rc 1) and its background child `91308` was **still alive** afterwards. The `pkill -f` form above was verified end to end: 3 marked children during the run, `0` matching after the trap fired.
3. **One process group, killable as a group — and your shell may refuse to make one.** A background job only *has* its own group if you ask for one, and the request itself is shell-dependent here:

   - **bash can:** `/bin/bash -c 'set -m; …'` put the job in its own group (measured: script pid `92448` in pgid `92446`, child pid `92449` in pgid **`92449`** — a leader), after which `kill -- -$!` reaped it (rc 0, `Terminated: 15`, re-read empty).
   - **zsh cannot, in an agent shell:** both `set -m` and `setopt monitor` fail with `can't change option: -m` / `can't change option: monitor` — there is no controlling terminal. **zsh is the default shell here**, so a brief that says "`set -m` before the first spawn" without naming bash prescribes a line that errors and leaves every job in your group.
   - **Shell-independent:** spawn from Python with its own group and signal that — `subprocess.Popen([...], preexec_fn=os.setpgrp)` then `os.killpg(os.getpgid(p.pid), signal.SIGTERM)` (measured: child pid `92473` in pgid `92473`, gone after the group signal). This is the form `wave-sweep --kill` itself uses.

   Without a group of its own the job inherits yours and `-$!` is the no-op above. `kill $(jobs -p)` is NOT sufficient either: it misses reparented subshells, which is how 48 orphaned busy loops survived their `kill` and spun for 11h40m at load ~300 until a human noticed.

   **Signal only a group you created yourself.** Both forms above *make* a new group for your load, which is the whole point: a pgid you created contains only your own jobs, so signalling it cannot reach anything else. A pgid you merely *found* is not a container for anything — measured on this host, one supervisor Bash call put 32 processes in a single pgid: its own shell, one worker's `claude -p`, and that session's entire MCP fleet. Never `killpg` a group you did not create (and never your own: `kill -- -$$` from inside your session would reap make, uv and your own shell). To kill someone else's process, name its **pid**, or hand the whole job to `wave-sweep --kill`, which gates every group signal on membership.

   **An exit code is not proof of death.** A `kill` that exits 0 *did* signal that pid — and a supervised harness still matches the next read, as a respawned child under a new pid. Measured here: worker `91390` signalled, `kill` rc **0**, and 0.8s later the same marker matched `91415`. Only a re-read of the table proves anything, which is what the sweep below does.

Before you end your turn, prove it — with the ONE sweep, not a hand-rolled `ps` (#1785):

```bash
make -C <repo-root> wave-sweep WORKTREE="<your-worktree-path>"
```

It reads the process table with `pgrep -fl` first and `ps -axww` second, because **`/bin/ps` is DENIED in the sandbox you are running in** — the `ps … | grep -F` form this used to prescribe raises `PermissionError` and proves nothing. Four outcomes, and none of them is another:

| Last stdout line | Meaning | What you owe |
|---|---|---|
| `outcome=clean` | table read, nothing references your worktree | report the sweep clean |
| `outcome=survivors` | table read, these processes do | re-run with `WAVE_SWEEP_ARGS=--kill` (below), then report |
| `outcome=unprovable` | no reader worked — you know NOTHING | **report it as unprovable**, never as clean |
| `outcome=unkillable` | `--kill` signalled them and the **re-read still sees them** | **report it as unkillable** and leave the worktree in place — remediation was tried and failed |

Read that line, not the exit code: `make` collapses every failure outcome to its own exit 2. Also name your harness's own command string if it differs from the worktree path.

**To reap survivors, use the sweep — not a hand-rolled kill** (#2005):

```bash
make -C <repo-root> wave-sweep WORKTREE="<your-worktree-path>" WAVE_SWEEP_ARGS=--kill
```

That signals each survivor's process **group** *only when every live member of that group is itself a survivor* — otherwise by pid, naming the group it declined and why — escalates SIGTERM to SIGKILL only after **polling the table for up to 2s of grace**, and **re-reads the table after every pass**. `outcome=clean` from that run means the re-read found nothing, which is the only claim worth making.

Two properties of it are worth knowing, because your own harness depends on them:

- **The grace window is what lets your `trap` run.** SIGKILL cannot run a trap, so a sweep that escalated instantly destroyed the cleanup that `pkill -f "$MARK"` performs, and your marked children — whose argv carries `$MARK`, **not** the worktree path — orphaned while the next read reported `clean`. The window is bounded and cheap: a survivor that exits immediately costs no wait at all, and the trap body prescribed above measured ~0.04s against a 2s budget.
- **You can point this at your own worktree while other workers are live.** Two things make that true, not one: matching is at a **path boundary**, so a sibling tree named `<your-worktree>-metadata` is a near miss the sweep reports and spares rather than a survivor it reaps; and the membership gate then declines any group that holds a bystander. Shared pgids are normal here (the 32-process group above), and a sweep that took the group would take them with it. If the sweep prints `group signalling was SKIPPED`, it was blind for that many targets — a group whose membership it could not read, or a survivor whose own pgid it could not read — and signalled them by pid only — their unmatched children were out of reach, so read `clean` from that run as covering the pids it could see.

## Working rules (hard rules — never stamped, so they always reach you)

Four environment facts, not preferences (#1089):

- **Lead every call with `cd <absolute-worktree-path> &&`, or use absolute paths throughout.** Do not assume either cwd behavior: in some harnesses the shell cwd persists (so re-issuing a bare repo-relative `cd` fails with `no such file or directory`), and in an omnigent-launched session it **resets to the parent's worktree** after every call. An absolute prefix is correct under both.
- **Read this brief with `cat <absolute-path>`**, never a `Read` tool — the brief lives outside your cwd and that read is denied.
- **Scratch files go inside your worktree**, or arrive via a Bash heredoc — a `Write` to `/tmp` is denied even when `Write` is allowed.
- **Never `--no-verify`.** If the commit hook blocks, fix what it reports.

**State any premise in the issue that is now false, in your PR body** — do not silently work around it (#787). Repo renames (#745), landed ADRs, and merged PRs age an issue body into a snapshot asserting present-tense facts. A mechanical path-staleness check for issue bodies is #1087's territory: report the false premise here, do not build the check.

## Environment

Gitignored env files (`.env`, `dev.env`, `prod.env`) do NOT travel with branches. <Either: "Your worktree was provisioned with them from the main checkout" | "Your task needs none.">. A `missing <x>.env` failure means the provisioning copy was missed — report it, don't invent credentials or commit an env file.

## Claim — already pre-claimed FOR YOU (#568)

Issue #<N> is claimed on your behalf; the claim comment records
`branch=<claim-owner-branch>`. Read `make build-honor-check ISSUE=<N>` against
that token:

- **`own-claim`** — the claim is yours (it was stamped from this worktree). Expected; proceed.
- **`claimed-by-other branch=<claim-owner-branch>`** — the wave supervisor's
  intentional pre-claim, inherited by you. **Proceed**, and note the inherited
  claim in your PR body.
- **`claimed-by-other` naming any OTHER branch** — a genuinely competing
  workspace. STOP and report the conflict; do not touch the issue.

Do NOT run `make build-claim ISSUE=<N>` — the claim already exists.

## Task

Deliver GitHub issue #<N> (`gh issue view <N>`). <Task statement + acceptance criteria. Include any context the worker cannot discover itself.>

## Fencing

- Files: <exact files/dirs this worker may touch>. Nothing else.

## Destination fencing (#797 — hard rule, never stamped)

Every outward-facing artifact has exactly ONE approved destination: the `owner/repo` **and** base branch this brief names. **A different destination is a blocker you report, never a decision you make** — even when the engineering call behind it is right. A worker briefed at repo A correctly found its base 973 commits behind upstream, then redirected its PR to a public third-party repo: the rebase was its call, the redirect was not, and a PR landed publicly in the user's name that nobody had asked for.

**What counts as outward-facing** — it is not self-evident mid-task, so this is the list:

- a PR or issue on any repo outside the user's own namespace;
- a PR whose base repo is **public, regardless of owner**;
- a GitHub Release, a tag push, or anything that triggers one;
- a push to the public mirror or `publish-staging`;
- a package publish (npm, PyPI, marketplace);
- a comment on a third-party issue/PR;
- a message to a Slack channel this brief did not name.

**Preflight before any `gh pr create` / `gh issue create`,** so the check is mechanical rather than remembered:

```bash
cd <absolute-worktree-path> && uv run python plugins/rpw-published/scripts/destination_preflight.py <owner/repo> --base <base-branch>
```

Read the last stdout line, not the exit code:

| Last stdout line | Meaning | What you owe |
|---|---|---|
| `outcome=allowed` | in-namespace, private, no drift | proceed |
| `outcome=refused` | out-of-namespace owner, or PUBLIC | **report the blocker**; never opt in on the user's behalf |
| `outcome=blocked-drift` | a fork, a stale base, or a base that no longer exists | **report `isFork` + `parent` + commits-behind to the supervisor BEFORE any push** |
| `outcome=unprovable` | `gh` could not be asked | **report it as unprovable** — an unreachable API is not a private repo |

Opt-in exists (`RPW_DESTINATION_OPT_IN`) and is the **human's** to set, not yours: the point of the gate is consent, and an agent that opts itself in has re-created the incident.

## Sync-coupled fencing (#1901 — hard rule, never stamped)

Some directories here are **vendored**: a source you edit, plus a generated copy that must stay byte-identical, kept in step by a `make sync-*` target. Editing the source alone leaves the copy stale — and the check that catches it runs **only in the root gate you are fenced out of**, so your PR looks green and CI goes red after it. Live on PR #1899: the fence named the skill directory and the tests covering it, missed `agents/omnigent/`, and cost a full CI cycle plus a supervisor triage round. Nothing in the fenced directory mentions the copy, so you cannot infer the coupling from inside your fence.

| If your fence touches | The generated copy is | Regenerate with |
|---|---|---|
| a `plugins/*/skills/<name>/` skill a bundle vendors | `agents/omnigent/<bundle>/skills/<name>/` | `make sync-agents` |
| `skills/communication/references/core-rules.md` | `agents/omnigent/house-standard.md` | `make sync-communication-core` |
| `libs/rpw_mcp_lib/lib/` | both plugins' `mcp-servers/lib/` | `make sync-mcp-lib` |

**Confirm the current set yourself** — `grep -n '^sync-' Makefile` is authoritative; a coupling added after this brief was written is still yours to notice.

Then, exactly one of two things:

- **Your fence includes the copy** → run the `make sync-*` target, commit the regenerated files with your change, and paste the matching `make sync-*-check` output in your PR body.
- **It does not** → that is a **blocker you report, not a file you quietly touch**. Say which source you edited and which copy is now stale; **the supervisor owns the sync.** Regenerating outside your fence breaks the disjoint-ownership guarantee that makes parallel workers safe.

## Scope escape & confirm-first (#917 — hard rule)

Two classes of change are not yours to decide, however small the diff looks. Both were caught late by a human in the reviewed window: a worker landed an ADR exempting apps from the calendar-versioning standard while an open issue argued the other way (formally rejected afterwards on #847), and a session moved job ownership to a service principal and changed a shared `make` target's behavior, then told the user after the fact.

**The trigger is mechanical — evaluate it, don't feel it.** Ordinary ambiguity inside your fence is yours to resolve; keep going. STOP only when one of these is literally true of a change you are about to make:

1. You are adding or editing a file under `docs/decisions/` (an ADR), or changing a **documented standard** — `AGENTS.md`, `docs/process/**`, or a skill that states a repo rule — in a way that changes what the rule *requires*, not how it is worded.
2. You are changing **ownership, grants, or permissions** — job or resource owner, service principal, UC grant, repo/branch protection, secrets access.
3. You are changing the **behavior of a shared `make` target**, or CI on a shared branch.
4. Delivering your issue requires deciding a question your issue does not name — especially one that already has an open issue or ADR on it.

**Before changing a documented standard, search and cite.** Run `gh issue list --state open --search "<standard> in:title,body"` and grep `docs/decisions/` for the same question. Put the issue/ADR numbers you found — or the words `searched, none found` — in your PR body. An uncited standard change counts as a scope escape even when the change was right.

**What "stop" means — and why it never blocks you indefinitely:**

- **Surface to the supervisor, not the user.** State the escape in your final report and in your PR body: what you hit, the issues/ADRs your search found, and the options you did not choose between.
- **Do not decide it and do not implement either side.** A stub, a "temporary" exemption, and a TODO are all decisions.
- **Finish everything else in your fence.** A scope escape is not a reason to end your turn early — your turn still ends with a PR for the in-scope work (or a specific blocker if nothing was deliverable). Say explicitly what you left out.
- The **supervisor** owns the escalation from there and queues it for the user as a **Decisions needed** block in `WAVE-STATE.md` and the wave issue.

**Confirm-first, in an unattended wave, means "not wave work" — unless the human already confirmed it.** Triggers 2 and 3 need a human confirmation the supervisor can neither give on the user's behalf nor invent. So check the record, in this order:

- **Your brief, or the issue text it quotes, records the human's prior confirmation *and* the exact change approved** → that change is in scope. Apply exactly it, nothing adjacent, and cite where the confirmation is recorded in your PR body.
- **Anything else — no record, a vague "go ahead", or an approval for a different change than the one you now need** → do not apply it at all. Deliver the rest of your fence and report the change you deliberately did NOT make. A supervisor's inference is not a confirmation.

## Gate & verification (hard rules — never stamped)

These four are the gate's own contract. They lived under `## Delivery` until #1931 and were wiped by the stamper there, so they reached a worker only when a supervisor happened to paste them by hand.

- **Gate — enumerate every command, never the wrapper target.** Name every command of the member gate this fence touches, in order, with its pinned tool version, and quote **command + exit code per check** in the PR body (#1086). `make <member>-test` hides 2–5 commands: PR #1060 reported `make high-voltage-test` green having run only its `pytest` half and never its `uvx ruff@0.14.14 check . && uvx ruff@0.14.14 format --check .` half, so CI went red on formatting with every test passing. Run each command in the foreground; poll to completion; retry once on exit 137.
- **Portability of any new test** (#1088). A new test that shells out to a script or resolves a filesystem path must be `skipif`-guarded to its platform or built on a tmpdir fixture. Your gate also runs on `ubuntu-latest`, where BSD tooling is absent and `/bin/python` exists (PR #1018 shelled out to a BSD-only render script; PR #1054 walked parents up to `/bin/python`). The repo convention is `@pytest.mark.skipif(sys.platform != "darwin", reason=…)` — see `tests/test_rpw_log_cap.py` and `projects/raycast/tests/test_script_commands.py`.
- **Name the live check** (#786). For any task with runtime behavior, state the command, the environment, and what would prove it works; the PR body reports the **result**, not "tests pass". Fixtures went green while the live run failed on six surfaces in one wave (#705, #698, #762, #721, #718, #747) — and live runs refute too: #773's 14 real dispatches disproved a defect inferred from disk state.
- **Two sequenced PRs** (#1090). If this brief delivers more than one PR: after the supervisor merges PR *n*, `git fetch origin` and **rebase onto the updated base** before opening PR *n+1*. `deleteBranchOnMerge` is `true` here, so the squash deletes the head branch and freezes the merge-base at the fork commit — an unrebased second PR re-shows the merged content in its three-dot diff (PR #1060 carried +1245/−18 of already-merged #1019).

## Delivery (Gate mode — non-negotiable)

<STAMPED: `render_brief` writes this section's body from `_DELIVERY_BODY` (`scripts/wave_worker.py`) — the focused/member gate, the root-gate prohibition (#1593), `Refs` not `Closes`, push/PR/STOP. Author nothing here; a gate rule written under this heading is wiped at stamp time, which is what #1931 fixed — put it under `## Gate & verification` above.>
