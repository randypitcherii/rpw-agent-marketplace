# Ad-hoc dispatch templates (outside `/build`)

Companion to [SKILL.md](SKILL.md) section 8, which holds the routing decisions —
the inline-first threshold, which category a request belongs to, and the fan-out
limits. This file is the fill-in-the-braces bodies.

Every prompt carries a **Context** block (the user's goal, files/paths examined,
approaches tried and rejected, stated preferences/constraints), and every
artifact-producing dispatch carries the identifier ask from
[`return-verification.md`](return-verification.md).

## Minion (Haiku)

```
Agent(
  subagent_type: "rpw-published:minion",
  description: "minion-{action}",
  model: "haiku",
  run_in_background: false,     // fast, foreground; no worktree
  prompt: "You are a Minion. Task: {exact-action}. {Context}. Complete this single action, make reasonable assumptions, do not modify files outside scope, return a brief result. Last line: the artifact's identifier (issue number, path, URL)."
)
```

Minion tasks produce durable artifacts more often than any other category —
issue creation is the canonical one — so they are the category most in need of
the section 6 ground-truth check.

## Research Lead (Opus; workers Sonnet)

```
Agent(
  subagent_type: "rpw-published:research-lead",
  description: "research-{topic-slug}",
  model: "opus",
  run_in_background: true,      // read-only, never worktree
  prompt: "You are a Research Lead. Question: {topic}. {Context}. Desired output: {format}. Investigate with parallel tool calls, cite files/URLs, note gaps rather than guess, return early on blocking errors, use the Result Format below."
)
```

For multi-angle research, dispatch up to **3** `research-worker` agents (Sonnet,
background) in ONE message and synthesize yourself.

## Debug Lead (Opus)

```
Agent(
  subagent_type: "rpw-published:debug-lead",
  description: "debug-{issue-slug}",
  model: "opus",
  run_in_background: true,      // diagnose only, NEVER edits files
  prompt: "You are a Debug Lead. Problem: {description + error output}. {Context}. Systematic debugging: reproduce → 2-3 hypotheses → test with parallel tool calls → confirmed root cause → specific fix (file paths). Do NOT edit files. Use the Result Format below."
)
```

The main agent implements the fix after reviewing. If an agent surfaces related
work, create a GitHub issue and suggest `/build` for non-trivial items.

## Result Format (Research/Debug Leads; Minions exempt)

```
**Status**: success|partial|failed    **Confidence**: high|medium|low
**Summary**: 2-3 sentence answer/diagnosis.
**Findings**: key findings with source/file references.
**Gaps**: what couldn't be determined and why.
**Follow-up**: next actions; GitHub issues to create.
```

These two roles are read-only, so they are exempt from the artifact check — but a
return with no findings and no citations, or a `produced no output` return, is a
**failed dispatch**, not a result to pass along (section 6).
