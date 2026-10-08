---
name: subagent-dispatch
description: Dispatch templates, guardrails, and return verification for spawning subagents — Build Workers inside /build and ad-hoc research/debug/minion dispatch outside it. Use when dispatching an Agent, picking a subagent model, or processing a worker's return — verify the claimed artifact (issue, commit, file, PR) before reporting it done. Trigger on "dispatch a worker/agent", "research X" / "compare X vs Y", "why is X broken?", a bounded minion task, or "did the subagent actually do it?".
---

# Subagent Dispatch

Spawn subagents via the Agent tool **inside `/build`** (Build Lead coordinates Workers and the Reviewer — sections 1–7) or **outside `/build`** (ad-hoc research/debug/minion auto-dispatch — section 8).

> **Runtime (#69):** these roles map to DeepAgents `task`-tool subagents (ADR-2026-05-27) — see the source repository’s build-subagent architecture; this skill is the human-readable dispatch guidance.

## 0. Agent Tool Schema — Use ONLY These Parameters

The Agent tool accepts exactly: `subagent_type`, `description`, `prompt`, `model` (`sonnet`|`opus`|`haiku`), `isolation` (`worktree`|`remote`), `run_in_background`. There is **no `name:` or `mode:` parameter** — put the role/ID label (e.g. `bw-{task}`) in `description`, select the role via `subagent_type`. Permission mode is a session setting.

## 1. Agent Role Reference

`subagent_type` values are prefixed `rpw-published:`. The ID pattern goes in `description`.

| Role | subagent_type | Model | ID | Worktree | Typical Task |
|------|---------------|-------|----|----------|--------------|
| Build Lead | (main agent) | Opus | `build-{feature}` | build | Decompose, coordinate Workers, merge (owns Feature issue) |
| Build Worker | `build-worker` | Opus/Sonnet | `bw-{task}` | task (required) | Implement one Task: tests, code, commit |
| Reviewer | `reviewer` | Opus | `review-{feature}` | none | One fresh-context pass: fail-closed security verdict + simplify/docs checklist (#332); never commits (#206) |
| Research Lead | `research-lead` | Opus | `research-{topic}` | none | Plan + synthesize research |
| Research Worker | `research-worker` | Sonnet | `rw-{topic}-{n}` | none | Fetch/read/summarize one source |
| Debug Lead | `debug-lead` | Opus | `debug-{issue}` | none | Diagnose, recommend fixes |
| Minion | `minion` | Haiku | `minion-{action}` | none | Bounded lookups, renames, metadata, issue creation |

## 2. Build Worker Dispatch Template
```
Agent(
  subagent_type: "rpw-published:build-worker",
  description: "bw-{task-slug}",
  model: "sonnet",          // default; "opus" for complex tasks
  isolation: "worktree",
  run_in_background: true,
  prompt: "... (MUST include absolute worktree path — see section 3)"
)
```

## 3. Prompt Template for Build Workers

Copy the whole prompt body from [`build-worker-prompt.md`](build-worker-prompt.md): scope, absolute worktree path, #135 isolation rules, coordinator-owned ledger, acceptance criteria, constraints, and the commit sha you verify in section 6. Wave workers get [`worker-brief-template.md`](../wave-supervisor/worker-brief-template.md) instead (#492).

## 4. Model Selection

**Sonnet** (default) for implementation, file edits, tests; **Opus** for architecture, complex refactoring, multi-file coordination, Lead roles; **Haiku** for Minion tasks only.

**Delegated mechanical work defaults to an OSS model on FMAPI** (GLM 5.2, Kimi K2.7-code, via `ucode`) — the rubric, the invocation, and the `PATH` precondition are in [`model-selection.md`](model-selection.md) (#915).

## 5. Dispatch Guardrails

- Max **5 Build Workers** per Build Lead; **3 Research Workers** per Research Lead; **5 Minions** per batch.
- Max **depth 1**: subagents are leaves — they **cannot spawn subagents**. For fan-out, dispatch multiple workers from the main conversation and synthesize yourself. **Harness caps:** 5 concurrent, depth 2 (`research-lead` needs 2) — values, fan-out math, and background auto-push in [`autonomy-caps.md`](autonomy-caps.md) (#916).
- **NEVER** dispatch workers that modify the same files in parallel. Shared files (`package.json`, lock files, config) go to ONE worker or are sequenced.
- Build Workers: always `run_in_background: true` + `isolation: "worktree"`, and include the absolute worktree path in the prompt. Research and Debug agents are **read-only** — no file edits.
- **Load/stress harnesses must self-terminate (#644)** — rules in [`load-harness-safety.md`](load-harness-safety.md).
- **The Build Lead owns commit boundaries (#206):** only Build Workers commit. The Reviewer edits, re-runs tests, and reports only; staging is per-file `git add <path>`, never `git add -A`. (#199's doc-only Simplifier carve-out is moot since #332 retired the standing Simplifier.)

### bypassPermissions Security Deny-List

In `bypassPermissions` mode, subagents inherit it and can bypass interactive prompts. To prevent exposure:

- **NEVER** read or write `.env` files, `.env.*`, or any dotenv variants.
- **NEVER** access `~/.aws` credentials, `~/.ssh` keys, or `~/.config` auth tokens.
- **NEVER** commit files matching `.env`, `credentials.json`, `*.pem`, `*.key`.
- Workers must check `git diff --cached` for secret patterns before committing.

## 6. Processing a Worker's Return

**Before calling anything stalled, read [`dispatch-liveness.md`](dispatch-liveness.md) (#773).** Dispatch is always
async; a `status=completed` notification proves an *in-process* subagent stopped —
cross-session omnigent children may never notify (#853), detached `claude -p`
children never notify at all and are read by parsing their log (#974) — and
stopping says nothing about the work.

### Verify the artifact before reporting done (#914)

**A return is a claim, not evidence** — three of nine reviewed omnigent sessions reported success having done nothing observable (upstream, not ours).

**Any dispatch claiming a durable artifact — issue, commit, file, PR, branch, comment — gets the check for its class: run it, read the output, then report. Not optional.** Read-only research/debug dispatches are exempt (their report *is* the artifact), but a `produced no output` return is a failed dispatch, not a finding.

| Claimed artifact | Ground-truth check — the scoping is mandatory |
|---|---|
| Issue filed | `gh issue list --repo <owner>/<repo> --search "<distinctive title words> in:title" --state all --json number,url` |
| Commit landed | the canonical block in [`return-verification.md`](return-verification.md#commit-landed) — `log <base>..<branch> -- <scoped-paths>` **and** `status --porcelain` |
| File written | `test -s <absolute-path> && wc -l <absolute-path>` — non-empty, in the worker's worktree, not yours |
| PR opened | `gh pr view <branch> --repo <owner>/<repo> --json number,url,state,baseRefName,headRefName` — base/head as you asked |

Pin the repo (`--repo`) or worktree (`git -C <abs-path>`, never `cd`) and search distinctive terms: an unscoped check reports a false "unverified". Traps, and `<scoped-paths>`: [`return-verification.md`](return-verification.md).

**Require the identifier, not prose.** End each such prompt with: *last line of your final message = the artifact's identifier (number, sha, URL, or path).* No identifier ⇒ **unverified**; search for it if you can, never upgrade prose to done.

**Report unverified as unverified**, never done: `unverified — <command> returned <output>`. Verified quotes the identifier confirmed.

### Two strikes, then do it yourself

1. **First failure:** re-dispatch **once**, quoting the check that failed and its output.
2. **Second failure, same unit of work:** stop delegating — two failures is where delegation costs more than it saves. Do it directly.
3. **The third attempt is yours, never a third *undiagnosed* dispatch.** If direct work is also blocked, report blocked with both failed checks.
4. **Fenced wave workers invert step 2:** park and escalate — never implement a fenced issue inline (#827). A relaunch carrying a newly diagnosed, written-down cause is not a strike; one rule, in [`return-verification.md`](return-verification.md) (#1021).

### Failure Handling

1. **Assess**: isolated (one task) or systemic (environment, dependency)?
2. **Retry once** if the failure was ambiguous — that is strike two above.
3. **Fallback**: mark the task issue blocked; merge only successful worktrees and report the incomplete ones.
4. **Escalate**: if 3+ workers fail in the same cycle, stop and ask the human.

**Post-dispatch isolation assertion** — after each worker finishes/stalls, the Build Lead runs `git -C <build-worktree-abs-path> status --porcelain` and `rev-parse --abbrev-ref HEAD`. If HEAD is not the feature branch or unexpected files appear, a worker leaked in — STOP merging and warn (#135).

## 7. Merge Protocol & Issue Hierarchy

After a Build Worker succeeds, merge with a **regular (non-squash) merge** — `--squash` breaks `git branch -d`. Run `make verify` after each merge. On failure, do NOT merge; clean up.
```bash
git merge --no-ff <task-branch>
make build-worker-cleanup WORKTREE=<path> BRANCH=<branch>   # canonical cleanup
# manual fallback: git worktree remove -f -f <path>; git branch -D <branch>; git worktree prune
```

**Issue Hierarchy (Build Lead owns it):** the build request issue is the Feature parent (`gh issue create --label feature` if none exists); each work unit is a checklist item or linked task issue; epics use milestones/labels. Workers implement one task and do NOT manage issues; the Build Lead closes them after merge.

## 8. Auto-Dispatch Outside `/build`

When NOT in a `/build` session, auto-dispatch qualifying requests. **This section does NOT apply during `/build`** — that lifecycle uses sections 1–7.

**Inline-first threshold (check FIRST):** if you can answer with ≤3 tool calls using context you have, handle it inline. Dispatch only for 4+ sources/searches, parallel investigation, or fan-out. When uncertain, bias inline.

Every dispatch prompt includes a **Context** block: the user's goal, files/paths examined, approaches tried/rejected, stated preferences/constraints. Fill-in templates and the Result Format live in [`ad-hoc-dispatch.md`](ad-hoc-dispatch.md) — pick the category here, copy the body from there.

### Minion Tasks (Haiku)
Simple, bounded, low-risk: issue creation, renames/metadata, single-value lookups, boilerplate from a template. NOT for judgment, multi-file coordination, or user-facing decisions. Foreground, no worktree. These usually claim a durable artifact → section 6 applies.

### Research Tasks (Opus / Sonnet)
"Research X", "Compare X vs Y", "how does X work here?" — anything needing 3+ sources. NOT for questions answerable from one read/search. Background, read-only, never a worktree. For multi-angle work dispatch up to **3** `research-worker` agents (Sonnet) in ONE message and synthesize yourself.

### Debugging Tasks (Opus)
"Why is X broken?", "this test fails", error/stack-trace reports, "debug this". NOT when the user already knows the fix. Background, diagnose only — never edits files; the main agent implements the fix after reviewing. If an agent surfaces related work, create a GitHub issue and suggest `/build` for non-trivial items.

Present findings by confidence: **high** → summary only; **medium** → + findings + gaps; **low** → full report. Always say what was dispatched and why.
