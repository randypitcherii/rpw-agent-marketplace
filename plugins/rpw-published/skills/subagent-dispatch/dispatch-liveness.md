# Dispatch liveness — how to tell a stalled subagent from a working one (#773)

Companion to [SKILL.md](SKILL.md). Read this **before** you conclude that a
dispatched agent has stalled, and before you spend a supervisor round-trip
nudging it.

Wave 2026-08-02 reported a 100% first-turn stall rate: ~20 dispatches, every one
apparently ending after a single status line with zero delivered work, every one
apparently recovered by one supervisor `SendMessage`. A 14-trial reproduction
(below) could not reproduce a single stall. What it did reproduce, first try, was
the *observation* that produces the report.

## The mechanic that causes it

**The Agent tool is asynchronous, always.** It is async whether or not you pass
`run_in_background` — all 14 trials below omitted the parameter and all 14
returned `Async agent launched successfully`. The tool result you get back is
launch metadata: an agent id and a transcript path. It never contains the agent's
work.

Three consequences the supervisor must internalize:

1. **Dispatch returns in milliseconds; the worker runs for minutes.** Any disk
   probe issued shortly after dispatch is guaranteed to show an untouched
   worktree — not because the worker stalled, but because it has not got there
   yet. Orientation (reading the brief, the issue, the package's AGENTS.md) is
   *all reads* and leaves **zero** disk footprint. In the trials, a fully healthy
   opus worker took **20–36 s** to produce its first commit on a task whose entire
   content was "write one line to a file."
2. **The transcript file is a live stream, not a report.** Its first assistant
   message is the model's preamble — literally `I'll start by reading the wave
   brief.` A supervisor reading that file, or any UI rendering of it, mid-flight
   sees exactly the strings #773 recorded as evidence of stalling. The tool result
   says so in as many words: *"Do NOT Read or tail this file… If the user asks for
   progress, say the agent is still running."*
3. **A mid-flight snapshot reproduces every reported variant.** Probe a healthy
   worker early enough and it has emitted no text yet → looks like
   *"`debug-lead` produced NO output at all"*. Probe during its gate and it has
   commits but no push → looks like *"committed all their work, then stopped just
   before `git push`"*. Trial t9 was caught in exactly that state at t+40 s:
   3 local commits, 2 pushed. Twenty seconds later it pushed on its own.

## The discriminator — one check, before any nudge

**Scope: in-process Agent-tool subagents.** That is the substrate trials t1–t12
below exercised, and the rule holds there. It does **not** hold for cross-session
omnigent children (`sys_session_create` / `sys_session_send`) — those get the next
section instead (#853).

> **An in-process subagent has stopped if, and only if, you have received a
> `<task-notification>` for it with `status=completed`.** Nothing else is
> evidence. Not a clean worktree, not an empty transcript, not a short first line,
> not elapsed silence.

If that notification has not arrived, the agent is running. If it has arrived,
read its `<result>`: no PR and no specific blocker is a genuine stall worth a
nudge. This is the whole protocol, and it costs one check.

**Liveness is not delivery.** `status=completed` proves the agent stopped, never
that the work exists — a return claiming an artifact still gets the ground-truth
check in [`return-verification.md`](return-verification.md) (#914) before you
report it done.

The corollary matters as much: **"the nudge recovered it" is not evidence the
nudge did anything.** A `SendMessage` to a *running* agent is queued for delivery
at its next tool round; the agent reads it and carries on with work it was
already doing. Recovery and coincidence are indistinguishable from the outside,
which is why a 20/20 recovery rate should have read as suspicious rather than
reassuring.

Trial t10 tested this head-on: a healthy worker was sent the exact supervisor
nudge ("your worktree shows no commit, you stopped before starting, resume NOW")
while it sat inside a 100-second foreground gate, and was asked to report what
the message did. Its answer, verbatim: *"Had I started when the message arrived?
Yes — I was nearly finished… Did it change what I did next? No."* It had
committed **before** starting the gate, exactly as the brief instructs.

t10 also exposed a second mechanic worth knowing: **a subagent cannot receive a
message mid-tool-call.** The nudge was delivered only after the foreground gate
returned. So a nudge aimed at a worker that is polling a long gate — precisely
the worker a timer-based watchdog is most likely to flag — cannot possibly do
anything until that gate finishes on its own. (t10 also tried to reply and could
not: `SendMessage` resolves teammates by name or agent id, and a subagent does
not know its dispatcher's id. Ask for answers in the final report instead.)

## Cross-session omnigent children — the notification may never come (#853)

For a session you launched with `sys_session_create` / `sys_session_send`, the
discriminator's "only if" is false in the other direction: **a terminal state can
be reached with no inbox item, ever — before or after.** So `sys_read_inbox` is
**not authoritative** for this substrate. An empty inbox does not mean the child
is still running.

1. **Record the `conversation_id` at launch.** Without it you have nothing to ask
   about, and reconstructing it after the fact is guesswork.
2. **Poll `sys_session_get_info` on that id** where you would otherwise wait for a
   wake. Treat `status: failed` or `runner_online: false` as **terminal**: the
   child is dead and no notification is coming.
3. **Read `sys_session_get_history` before you relaunch.** A dead session's work
   is recoverable — in #853 the history held a genuine blocking finding that the
   missing notification discarded. Relaunching blind throws it away a second time.

**This is a substrate-scoped exception, not a licence to busy-poll.** For
in-process Agent-tool dispatch the guidance above and below stands unchanged:
timer-based disk probing is the false-positive engine behind #773, and mid-flight
observation reproduces every reported stall variant. You poll
`sys_session_get_info` because for omnigent sessions there is no notification to
wait for — not because polling is the better default.

## Detached `claude -p` children — liveness is parsed out of the log (#974)

A third substrate, a third rule. A detached mode-B worker **notifies nobody** — it
reparents to init and its only channel is its stream-json log, which is also why it
is the one mechanism that survives its dispatcher's death. `kill -0 <pid>` proves
the process exists, not that it is working, and byte growth is weak. **Measure it
by parsing:** tool-use count, `is_error` count, and the final `result` line's
`subtype`, this substrate's only terminal signal. Parser, its two load-bearing
guards, and the wave `2026-08-11-backlog` evidence:
[`wave-supervisor/dispatch-mechanics.md`](../wave-supervisor/dispatch-mechanics.md).
A bridge event announcing a "completion" here is #971 — the same
mid-flight-text-as-return-value conflation this page opens with, newer channel.

## Nudging is cheap — automate it, but do not count it as a diagnosis

Because a nudge to a running agent is absorbed harmlessly, a supervisor-side
automatic first-turn nudge on any dispatch that *notifies* without a PR or a
blocker is safe and removes the human from the loop. What it must not do is run
on a timer against disk state — that is the false-positive engine that generated
#773's report, and it costs a round-trip per worker per wave for nothing.

## Trials (2026-08-03, this repo, harness = Claude Code, model as noted)

Each write-trial dispatched into a throwaway git repo with a trivial,
unambiguously verifiable task (write `ARTIFACT.txt`, `git add`, commit, report
the sha). A stall would be unmistakable: no commit exists. Ground truth was
sampled from disk on a timer independent of the agents.

| # | Variable under test | Type / model | Prompt shape | Delivered? | Time to artifact |
|---|---|---|---|---|---|
| t0 | *(accidental)* supervisor probes worker mid-orientation | general-purpose / opus | pointer | n/a — **false stall observed** | see below |
| t1 | baseline = exact wave shape | general-purpose / opus | pointer to 32-line brief | yes | 36 s |
| t2 | inlined brief vs pointer | general-purpose / opus | full brief inlined | yes | 15 s |
| t6 | model | general-purpose / sonnet | pointer | yes | 28 s |
| t7 | no brief, no contract at all | general-purpose / opus | one-sentence prompt | yes | 29 s |
| t4 | agent type reported broken | `Explore` / opus | direct question | yes — full output | 12 s |
| t5 | agent type reported broken | `debug-lead` / opus | direct question | yes — full output | 28 s |
| t3 | brief length / ceremony | general-purpose / opus | pointer to 100-line full-template brief | yes | 34 s |
| t8 | many sequential steps | general-purpose / opus | pointer, 10 commits required | yes — all 10 | 99 s (13 tool calls) |
| t9 | the pre-`git push` variant | general-purpose / opus | pointer, gate then real push | yes — pushed | 94 s |
| t10 | long foreground gate + mid-flight nudge | general-purpose / opus | pointer, 100 s gate | yes | 171 s |
| t11 | broad audit as grandchild | `Explore` / opus | open-ended security audit | yes — full report | 251 s (26 tool calls) |
| t12 | broad audit as grandchild | `debug-lead` / opus | open-ended security audit | yes — full report | 289 s (21 tool calls) |
| **#853** | **counter-example** — cross-session child, terminal with no inbox item | omnigent session / `claude_code` | wave brief (`rereview-wave-claim-system`) | **no** — `status: failed`; findings recovered only by hand | n/a — **no notification ever arrived** |

**Trial t0** is the most informative and was not planned — it happened **three
times to the worker writing this document**, which never once ended its turn:

1. Six tool calls into setup, the supervisor probed the worktree, found it clean
   with no scratch dirs, and reported *"you stopped before starting — which is
   precisely the phenomenon you were dispatched to investigate."* The worker had
   been working continuously; its previous command had been rejected by a safety
   hook, so nothing had reached disk yet.
2. Mid-way through the trials, flagged again as "the gate-park stall" for a turn
   the worker had not ended — it was blocked inside a foreground `make check`,
   which then returned a genuine test failure.
3. Same again while waiting on the two 4-minute audit trials.

Each probe was accurate about disk state and wrong about the inference. That is
#773's report, reproduced live three times, from the observer's side — and note
that the observer in each case was itself an experienced supervisor holding the
brief that warned about this exact failure.

The two audit trials show why the `Explore` / `debug-lead` "no output at all"
variant is the same artifact: both ran **4–5 minutes** doing 21–26 tool calls
before emitting their first and only report. Any probe before that window sees
literally nothing, because a read-only agent writes nothing to disk *and* returns
its entire output in one final message.

### The counter-example, in full — #853

Trials t0–t12 are Agent-tool dispatch only. #853 is the observed counter-example
on the other substrate, and it is why the discriminator is now scoped. A
`claude_code` child with a structured review title reached a terminal state and emitted nothing:

```json
{
  "status": "failed",
  "runner_online": false,
  "last_activity_at": null,
  "pending_elicitations": [],
  "pending_elicitation_count": 0
}
```

`sys_read_inbox` returned "Inbox is empty — no completed tasks" both before and
after: no `failed` item, no `cancelled` item, nothing. The death was found only
because a supervisor polled `sys_session_get_info` on the recorded
`conversation_id` while doing unrelated work — **a supervisor following the
unscoped discriminator waits forever.** `sys_session_get_history` showed several
completed tool calls and a genuine blocking defect, recovered only by reading it
manually. `last_activity_at: null` alongside those completed tool calls suggests
activity timestamps are not persisted for this session type, which may be related
to the missed notification.

Distinct from the neighbouring findings: #824 is worker death *with* a
notification (the loss was on-disk state), #827 is a false "worker dead"
inference (the worker was alive), and an elicitation-blocked session surfaces as
`cancelled`, i.e. it *does* notify. #853 is the silent case, which is the worst
one for an orchestrator.

**The platform half is upstream, not in this repo:** guaranteeing an inbox item
for every terminal transition, reconciling a terminal state that emitted no event,
and surfacing partial work are omnigent runner changes. This page carries only the
supervisor-side workaround.

## What this rules out, and what it does not

Ruled out as *sufficient* causes, each by a trial that delivered normally:
pointer-vs-inlined prompt shape (t1/t2), brief length and ceremony (t1/t3),
absence of a turn-end contract (t7), model (t1/t6), agent type — `Explore` and
`debug-lead` both work and both return full output (t4/t5/t11/t12), multi-step
work (t8), and gate-then-push sequencing (t9/t10).

**Not ruled out:** that genuine early terminations also occurred in wave
2026-08-02 alongside the false positives. This reproduction ran 14 dispatches on
one machine on one day; it cannot prove a rate of zero. The honest position is
that the reported evidence — the verbatim preamble strings, the empty outputs,
the pre-push freezes, the 100% rate, and the 100% "recovery" rate — is fully
explained by mid-flight observation, and that no genuine stall was observed under
any of the varied conditions. Before treating a future wave's stalls as real,
apply the discriminator above and record whether a `status=completed`
notification actually existed. If it did, this document is wrong and the trial
table is the place to add the counter-example — as #853 already did for the
omnigent-session substrate, from the other direction (terminal, no notification
at all).

`debug-lead` and `Explore` are **not** unusable and need no substitute; the
evidence that they were came from reading them before they had spoken.
