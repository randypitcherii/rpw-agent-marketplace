# Supervision — liveness, stall triage, salvage

Companion to [SKILL.md](SKILL.md) step 4 (#531). Everything here was earned on
live waves; the ordering is the lesson, not decoration.

## Liveness signals, in reliability order

Earned across waves 2–3 — both monitor false-alarms came from layer 3:

1. **Harness task-completion notifications** — primary; never wrong across 10+ workers.
2. **Worktree progress** — dirty-file counts / commits; the mid-flight signal.
3. **Process inspection** — last resort only; NEVER pattern-match on prompt text
   (relaunched workers start "RESUME…", not "Implement…").

**For an in-process Agent-tool worker, only a `task-notification` with
`status=completed` means it stopped (#773)** — and that guarantee is
**substrate-scoped, not universal**. A cross-session omnigent child
(`sys_session_create` / `sys_session_send`) can reach a terminal state with **no
inbox item ever**, so a supervisor holding the unscoped absolute waits forever on
a worker that is already dead (#853, #1037). For that substrate, poll
`sys_session_get_info` on the `conversation_id` you recorded at launch — `status:
failed` or `runner_online: false` is terminal — and read
`sys_session_get_history` before relaunching, because a dead session's findings
are recoverable. The scoped discriminator for both substrates is canonical in
[`subagent-dispatch/dispatch-liveness.md`](../subagent-dispatch/dispatch-liveness.md);
read it rather than re-deriving it here.

A clean worktree never means stopped, in any mode: dispatch is asynchronous,
orientation leaves no disk footprint, and healthy workers routinely go 3–5
minutes before their first commit (read-only agents emit nothing at all until their single final report).
Signal 2 is a *progress* signal, never a *stopped* signal — reading it as the
latter is a false-positive engine, and it is what produced wave 2026-08-02's
report of a 100% first-turn stall rate across ~20 workers, none of which had
actually stalled. Do not read or tail a running agent's transcript file to judge
progress; its first line is always the model's preamble. Beware any *secondary*
inbox/bridge channel that surfaces mid-flight text as if it were a return value —
that conflation is exactly how the false rate was generated.

When a completion notification *does* arrive without a PR or a specific blocker,
nudge immediately and automatically — a nudge to a running agent is queued until
its current tool call returns and is absorbed harmlessly, so a wrong nudge is
cheap and a missed one is a dead worker. But never treat "the nudge recovered it"
as evidence the worker was stalled: a subagent cannot even receive a message
mid-tool-call, so a nudge sent during a long gate does nothing until that gate
finishes anyway. That inference is unfalsifiable from the outside.

**Backstop:** a 60-minute "has each worker produced output yet" silence timer. It
covers the only gap notifications leave — a hung worker that never exits.
Process existence alone is NOT liveness (#259 prompt-wedge).

Mode-A notifications are free only while the supervisor session is alive; in a
durable session, observe a first artifact per worker in-turn or arm a liveness
mechanism (#881, [`dispatch-mechanics.md`](dispatch-mechanics.md)).

## Liveness is queried from the dispatch layer, never inferred (#827)

**Query the dispatch layer for a worker's state; worktree contents are not
evidence of it.** `ListAgents` and the task's own status (mode B: `kill -0 <pid>`
plus log growth; omnigent child: `sys_session_get_info`) answer *is this worker
alive*. `git status` answers *has it written anything yet* — a different question
with a different answer. A worker
whose task is non-terminal is **alive**, whatever its worktree looks like.

**"No commits yet" is the normal steady state and is never death.** Workers do not
commit until their task is done, so base-commit-and-clean is what a healthy worker
looks like for most of its run, and stays so until incremental commits land
(#824). Classifying that as death is wrong in exactly the common case, and what it
buys is a live worker re-dispatched into an occupied worktree — the corruption
**One worktree, one worker** ([`dispatch-mechanics.md`](dispatch-mechanics.md))
forbids.

**Three states, not two:**

| State | Evidence | Do |
|---|---|---|
| **Alive, producing** | log growth, dirty files, or new commits since the last check | leave it alone |
| **Quiet but alive** | dispatch layer reports a non-terminal task; no new output | **not death.** Nudge if a completion notification arrived without a PR or blocker; otherwise let the silence backstop and the stall timer below decide |
| **Confirmed dead** | a terminal task status, or the three-part conjunction in [`dispatch-mechanics.md`](dispatch-mechanics.md) (#881) | cancel explicitly, confirm termination, *then* relaunch |

Declaring a worker dead is an action with a precondition: **explicit cancel plus
confirmed termination before its worktree is reused.** Record the evidence you
queried in `WAVE-STATE.md` — "I concluded it was dead" is not a record, and the
2026-08-05 wave's untrustworthy state file is what that costs.

## Watchers must alert on stalls, not only on exit (#497)

Every watcher over a long-running process — a worker, or a supervisor-owned
detached run ([`dispatch-mechanics.md`](dispatch-mechanics.md)) — needs **three**
terminal conditions, not two: completed, crashed, **and stalled**. A watcher that
only covers "summary appeared" and "process exited" reads a hang as healthy
progress: a detached baseline run hung on mlflow's SQL-warehouse auto-start for
**4 days** — process alive, 0 CPU, log frozen — while its watcher stayed silent.
The replacement watcher, with a 15-minute log-growth timeout, caught the next
stall immediately.

**Stall signal = no log growth for N minutes while the process is alive.**
Default N = 15 for runs whose logs stream continuously; raise it only for a run
with known quiet phases, and say so when you do. **Bytes are the weak form of this
signal** — for a mode-B worker log, parse it for tool-use and `is_error` counts and
the final `result` subtype instead (#974,
[`dispatch-mechanics.md`](dispatch-mechanics.md)).

```bash
LOG=.wave/worker-<issue>.log; PID=<pid>; TICK=60; STALL_TICKS=15   # ~15 min
last=0; idle=0
while kill -0 "$PID" 2>/dev/null; do
  sleep "$TICK"
  now=$(stat -f %z "$LOG" 2>/dev/null || echo 0)     # Linux: stat -c %s
  if [ "$now" -gt "$last" ]; then last=$now; idle=0; else idle=$((idle + 1)); fi
  if [ "$idle" -ge "$STALL_TICKS" ]; then
    echo "STALL: $LOG frozen ${idle}m, pid $PID alive"; break
  fi
done
```

Silence is never evidence of progress. On a stall fire: check CPU
(`ps -o time,%cpu -p $PID` — ~0 confirms it), read the log tail for what it was
waiting on, then nudge/salvage or kill and relaunch. Record the stall in
`WAVE-STATE.md` — a hang nobody logged is a hang the retro can't cost.

## Completion-notification triage (#492)

A worker result must contain **a PR URL or a specific blocker**. Anything else
(e.g. "waiting on the gate", "gate still running") is a STALL — don't wait,
`SendMessage` the standard nudge:

> Commit now; run the gate in the foreground to completion; push and open the
> wave-branch PR. Your turn ends only with the PR open or a specific blocker.

Commit-before-gate (in the brief template) means a stall strands nothing
uncommitted.

### A URL is a claim until its base is verified (#1023)

**A PR URL alone does not make a result delivered.** Run the canonical PR check —
[`subagent-dispatch/return-verification.md`](../subagent-dispatch/return-verification.md#pr-opened),
not a restatement of it — and read `baseRefName` before you record anything:

- `baseRefName` **must equal the wave branch you dispatched against**, exactly.
- `headRefName` must be the worker branch from the brief.
- Either mismatch ⇒ **not delivered.** A PR opened against `production` is a
  found artifact and a failed dispatch at the same time (#1010); triage it as a
  failed dispatch and re-dispatch the worker to reopen against the wave branch.

Why the check cannot wait for merge time: `gh pr merge` honors the PR's own base,
so a wrong-base PR that reaches the serialized merge step
([`merge-and-closeout.md`](merge-and-closeout.md)) is **executed, not rejected** —
one worker's slice lands on `production` mid-wave, breaking the guarantee the wave
exists to hold and letting the #480 auto-bump fire. Intake is the only place this
is cheap.

## The launch-death signature: one planning sentence, zero tool calls (#1250)

In an **omnigent-launched supervisor session**, a mode-A child's *first* result is
frequently **a single planning sentence with zero tool calls** — "I'll read the
brief and start with the issue." That is a **launch death, not a report**. It is
not the turn-boundary death of [`dispatch-mechanics.md`](dispatch-mechanics.md)
(#881): the child dies **at launch**, with the supervisor still in-turn, so
`.wave/worker-<n>.log` was never written and the worktree is still at the fork
commit.

The trap is the shape of the return. A sentence is a *complete* result, so the
notification reads as "the worker reported" and the triage rule above has to be
read strictly to catch it. Read it strictly: **no PR URL and no specific blocker
is a STALL, and a first result with no tool calls and no artifact is the
launch-death case of it.** A one-line result is not a deliverable.

**The remedy is one `SendMessage` to the same agent id — nudge before you ever
relaunch.** The nudge revives the child with its context intact; a relaunch pays
the full brief read again, can double-claim the issue, and is the action the
strike rule in the salvage protocol exists to bound. Only after a nudge fails to
produce an artifact does the three-part death detector apply
([`dispatch-mechanics.md`](dispatch-mechanics.md), #827/#881) — and only then is
a relaunch the move.

**This is a launch step, not triage.** After a mode-A cohort dispatch from an
omnigent session, budget one nudge per child the same way you budget 3–5 minutes
for a first artifact: on this substrate it is what the launch costs, not evidence
that something is broken. Evidence: wave `2026-08-23-sandbox` — **5 of 5
children** returned the one-sentence result, **5 nudges, 0 relaunches**, and every
one then ran to completion (PRs #1247, #1249, plus two lens reports and one
bug-catching run).

**Record each nudge in `WAVE-STATE.md`** as an event — a nudge is a launch step
the retro has to be able to cost, and reconstructing it from memory is what #569
fixed:

```bash
make wave-state-append SECTION='Events' \
  LINE='<ISO-8601 UTC> — nudged #<n> (launch death: one-sentence first result, 0 tool calls)'
```

A nudge is not a relaunch: append the resumed worker's report and a second usage
line to the **existing** `.wave/worker-<n>.log`, never a new `.r<k>.log`
([`dispatch-mechanics.md`](dispatch-mechanics.md), #570).

## Salvage protocol

Validated 4/4 and 2/2 on live VPN drops.

1. **Probe connectivity first — mode B only (#1022).** Re-run the bounded 1-token
   probe from the **Bootability preflight**
   ([`dispatch-mechanics.md`](dispatch-mechanics.md)), with the exact flag set you
   dispatch with. A dead network looks exactly like a dead worker, and the same
   probe re-checks CLI flag drift (#498). A failure here is an environment
   verdict, not a worker verdict: fix it before relaunching anything.

   **In mode A this step does not exist — skip to step 2.** The preflight says so
   in as many words: the worker runs inside your session, so there is no second
   process to boot and no probe applies. Every wave since wave 5 has run in mode
   A, so skipping is the normal path, not an exception. Do **not** run the mode-B
   `claude -p` probe to manufacture a step 1; a mode-A worker's readiness evidence
   is its first observed artifact, not a probe.

   **A `classifier-blocked` result is not the environment verdict this step
   means.** The auto-mode permission classifier refuses that `claude -p`
   invocation intermittently — approved 4× and denied 3× in the wave-5 retro,
   denied again at 2026-08-01T02:02Z — which is a statement about the classifier,
   not about the network or the worker. The roster table is explicit that it is
   **not** a target failure: go to mode A and relaunch there. Stopping a
   recoverable salvage because a permission prompt fired is the failure this
   paragraph exists to prevent.
2. **Confirm the prior worker is terminated, then relaunch in the SAME worktree**
   — cancel it explicitly and prove the worktree is empty of processes before the
   relaunch (**One worktree, one worker**,
   [`dispatch-mechanics.md`](dispatch-mechanics.md), #827); relaunching into a
   worktree whose previous worker is still live is the corruption, not the
   salvage. Then use a salvage header:

   > Review `git status` / `git diff` / `git log` first; continue — don't start
   > over; check for existing comments/PRs before posting.

   Partial work survives into the final PRs.

   **Whether you may relaunch at all is one rule, and it is not a count (#1021).**
   It lives in
   [`subagent-dispatch/return-verification.md`](../subagent-dispatch/return-verification.md)
   — the same section that governs every other dispatch return, so the two skills
   now agree. In short: a relaunch of a dispatch that **never ran** (runner death,
   VPN drop, flag drift) costs nothing; a relaunch carrying a **newly diagnosed
   cause** — run id, error verbatim, root cause, prescribed fix, written into the
   worktree as `FOLLOWUP.md` and quoted in the prompt — buys exactly one more
   dispatch and cannot be spent twice; a **second undiagnosed repeat of the same
   failure** is the stop. Stop means **park the issue and escalate**
   ([SKILL.md](SKILL.md)) — never implement a fenced issue yourself, inline, in
   the worker's worktree, which is the **One worktree, one worker** and
   file-ownership violation (#827) the cap exists to prevent.
3. **Keep the artifact trail on the same issue key** — the relaunch writes
   `.wave/worker-<issue>.r<k>.log` and appends a metadata line for the same
   issue (#570, see [`dispatch-mechanics.md`](dispatch-mechanics.md)). A salvage
   that starts a fresh, unrelated log is how one worker's cost gets split across
   artifacts nobody can rejoin. The `.r<k>` ladder is deliberately unbounded as a
   *naming* scheme; what bounds relaunches is step 2's strike rule, never the
   filename.
4. **Record the event in `WAVE-STATE.md`** — launch, relaunch, and parking events
   are close-out inputs, and reconstructing them from memory is what #569 fixed.

Escalate stalls with a specific question; never stall silently. "Specific" means
**tool-ready** — queued while workers are in flight, then asked with
`AskUserQuestion` the moment the user signals they are available, or immediately if
nothing else is eligible. The option count, the timing rule and the queue format
are specified once, in [`asking-the-user.md`](asking-the-user.md).
