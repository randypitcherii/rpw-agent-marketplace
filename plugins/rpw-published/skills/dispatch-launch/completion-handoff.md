# Completion handoff — the close-out a dispatched session ends with

Companion to [SKILL.md](SKILL.md) (#2343). The next operator needs five answers
without reading the transcript: **what shipped, is it proven, what is deployed, what
is waiting on me, what is left behind.** One format, one source of truth; link to
artifacts instead of narrating them. Prose alone never proves completion.

## The artifacts are the proof; this handoff is the summary (#2449)

Whether work is shipped is a fact about the PR, its issues, the worktree and the
branches, so `rpw sessions classify` reads it from them with `git` + `gh` (no model)
and reports it as `delivery`, next to the session's next action:

```bash
rpw sessions classify <id>                 # one session: action + delivery + checked-at
rpw sessions classify --all --write        # every session; records it on Omnigent
```

`delivery.state`: `shipped` (PR merged, issues closed, branches gone) ·
`cleanup-pending` (merged, something left behind) · `pr-open` · `wip` ·
`nothing-to-ship` · `n/a` (not a git workspace) · `unknown` (no data is never clean).
A verified `shipped` makes the action `archive`, and `cleanup-pending` makes it
`clean_up`, unless the session is still asking you something or working. `--write`
records `rpw.delivery`, `.checked_at`, `.pr`, `.detail` and `rpw.action` labels and turns
a ✅ title to ‼️ when the work is `wip` or its PR into the default branch is still open.
It runs over Omnigent's API, not as a harness hook, so every harness is covered the
same way. **Run `rpw sessions classify <your id>` before writing the block below**
and quote its `delivery` on the `Artifact` line; a block that disagrees with it is wrong.

Why no response-phase policy enforces the block: an Omnigent `response` /
`PHASE_LLM_RESPONSE` DENY replaces the assistant text with a
`[Denied by policy: …]` sentinel and errors the turn. The agent is never re-prompted
to fix it, and the human loses the report. ASK would route the check to the human.
Both add work, so classify labels the session instead (#2426 spike).

## The format

```
Status: ✅ done | 🟡 partial | ⛔ blocked
Artifact: <PR / commit / deployment URL> — <merged | open | none> (checked <how, when>)
Tests/CI: <gate + result> | not run: <why>
Deploy: <env + how verified> | N/A | partial: <what is live, what is not>
Decisions needed: none | 1. <question> — options: A / B
Scheduled/follow-on: <known job run, issue, or "none">
Cleanup: worktree <removed | kept: why> · session <closed | open: why>
Not done: <only for partial / blocked: what remains, who owns it>
```

## Rules (each one exists because the field decides the next move)

- **✅ done needs all three:** an artifact whose state you *checked* (`gh pr view`,
  `git log`, the deploy status call; not your memory of pushing it), a green gate, and
  an explicit cleanup line. Anything less is 🟡.
- **🟡 / ⛔ must fill `Not done`** and must not borrow ✅ words ("shipped", "fixed").
  An open PR is `open`, never `merged`; say which.
- **Deploy is never blank.** `N/A` is an answer; silence is not. A partial deploy
  names what is live and what is not.
- **Cleanup states, it does not perform.** Report what the owning workflow
  (`session-lifecycle.md`) did or why it kept the worktree. Never delete a worktree
  or stop a process just to fill the line.
- **Decisions are numbered with options** (house communication rule), never buried.
- Keep it to one screen. Add no field that does not change what the reader does next.

## Check it

```bash
uv run plugins/rpw-published/skills/dispatch-launch/scripts/handoff-lint.py handoff.md   # or - for stdin
```

Exit 0 = complete and internally consistent; exit 1 prints each problem. Use it on a
child's report before relaying "done" (the verify-the-artifact rule in
`subagent-dispatch`). Covered by `tests/test_dispatch_handoff.py` with a successful,
a blocked, and a partially deployed handoff.
