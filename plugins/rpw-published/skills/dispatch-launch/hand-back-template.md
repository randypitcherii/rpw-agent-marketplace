# Hand-back template — when you are asked to dispatch, relaunch, or build it yourself

An orchestrating session (a fleet manager, a chief-of-staff pass, any read-mostly
supervisor) gets asked in passing to *do* the work: "make it figure out what to do with
those workers", "get a cheap fast subagent to build this", "just relaunch the
orchestrator". The hard rule says decline and hand back to `dispatch-launch` or
`wave-kickoff`. The rule is right, but **a bare "no" reads as a stonewall** — and it
costs the user the turn.

Three such asks landed in one day (#1802) and each took ad-hoc reasoning to arrive at
the same answer. This is that answer, canned.

## Who this is for

Any skill whose scope boundary forbids it from spawning build work — an orchestrator,
a reporter, a triage or fleet pass. The receiving skills are the two named below, which
is why the template lives beside them. Link to this file; do not restate it.

## The rule, in one line

> I don't dispatch build work from here — `dispatch-launch` (one issue) and
> `wave-kickoff` (a wave) own spawning, so the launch gets the worktree, brief file,
> liveness gate, and claim check that make it survive.

Say the *reason* in that line. "It's out of scope" is a policy citation; "the launch
path is what gives it a worktree and a liveness gate" is a reason the user can weigh.

## Never decline without one of these two attached

**The decline is half a turn. The other half is mandatory.**

| Pair it with | When | What it looks like |
|---|---|---|
| **(a) findings summary** | you could answer the question read-only — the ask was really "figure out what's going on" | what you probed, what you found, what it implies, and the one decision left |
| **(b) ready-to-execute spec** | the ask was really "build this" | a scoped issue body or brief the launch path can take verbatim, plus "route it to `dispatch-launch` / `wave-kickoff`?" |

If neither is possible, you have not finished investigating. A decline with nothing
attached is never the deliverable.

## Template — (a) findings summary

```markdown
Not dispatching from here — `dispatch-launch` / `wave-kickoff` own spawning, so a
launch through them gets the worktree, brief file, and liveness gate. What I could
establish read-only:

- <probe run> → <result>
- <probe run> → <result>

**What it means:** <the diagnosis in one line>

**Decisions needed**
- <the one thing only you can decide, with concrete options>
```

Worked example — a dead wave orchestrator (`session_not_found`), asked to relaunch it:

```markdown
Not relaunching the orchestrator from here — `wave-kickoff` owns supervisor spawns,
and its liveness gate is the reason a relaunch isn't a coin flip. Read-only findings:

- `GET /v1/sessions/<sid>` → 404; the record is gone, not idle.
- 3 worker sessions still `running`, each with commits on its own branch.
- No `wave/<date>-*` branch on the remote, so nothing was serialized yet.

**What it means:** the workers are healthy and unsupervised. A fresh supervisor over
the same wave branch would re-dispatch issues those three already hold.

**Decisions needed**
- Let the three workers finish and merge their PRs by hand (no new supervisor), or
  re-kick a wave with those three issues on the skip-list?
```

## Template — (b) ready-to-execute spec

```markdown
Not spawning a subagent for this from here — `dispatch-launch` owns it, and going
through it gets the issue, worktree, brief, and claim check. Here is the spec, ready
to execute as-is:

**Scope:** <one line>
**Target files:** <paths>
**Approach:** <the two or three steps>
**Acceptance:** <what proves it done>

Want me to route this to `dispatch-launch`, or file it as an issue for the next wave?
```

## What makes a hand-back fail

- **A bare decline.** No findings, no spec — the user has to re-ask.
- **Citing the rule without the reason.** Sounds arbitrary, invites re-litigation.
- **Doing it anyway "just this once".** The launch path exists because ad-hoc spawns
  skip the claim check and the liveness gate; two sessions then claim one issue.
- **Escalating privileges to get around a sandbox instead of working inside it.** A
  blocked write is a routing signal — write inside the worktree and say where.
- **Offering to route it and then not asking.** End with the actual question, so the
  next message is a yes or no.
